"""Tests for the CPU-runaway fixes (PR: fix/reduce-cpu-logging).

Covers four issues that caused the Raspberry Pi to become unresponsive:
  1. SocketIO engineio_logger/logger/debug flags must be False in production.
  2. motor_go verbose flag must be False to prevent per-step log spam.
  3. _start_timer_worker must use a single blocking wait, not a 1-second poll loop.
  4. _ldr_poll_tick must not call heater_history.get_history/get_stats twice per transition.
"""
import ast
import inspect
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Hardware stub — must happen before importing main
# ---------------------------------------------------------------------------
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

import main  # noqa: E402


# ---------------------------------------------------------------------------
# Fix 1 — SocketIO logger flags
# ---------------------------------------------------------------------------


class TestSocketIOLoggerFlags:
    """Fix 1: engineio_logger, logger, and debug must all be False.

    Passing True floods the Pi SD card with Engine.IO heartbeat/packet logs
    at thousands of lines per minute, saturating I/O and starving sshd.
    """

    def test_socketio_debug_is_false(self):
        src = inspect.getsource(main.init_flask)
        assert "debug=True" not in src, (
            "SocketIO debug=True in init_flask floods logs on the Pi"
        )

    def test_socketio_logger_is_false(self):
        src = inspect.getsource(main.init_flask)
        assert "logger=True" not in src, (
            "SocketIO logger=True in init_flask floods logs on the Pi"
        )

    def test_socketio_engineio_logger_is_false(self):
        src = inspect.getsource(main.init_flask)
        assert "engineio_logger=True" not in src, (
            "SocketIO engineio_logger=True logs every heartbeat packet"
        )


# ---------------------------------------------------------------------------
# Fix 2 — motor_go verbose flag
# ---------------------------------------------------------------------------


class TestMotorGoVerboseFlag:
    """Fix 2: motor_go must be called with verbose=False.

    With verbose=True, RpiMotorLib prints one line per stepper step.
    At 14 steps/degree a 10-degree change emits 140 synchronous log lines
    inside the motor lock, blocking the event loop.
    """

    def test_motor_go_verbose_true_absent_from_source(self):
        src = inspect.getsource(main.motor_control)
        assert "True,  # True = print verbose output" not in src, (
            "motor_go still called with verbose=True — per-step log spam"
        )

    def test_motor_go_called_with_false_verbose(self):
        """motor_go is called with False as the verbose (5th positional) argument."""
        mock_motor = MagicMock()
        mock_a4988 = MagicMock(return_value=mock_motor)

        with patch("main.GPIO"), \
             patch("main.RpiMotorLib.A4988Nema", mock_a4988):
            main.motor_control(10, clockwise=True, steptype="Full")

        args = mock_motor.motor_go.call_args[0]
        assert len(args) >= 5, "motor_go called with fewer args than expected"
        assert args[4] is False, (
            f"motor_go verbose arg is {args[4]!r}, expected False"
        )


# ---------------------------------------------------------------------------
# Fix 3 — _start_timer_worker blocking wait
# ---------------------------------------------------------------------------


class TestStartTimerWorkerBlockingWait:
    """Fix 3: _start_timer_worker must use a single blocking Event.wait()
    for the full duration, not a 1-second poll loop.

    The poll-loop variant wakes every second for the entire timer duration,
    burning unnecessary CPU cycles on the Pi.
    """

    def test_source_has_no_poll_loop(self):
        src = inspect.getsource(main._start_timer_worker)
        assert "while True" not in src, (
            "_start_timer_worker still contains a while True poll loop"
        )

    def test_source_uses_single_blocking_wait_in_ast(self):
        """Count .wait() calls via AST — immune to docstring mentions."""
        src = inspect.getsource(main._start_timer_worker)
        tree = ast.parse(src)
        wait_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "wait"
        ]
        assert len(wait_calls) == 1, (
            f"_start_timer_worker has {len(wait_calls)} .wait() call(s) in AST; expected 1"
        )

    def test_timer_fires_and_sets_temperature(self):
        """When the timer elapses without cancellation, set_temperature is called."""
        cancel_ev = threading.Event()
        with main._start_timer_lock:
            main._start_timer_end_timestamp = time.time() + 0.01  # 10 ms
            main._start_timer_cancel_event = cancel_ev
            main._start_timer_intermediate_temp = 106
            main._start_timer_reset_duration = 0.001

        with patch.object(main, "sio", MagicMock()), \
             patch("main.set_temperature") as mock_set_temp, \
             patch("main.threading.Thread"):
            main._start_timer_worker()

        mock_set_temp.assert_called_once_with(106)
        assert main._start_timer_end_timestamp is None

    def test_timer_cancelled_before_firing(self):
        """When cancelled before elapsing, set_temperature must not be called."""
        cancel_ev = threading.Event()
        with main._start_timer_lock:
            main._start_timer_end_timestamp = time.time() + 60
            main._start_timer_cancel_event = cancel_ev
            main._start_timer_intermediate_temp = 106
            main._start_timer_reset_duration = 30

        threading.Timer(0.02, cancel_ev.set).start()

        with patch.object(main, "sio", MagicMock()), \
             patch("main.set_temperature") as mock_set_temp:
            main._start_timer_worker()

        mock_set_temp.assert_not_called()
        assert main._start_timer_end_timestamp is None

    def test_timer_returns_immediately_when_state_is_none(self):
        """If end timestamp is None (no active timer), worker exits without blocking."""
        with main._start_timer_lock:
            main._start_timer_end_timestamp = None
            main._start_timer_cancel_event = None

        with patch("main.set_temperature") as mock_set_temp:
            main._start_timer_worker()

        mock_set_temp.assert_not_called()


# ---------------------------------------------------------------------------
# Fix 4 — deduplicate heater_history calls in _ldr_poll_tick
# ---------------------------------------------------------------------------


class TestHeaterHistoryDeduplication:
    """Fix 4: _ldr_poll_tick must call get_history() and get_stats() only once
    per ON/OFF transition, sharing the result between MQTT and SocketIO.
    """

    def test_get_history_called_once_on_off_to_on(self):
        main._heater_on = False
        main._ldr_auto_timer_enabled = False
        main._ldr_progressive_enabled = False

        with patch.object(main, "sio", MagicMock()), \
             patch("main.heater_history.get_history", return_value=[]) as mock_hist, \
             patch("main.heater_history.get_stats", return_value={}) as mock_stats, \
             patch("main.heater_history.record_on"), \
             patch("main.mqtt_bridge.publish_history"), \
             patch("main.mqtt_bridge.publish_state"):
            main._ldr_poll_tick(0, [0, 0, 0])

        assert mock_hist.call_count == 1, (
            f"get_history called {mock_hist.call_count}x on ON transition; expected 1"
        )
        assert mock_stats.call_count == 1, (
            f"get_stats called {mock_stats.call_count}x on ON transition; expected 1"
        )

    def test_get_history_called_once_on_on_to_off(self):
        main._heater_on = True
        main._ldr_saved_temp = None
        main._ldr_progressive_active = False
        main.CURRENT_TEMPERATURE = main.RESET_TEMPERATURE

        with patch.object(main, "sio", MagicMock()), \
             patch("main.heater_history.get_history", return_value=[]) as mock_hist, \
             patch("main.heater_history.get_stats", return_value={}) as mock_stats, \
             patch("main.heater_history.record_off"), \
             patch("main.mqtt_bridge.publish_history"), \
             patch("main.mqtt_bridge.publish_state"):
            main._ldr_poll_tick(1, [1, 1, 1])

        assert mock_hist.call_count == 1, (
            f"get_history called {mock_hist.call_count}x on OFF transition; expected 1"
        )
        assert mock_stats.call_count == 1, (
            f"get_stats called {mock_stats.call_count}x on OFF transition; expected 1"
        )

    def test_mqtt_and_socketio_receive_same_history_object(self):
        """MQTT and SocketIO must receive the identical list — not two separate calls."""
        main._heater_on = False
        main._ldr_auto_timer_enabled = False
        main._ldr_progressive_enabled = False

        sentinel_events = [{"start": 1, "end": 2, "duration": 1}]
        sentinel_stats = {"today_events": 1}

        captured_mqtt: dict = {}
        captured_socketio: dict = {}

        def fake_publish_history(events, stats):
            captured_mqtt["events"] = events
            captured_mqtt["stats"] = stats

        def fake_emit(event, data, namespace=None):
            if event == "heater_history":
                captured_socketio["events"] = data["events"]
                captured_socketio["stats"] = data["stats"]

        mock_sio = MagicMock()
        mock_sio.emit.side_effect = fake_emit

        with patch.object(main, "sio", mock_sio), \
             patch("main.heater_history.get_history", return_value=sentinel_events), \
             patch("main.heater_history.get_stats", return_value=sentinel_stats), \
             patch("main.heater_history.record_on"), \
             patch("main.mqtt_bridge.publish_history", side_effect=fake_publish_history), \
             patch("main.mqtt_bridge.publish_state"):
            main._ldr_poll_tick(0, [0, 0, 0])

        assert captured_mqtt.get("events") is sentinel_events, \
            "MQTT did not receive the shared events list"
        assert captured_socketio.get("events") is sentinel_events, \
            "SocketIO did not receive the shared events list"
