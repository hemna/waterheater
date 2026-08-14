"""Tests for LDR heater detection logic."""
import json
import sys
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Mock hardware and unavailable modules before importing main
sys.modules['RPi'] = MagicMock()
sys.modules['RPi.GPIO'] = MagicMock()
sys.modules['RpiMotorLib'] = MagicMock()
sys.modules['RpiMotorLib.RpiMotorLib'] = MagicMock()
sys.modules['click'] = MagicMock()
sys.modules['flask'] = MagicMock()
sys.modules['werkzeug'] = MagicMock()
sys.modules['werkzeug.security'] = MagicMock()


class FakeNamespace:
    def __init__(self, *args, **kwargs):
        pass


sys.modules['flask_socketio'] = SimpleNamespace(
    SocketIO=MagicMock(),
    Namespace=FakeNamespace,
)

import main  # noqa: E402


class TestLdrDebounceSamples:
    def test_inconclusive_when_buffer_too_short(self):
        result = main._check_ldr_debounce([0, 0], heater_on_level=0)
        assert result is None

    def test_heater_on_when_all_samples_match_on_level(self):
        result = main._check_ldr_debounce([0, 0, 0], heater_on_level=0)
        assert result is True

    def test_heater_off_when_all_samples_mismatch_on_level(self):
        result = main._check_ldr_debounce([1, 1, 1], heater_on_level=0)
        assert result is False

    def test_inconclusive_when_mixed_samples(self):
        result = main._check_ldr_debounce([0, 1, 0], heater_on_level=0)
        assert result is None

    def test_uses_last_n_samples_only(self):
        # Buffer longer than DEBOUNCE_SAMPLES — only last 3 matter.
        # Last 3 of [1, 1, 1, 0, 0, 0] are [0, 0, 0]; heater_on_level=0 → heater ON
        result = main._check_ldr_debounce([1, 1, 1, 0, 0, 0], heater_on_level=0)
        assert result is True

    def test_empty_buffer_is_inconclusive(self):
        result = main._check_ldr_debounce([], heater_on_level=0)
        assert result is None


class TestLdrSettingsPersistence:
    def test_load_settings_returns_false_when_file_missing(self, tmp_path):
        result = main._load_ldr_settings(str(tmp_path / "missing.json"))
        assert result == {
            "auto_timer_enabled": False,
            "progressive_enabled": False,
            "progressive_min_temp": main.LDR_PROGRESSIVE_MIN_TEMP_DEFAULT,
            "off_reset_minutes": main.HEATER_OFF_RESET_MINUTES_DEFAULT,
        }

    def test_load_settings_reads_existing_file(self, tmp_path):
        f = tmp_path / "ldr.json"
        f.write_text(json.dumps({"auto_timer_enabled": True}))
        result = main._load_ldr_settings(str(f))
        assert result["auto_timer_enabled"] is True

    def test_save_settings_writes_file(self, tmp_path):
        f = tmp_path / "ldr.json"
        main._save_ldr_settings({"auto_timer_enabled": True}, str(f))
        data = json.loads(f.read_text())
        assert data["auto_timer_enabled"] is True

    def test_save_settings_preserves_existing_values(self, tmp_path):
        f = tmp_path / "ldr.json"
        f.write_text(json.dumps({"off_reset_minutes": 15}))
        main._save_ldr_settings({"progressive_enabled": True}, str(f))
        data = json.loads(f.read_text())
        assert data["progressive_enabled"] is True
        assert data["off_reset_minutes"] == 15


class TestLdrStateTransitions:
    def test_off_to_on_transition_sets_heater_on(self):
        """When debounce confirms ON, _heater_on becomes True."""
        main._heater_on = False
        main._ldr_auto_timer_enabled = True
        with patch.object(main, 'sio', MagicMock()), \
             patch('main._start_ldr_timer'):
            main._ldr_poll_tick(0, [0, 0, 0])
        assert main._heater_on is True

    def test_on_to_off_transition_sets_heater_off(self):
        """When debounce confirms OFF, _heater_on becomes False."""
        main._heater_on = True
        main._ldr_saved_temp = None
        with patch.object(main, 'sio', MagicMock()):
            main._ldr_poll_tick(1, [1, 1, 1])
        assert main._heater_on is False

    def test_on_to_off_restores_saved_temp_when_progressive_not_active(self):
        """When heater turns off, progressive NOT active, and temp was reduced, restore it."""
        main._heater_on = True
        main._ldr_saved_temp = 108
        main._ldr_progressive_active = False
        with patch.object(main, 'sio', MagicMock()), \
             patch('main.set_temperature') as mock_set_temp:
            main._ldr_poll_tick(1, [1, 1, 1])
        mock_set_temp.assert_called_once_with(108)
        assert main._ldr_saved_temp is None

    def test_on_to_off_skips_restore_when_progressive_was_active(self):
        """When heater turns off while progressive was actively running, do NOT restore."""
        main._heater_on = True
        main._ldr_saved_temp = 108
        main._ldr_progressive_active = True
        main._ldr_progressive_cancel_event = threading.Event()
        with patch.object(main, 'sio', MagicMock()), \
             patch('main.set_temperature') as mock_set_temp:
            main._ldr_poll_tick(1, [1, 1, 1])
        mock_set_temp.assert_not_called()
        assert main._ldr_saved_temp is None

    def test_on_to_off_does_not_restore_when_no_saved_temp(self):
        """When heater turns off and timer hadn't fired, no temp restore."""
        main._heater_on = True
        main._ldr_saved_temp = None
        with patch.object(main, 'sio', MagicMock()), \
             patch('main.set_temperature') as mock_set_temp:
            main._ldr_poll_tick(1, [1, 1, 1])
        mock_set_temp.assert_not_called()

    def test_off_to_on_starts_timer_when_auto_enabled(self):
        """When heater turns on with auto-timer enabled, _start_ldr_timer is called."""
        main._heater_on = False
        main._ldr_auto_timer_enabled = True
        with patch.object(main, 'sio', MagicMock()), \
             patch('main._start_ldr_timer') as mock_start_timer:
            main._ldr_poll_tick(0, [0, 0, 0])
        mock_start_timer.assert_called_once()
        assert main._heater_on is True

    def test_off_to_on_does_not_start_timer_when_auto_disabled(self):
        """When heater turns on with auto-timer disabled, no timer is started."""
        main._heater_on = False
        main._ldr_auto_timer_enabled = False
        main._ldr_progressive_enabled = False
        with patch.object(main, 'sio', MagicMock()), \
             patch('main._start_ldr_timer') as mock_start_timer:
            main._ldr_poll_tick(0, [0, 0, 0])
        mock_start_timer.assert_not_called()

    def test_off_to_on_restarts_progressive_when_temp_below_reset(self):
        """When heater turns back on below reset temp, progressive cooling resumes."""
        main.CURRENT_TEMPERATURE = 80
        main._heater_on = False
        main._ldr_auto_timer_enabled = False
        main._ldr_progressive_enabled = True
        main._ldr_progressive_active = False
        with patch.object(main, 'sio', MagicMock()), \
             patch('main._start_ldr_timer') as mock_start_timer, \
             patch('main._start_ldr_progressive') as mock_start_progressive:
            main._ldr_poll_tick(0, [0, 0, 0])
        mock_start_timer.assert_not_called()
        mock_start_progressive.assert_called_once()


class TestLdrTimerWorker:
    def test_timer_reduces_temp_after_firing(self):
        """Timer worker saves current temp and sets to 97°F on completion."""
        main.CURRENT_TEMPERATURE = 108
        main._ldr_saved_temp = None
        cancel_event = threading.Event()
        with main._ldr_timer_lock:
            main._ldr_timer_cancel_event = cancel_event
        with patch('main.set_temperature') as mock_set_temp, \
             patch.object(main, 'LDR_AUTO_TIMER_MINUTES', 0.0001), \
             patch.object(main, 'sio', MagicMock()):
            main._ldr_timer_worker()
        assert main._ldr_saved_temp == 108
        mock_set_temp.assert_called_once_with(main.LDR_REDUCED_TEMP)

    def test_timer_does_nothing_when_cancelled(self):
        """Cancelled timer does not change temperature."""
        main.CURRENT_TEMPERATURE = 108
        main._ldr_saved_temp = None
        cancel_event = threading.Event()
        cancel_event.set()  # pre-cancelled
        with main._ldr_timer_lock:
            main._ldr_timer_cancel_event = cancel_event
        with patch('main.set_temperature') as mock_set_temp, \
             patch.object(main, 'sio', MagicMock()):
            main._ldr_timer_worker()
        mock_set_temp.assert_not_called()
        assert main._ldr_saved_temp is None


class TestProgressiveResetTimerInteraction:
    def test_start_progressive_now_cancels_existing_reset_timer(self):
        """Manual progressive cooling must cancel a pending reset-to-108 timer."""
        main.CURRENT_TEMPERATURE = main.LDR_REDUCED_TEMP
        reset_cancel_event = threading.Event()
        with main._timer_lock:
            main._timer_cancel_event = reset_cancel_event
            main._timer_end_timestamp = 123.0
        with main._ldr_timer_lock:
            main._ldr_timer_cancel_event = None
            main._ldr_timer_end_timestamp = None

        namespace = main.ControlNamespace(main.APP_NAMESPACE)
        with patch.object(main, 'sio', MagicMock()), \
             patch('main._start_ldr_progressive'), \
             patch('main._emit_timer_state') as mock_emit_timer_state:
            namespace.on_start_progressive_now({})

        assert reset_cancel_event.is_set()
        assert main._timer_end_timestamp is None
        mock_emit_timer_state.assert_called_once()

    def test_reset_timer_does_not_restore_while_progressive_active(self):
        """An expired reset timer must not undo active progressive cooling."""
        main.CURRENT_TEMPERATURE = 80
        main._ldr_progressive_enabled = True
        main._ldr_progressive_active = True
        reset_cancel_event = MagicMock()
        reset_cancel_event.wait.return_value = False
        with main._timer_lock:
            main._timer_cancel_event = reset_cancel_event
            main._timer_end_timestamp = 0

        with patch.object(main, 'sio', MagicMock()), \
             patch('main.set_temperature') as mock_set_temp, \
             patch('main.time.time', return_value=1):
            main._timer_worker()

        assert main._timer_end_timestamp is None
        mock_set_temp.assert_not_called()

    def test_set_timer_ignored_while_progressive_temp_is_below_reset(self):
        """Progressive low-temp mode must not schedule reset-to-108 timers."""
        main.CURRENT_TEMPERATURE = 80
        main._ldr_progressive_enabled = True
        main._ldr_progressive_active = False
        with main._timer_lock:
            main._timer_cancel_event = None
            main._timer_end_timestamp = None

        namespace = main.ControlNamespace(main.APP_NAMESPACE)
        with patch.object(main, 'sio', MagicMock()), \
             patch('main.threading.Thread') as mock_thread:
            namespace.on_set_timer({"duration_minutes": 15})

        assert main._timer_end_timestamp is None
        mock_thread.assert_not_called()


class TestOffTimerResume:
    def test_resume_off_timer_when_service_starts_off_below_reset(self):
        main._heater_on = False
        main.CURRENT_TEMPERATURE = 80

        with patch('main._start_off_timer') as mock_start_off_timer:
            main._resume_off_timer_if_needed()

        mock_start_off_timer.assert_called_once()


class TestFullStatePayload:
    def test_includes_off_reset_minutes_for_mqtt_clients(self):
        main._heater_off_reset_minutes = 15

        state = main._get_full_state()

        assert state["off_reset_minutes"] == 15
