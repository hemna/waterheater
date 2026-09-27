"""Tests for the MQTT bridge and the MQTT command surface.

Verifies that every waterheater feature is reachable via waterheater/cmd/<action>
and that MQTT state stays in sync with the web UI.
"""
import sys
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Mock hardware and unavailable modules before importing main
sys.modules.setdefault("RPi", MagicMock())
sys.modules.setdefault("RPi.GPIO", MagicMock())
sys.modules.setdefault("RpiMotorLib", MagicMock())
sys.modules.setdefault("RpiMotorLib.RpiMotorLib", MagicMock())
sys.modules.setdefault("click", MagicMock())
sys.modules.setdefault("flask", MagicMock())
sys.modules.setdefault("werkzeug", MagicMock())
sys.modules.setdefault("werkzeug.security", MagicMock())


class _FakeNamespace:
    def __init__(self, *args, **kwargs):
        pass


sys.modules.setdefault(
    "flask_socketio",
    SimpleNamespace(SocketIO=MagicMock(), Namespace=_FakeNamespace),
)

import heater_history  # noqa: E402
import main  # noqa: E402
import mqtt_bridge  # noqa: E402


class TestMqttCommandSurface:
    """Every waterheater feature must be registered as waterheater/cmd/<action>."""

    EXPECTED_ACTIONS = {
        "set_temperature",
        "change_temperature",
        "set_temperature_reading",
        "set_timer",
        "force_reset",
        "start_progressive",
        "stop_progressive",
        "set_ldr_auto_timer",
        "set_ldr_progressive",
        "set_progressive_floor",
        "set_off_timer_minutes",
        "set_start_timer",
        "cancel_start_timer",
        "cancel_off_timer",
        "move_motor",
        "get_history",
        "get_chart_data",
    }

    def test_all_features_registered(self):
        handlers = main._build_mqtt_handlers()
        assert self.EXPECTED_ACTIONS <= set(handlers), (
            f"Missing MQTT commands: {self.EXPECTED_ACTIONS - set(handlers)}"
        )

    def test_set_temperature_handler(self):
        handlers = main._build_mqtt_handlers()
        with patch("main.set_temperature") as mock_set:
            handlers["set_temperature"]({"temperature": 100})
        mock_set.assert_called_once_with(100)

    def test_change_temperature_handler(self):
        handlers = main._build_mqtt_handlers()
        with patch("main.change_temperature") as mock_change:
            handlers["change_temperature"]({"degrees": -2})
        mock_change.assert_called_once_with(-2)

    def test_set_timer_handler(self):
        handlers = main._build_mqtt_handlers()
        with patch("main._do_set_timer") as mock_timer:
            handlers["set_timer"]({"duration_minutes": 15})
        mock_timer.assert_called_once_with(15.0)

    def test_force_reset_handler(self):
        handlers = main._build_mqtt_handlers()
        with patch("main._do_force_reset") as mock_reset:
            handlers["force_reset"]({})
        mock_reset.assert_called_once()

    def test_set_start_timer_handler(self):
        handlers = main._build_mqtt_handlers()
        with patch("main._do_set_start_timer") as mock_start:
            handlers["set_start_timer"]({"duration_minutes": 15, "intermediate_temperature": 106, "reset_duration_minutes": 30})
        mock_start.assert_called_once_with(15, 106, 30)

    def test_cancel_start_timer_handler(self):
        handlers = main._build_mqtt_handlers()
        with patch("main._do_cancel_start_timer") as mock_cancel:
            handlers["cancel_start_timer"]({})
        mock_cancel.assert_called_once()

    def test_cancel_off_timer_handler(self):
        """The iOS companion app sends cancel_off_timer — it must be registered."""
        handlers = main._build_mqtt_handlers()
        with patch("main._cancel_off_timer") as mock_cancel:
            handlers["cancel_off_timer"]({})
        mock_cancel.assert_called_once()

    def test_move_motor_handler(self):
        handlers = main._build_mqtt_handlers()
        with patch("main._do_move_motor") as mock_move:
            handlers["move_motor"]({"steps": 50, "clockwise": False})
        mock_move.assert_called_once_with(50, "Full", False)

    def test_get_history_handler_publishes_history(self):
        handlers = main._build_mqtt_handlers()
        events = [{"start": 1, "end": 2, "duration": 1}]
        stats = {"total_events": 1}
        with patch("main.mqtt_bridge.publish_history") as mock_pub, \
             patch("main.heater_history.get_history", return_value=events), \
             patch("main.heater_history.get_stats", return_value=stats):
            handlers["get_history"]({})
        mock_pub.assert_called_once_with(events, stats)

    def test_get_chart_data_handler_publishes_chart(self):
        handlers = main._build_mqtt_handlers()
        data = {"labels": [], "values": [], "title": "x"}
        with patch("main.mqtt_bridge.publish_chart_data") as mock_pub, \
             patch("main.heater_history.get_chart_data", return_value=data):
            handlers["get_chart_data"]({"period": "week", "offset": -1})
        mock_pub.assert_called_once_with("week", -1, data)

    def test_get_chart_data_invalid_period_defaults_to_day(self):
        handlers = main._build_mqtt_handlers()
        with patch("main.mqtt_bridge.publish_chart_data") as mock_pub, \
             patch("main.heater_history.get_chart_data", return_value={}):
            handlers["get_chart_data"]({"period": "bogus"})
        assert mock_pub.call_args[0][0] == "day"


class TestMqttAutoTimerDivergence:
    """MQTT enable path must behave identically to the web UI."""

    def test_enable_auto_timer_starts_timer_when_heater_on(self):
        main._heater_on = True
        main._heater_on_since = 123.0
        main._ldr_auto_timer_enabled = False
        with patch("main._start_ldr_timer") as mock_start, \
             patch("main._save_ldr_settings"), \
             patch.object(main, "sio", MagicMock()), \
             patch("main.mqtt_bridge.publish_state"):
            main._do_set_ldr_auto_timer(True)
        mock_start.assert_called_once()

    def test_enable_auto_timer_does_not_start_timer_when_heater_off(self):
        main._heater_on = False
        main._heater_on_since = None
        main._ldr_auto_timer_enabled = False
        with patch("main._start_ldr_timer") as mock_start, \
             patch("main._save_ldr_settings"), \
             patch.object(main, "sio", MagicMock()), \
             patch("main.mqtt_bridge.publish_state"):
            main._do_set_ldr_auto_timer(True)
        mock_start.assert_not_called()
        assert main._ldr_auto_timer_enabled is True

    def test_disable_auto_timer_cancels_running_timer(self):
        ev = threading.Event()
        with main._ldr_timer_lock:
            main._ldr_timer_cancel_event = ev
        main._heater_on = False
        with patch("main._save_ldr_settings"), \
             patch.object(main, "sio", MagicMock()), \
             patch("main.mqtt_bridge.publish_state"):
            main._do_set_ldr_auto_timer(False)
        assert ev.is_set()
        assert main._ldr_auto_timer_enabled is False

    def test_string_false_payload_is_parsed_as_false(self):
        """bool("false") is True — string payloads must be parsed properly."""
        ev = threading.Event()
        with main._ldr_timer_lock:
            main._ldr_timer_cancel_event = ev
        main._ldr_auto_timer_enabled = True
        handlers = main._build_mqtt_handlers()
        with patch("main._save_ldr_settings"), \
             patch.object(main, "sio", MagicMock()), \
             patch("main.mqtt_bridge.publish_state"):
            handlers["set_ldr_auto_timer"]({"enabled": "false"})
        assert main._ldr_auto_timer_enabled is False
        assert ev.is_set()


class TestMqttStatePublishing:
    """MQTT state must be published whenever a feature's state changes."""

    def test_start_timer_state_publishes(self):
        with patch("main.mqtt_bridge.publish_state") as mock_pub, \
             patch.object(main, "sio", MagicMock()):
            main._emit_start_timer_state()
        mock_pub.assert_called_once()

    def test_ldr_timer_state_publishes(self):
        with patch("main.mqtt_bridge.publish_state") as mock_pub, \
             patch.object(main, "sio", MagicMock()):
            main._emit_ldr_timer_state()
        mock_pub.assert_called_once()

    def test_off_timer_state_publishes(self):
        with patch("main.mqtt_bridge.publish_state") as mock_pub, \
             patch.object(main, "sio", MagicMock()):
            main._emit_off_timer_state()
        mock_pub.assert_called_once()

    def test_set_temperature_reading_publishes_state(self):
        with patch("main.save_temperature"), \
             patch("main.mqtt_bridge.publish_state") as mock_pub, \
             patch.object(main, "sio", MagicMock()):
            main._do_set_temperature_reading(110)
        mock_pub.assert_called_once()
        assert main.CURRENT_TEMPERATURE == 110

    def test_full_state_includes_feature_constants(self):
        main._ldr_saved_temp = 108
        state = main._get_full_state()
        assert state["ldr_reduced_temp"] == main.LDR_REDUCED_TEMP
        assert state["progressive_step"] == main.LDR_PROGRESSIVE_STEP
        assert state["progressive_interval_minutes"] == main.LDR_PROGRESSIVE_INTERVAL_MINUTES
        assert state["ldr_saved_temp"] == 108
        assert "temperature" in state
        assert "off_reset_minutes" in state


class TestTemperatureClamp:
    def test_temp_max_is_150(self):
        assert main.TEMP_MAX == 150

    def test_set_temperature_clamps_high(self):
        main.CURRENT_TEMPERATURE = 110
        with patch("main.motor_control"), patch("main.save_temperature"), \
             patch.object(main, "sio", MagicMock()), \
             patch("main.mqtt_bridge.publish_state"):
            main.set_temperature(500)
        assert main.CURRENT_TEMPERATURE == main.TEMP_MAX

    def test_set_temperature_clamps_low(self):
        main.CURRENT_TEMPERATURE = 110
        with patch("main.motor_control"), patch("main.save_temperature"), \
             patch.object(main, "sio", MagicMock()), \
             patch("main.mqtt_bridge.publish_state"):
            main.set_temperature(10)
        assert main.CURRENT_TEMPERATURE == main.TEMP_MIN

    def test_change_temperature_clamps_high(self):
        main.CURRENT_TEMPERATURE = main.TEMP_MAX - 1
        with patch("main.motor_control") as mock_motor, \
             patch("main.save_temperature"), \
             patch.object(main, "sio", MagicMock()), \
             patch("main.mqtt_bridge.publish_state"):
            main.change_temperature(20)
        assert main.CURRENT_TEMPERATURE == main.TEMP_MAX
        # Motor only moved for the clamped delta (1 degree)
        mock_motor.assert_called_once()
        steps = mock_motor.call_args[0][0]
        assert steps == main.DEFAULT_STEPS_PER_DEGREE

    def test_change_temperature_noop_when_clamped_to_current(self):
        main.CURRENT_TEMPERATURE = main.TEMP_MAX
        with patch("main.motor_control") as mock_motor, \
             patch("main.save_temperature"), \
             patch.object(main, "sio", MagicMock()), \
             patch("main.mqtt_bridge.publish_state"):
            main.change_temperature(5)
        mock_motor.assert_not_called()


class TestDoMoveMotor:
    def test_clamps_to_temp_min_when_clockwise(self):
        main.CURRENT_TEMPERATURE = main.TEMP_MIN + 1
        with patch("main.motor_control") as mock_motor, \
             patch.object(main, "sio", MagicMock()):
            main._do_move_motor(10000, "Full", True)
        assert mock_motor.call_args[0][0] == main.DEFAULT_STEPS_PER_DEGREE
        assert main.CURRENT_TEMPERATURE == main.TEMP_MIN

    def test_clamps_to_temp_max_when_ccw(self):
        main.CURRENT_TEMPERATURE = main.TEMP_MAX - 1
        with patch("main.motor_control") as mock_motor, \
             patch.object(main, "sio", MagicMock()):
            main._do_move_motor(10000, "Full", False)
        assert mock_motor.call_args[0][0] == main.DEFAULT_STEPS_PER_DEGREE
        assert main.CURRENT_TEMPERATURE == main.TEMP_MAX

    def test_parses_string_false_clockwise_once(self):
        """String 'false' must parse to False for BOTH the motor and the message."""
        main.CURRENT_TEMPERATURE = 110
        with patch("main.motor_control") as mock_motor, \
             patch.object(main, "sio", MagicMock()) as mock_sio:
            main._do_move_motor(14, "Full", "false")
        assert mock_motor.call_args[0][0] == 14
        assert mock_motor.call_args[1]["clockwise"] is False
        assert main.CURRENT_TEMPERATURE == 111
        msg = mock_sio.emit.call_args[0][1]["message"]
        assert "CCW" in msg

    def test_keeps_temperature_in_sync_with_partial_steps(self):
        main.CURRENT_TEMPERATURE = 110
        with patch("main.motor_control") as mock_motor, \
             patch.object(main, "sio", MagicMock()):
            main._do_move_motor(7, "Full", True)
        assert mock_motor.call_args[0][0] == 7
        assert main.CURRENT_TEMPERATURE == 110 - 7 / main.DEFAULT_STEPS_PER_DEGREE

    def test_move_motor_handler_passes_raw_clockwise_string(self):
        handlers = main._build_mqtt_handlers()
        with patch("main._do_move_motor") as mock_move:
            handlers["move_motor"]({"steps": 50, "clockwise": "false"})
        mock_move.assert_called_once_with(50, "Full", "false")

    def test_negative_steps_are_rejected(self):
        """Negative steps must not move the dial or change CURRENT_TEMPERATURE."""
        main.CURRENT_TEMPERATURE = 110
        with patch("main.motor_control") as mock_motor, \
             patch.object(main, "sio", MagicMock()):
            main._do_move_motor(-28, "Full", True)
        mock_motor.assert_not_called()
        assert main.CURRENT_TEMPERATURE == 110


class TestDoSetTimer:
    def test_returns_false_when_progressive_owns_temp(self):
        main.CURRENT_TEMPERATURE = 80
        main._ldr_progressive_enabled = True
        with main._timer_lock:
            main._timer_cancel_event = None
            main._timer_end_timestamp = None
        with patch("main.threading.Thread") as mock_thread:
            assert main._do_set_timer(15) is False
        mock_thread.assert_not_called()

    def test_starts_timer_when_allowed(self):
        main.CURRENT_TEMPERATURE = main.RESET_TEMPERATURE
        main._ldr_progressive_enabled = False
        with patch("main.threading.Thread") as mock_thread, \
             patch("main._emit_timer_state"):
            assert main._do_set_timer(15) is True
        mock_thread.assert_called_once()


class TestAsBool:
    def test_parses_common_string_forms(self):
        assert main._as_bool("true") is True
        assert main._as_bool("1") is True
        assert main._as_bool("yes") is True
        assert main._as_bool("false") is False
        assert main._as_bool("0") is False
        assert main._as_bool("no") is False

    def test_passes_through_bools_and_ints(self):
        assert main._as_bool(True) is True
        assert main._as_bool(False) is False
        assert main._as_bool(1) is True
        assert main._as_bool(0) is False


class TestHeaterHistoryFixes:
    def teardown_method(self):
        heater_history._history = []

    def test_record_on_discards_orphan_open_event(self, tmp_path, monkeypatch):
        """An orphaned open event (end=None) is discarded, not counted as completed."""
        monkeypatch.setattr(heater_history, "HISTORY_FILE", str(tmp_path / "h.json"))
        heater_history._history = [{"start": 100.0, "end": None, "duration": None}]
        heater_history.record_on(200.0)
        assert len(heater_history._history) == 1
        assert heater_history._history[0]["start"] == 200.0
        assert heater_history._history[0]["end"] is None

    def test_stats_today_uses_local_midnight(self, tmp_path, monkeypatch):
        import datetime

        monkeypatch.setattr(heater_history, "HISTORY_FILE", str(tmp_path / "h.json"))
        now = datetime.datetime.now()
        today_local_midnight = datetime.datetime(now.year, now.month, now.day).timestamp()
        # Event yesterday (just before local midnight) — not today
        heater_history._history = [
            {"start": today_local_midnight - 3600, "end": today_local_midnight - 3500, "duration": 100.0},
        ]
        stats = heater_history.get_stats()
        assert stats["today_events"] == 0

    def test_stats_counts_event_after_local_midnight(self, tmp_path, monkeypatch):
        import datetime

        monkeypatch.setattr(heater_history, "HISTORY_FILE", str(tmp_path / "h.json"))
        now = datetime.datetime.now()
        today_local_midnight = datetime.datetime(now.year, now.month, now.day).timestamp()
        heater_history._history = [
            {"start": today_local_midnight + 60, "end": today_local_midnight + 160, "duration": 100.0},
        ]
        stats = heater_history.get_stats()
        assert stats["today_events"] == 1


class TestMqttBridge:
    def teardown_method(self):
        mqtt_bridge._client = None
        mqtt_bridge._connected = False
        mqtt_bridge._get_state_fn = None
        mqtt_bridge._cmd_handlers = {}

    def test_on_message_routes_to_handler(self):
        calls = []
        mqtt_bridge._cmd_handlers = {"set_temperature": lambda d: calls.append(d)}
        msg = SimpleNamespace(topic="waterheater/cmd/set_temperature", payload=b'{"temperature": 100}')
        mqtt_bridge._on_message(None, None, msg)
        assert calls == [{"temperature": 100}]

    def test_on_message_unknown_command_does_not_raise(self):
        mqtt_bridge._cmd_handlers = {}
        msg = SimpleNamespace(topic="waterheater/cmd/nope", payload=b"{}")
        mqtt_bridge._on_message(None, None, msg)

    def test_on_message_bad_payload_does_not_raise(self):
        mqtt_bridge._cmd_handlers = {}
        msg = SimpleNamespace(topic="waterheater/cmd/set_temperature", payload=b"not json")
        mqtt_bridge._on_message(None, None, msg)

    def test_publish_state_retains_payload(self):
        mock_client = MagicMock()
        mqtt_bridge._client = mock_client
        mqtt_bridge._connected = True
        mqtt_bridge._get_state_fn = lambda: {"temperature": 100}
        mqtt_bridge.publish_state()
        _, kwargs = mock_client.publish.call_args
        assert kwargs.get("retain") is True

    def test_publish_chart_data_not_retained(self):
        mock_client = MagicMock()
        mqtt_bridge._client = mock_client
        mqtt_bridge._connected = True
        mqtt_bridge.publish_chart_data("day", 0, {"labels": []})
        _, kwargs = mock_client.publish.call_args
        assert kwargs.get("retain") is False

    def test_publish_history_retains_payload(self):
        mock_client = MagicMock()
        mqtt_bridge._client = mock_client
        mqtt_bridge._connected = True
        mqtt_bridge.publish_history([], {"total_events": 0})
        _, kwargs = mock_client.publish.call_args
        assert kwargs.get("retain") is True

    def test_publish_noop_when_disconnected(self):
        mock_client = MagicMock()
        mqtt_bridge._client = mock_client
        mqtt_bridge._connected = False
        mqtt_bridge._get_state_fn = lambda: {"temperature": 100}
        mqtt_bridge.publish_state()
        mock_client.publish.assert_not_called()


class TestMqttConfig:
    def test_remote_broker_defaults_to_tls_8883(self):
        use_tls, port = mqtt_bridge._resolve_tls_and_port("cloud.hemna.com", None)
        assert use_tls is True
        assert port == 8883

    def test_local_broker_defaults_to_plaintext_1883(self):
        for host in ("localhost", "127.0.0.1", "::1"):
            use_tls, port = mqtt_bridge._resolve_tls_and_port(host, None)
            assert use_tls is False
            assert port == 1883

    def test_explicit_tls_env_wins(self):
        assert mqtt_bridge._resolve_tls_and_port("localhost", "1") == (True, 8883)
        assert mqtt_bridge._resolve_tls_and_port("cloud.hemna.com", "0") == (False, 1883)

    def test_init_remote_with_default_creds_does_not_start(self, monkeypatch):
        fake_mqtt = SimpleNamespace(
            Client=MagicMock(),
            MQTTv311="3.1.1",
            CallbackAPIVersion=SimpleNamespace(VERSION2=2),
        )
        monkeypatch.setattr(mqtt_bridge, "mqtt", fake_mqtt)
        monkeypatch.setattr(mqtt_bridge, "MQTT_BROKER", "cloud.hemna.com")
        monkeypatch.setattr(mqtt_bridge, "MQTT_USERNAME", "waterheater")
        monkeypatch.setattr(mqtt_bridge, "MQTT_PASSWORD", "waterheater")
        with patch("mqtt_bridge.threading.Thread"):
            mqtt_bridge.init(lambda: {}, {})
        assert mqtt_bridge._get_state_fn is None

    def test_init_local_with_default_creds_starts(self, monkeypatch):
        fake_mqtt = SimpleNamespace(
            Client=MagicMock(),
            MQTTv311="3.1.1",
            CallbackAPIVersion=SimpleNamespace(VERSION2=2),
        )
        monkeypatch.setattr(mqtt_bridge, "mqtt", fake_mqtt)
        monkeypatch.setattr(mqtt_bridge, "MQTT_BROKER", "localhost")
        monkeypatch.setattr(mqtt_bridge, "MQTT_USERNAME", "waterheater")
        monkeypatch.setattr(mqtt_bridge, "MQTT_PASSWORD", "waterheater")
        with patch("mqtt_bridge.threading.Thread"):
            mqtt_bridge.init(lambda: {"x": 1}, {})
        assert mqtt_bridge._get_state_fn is not None
