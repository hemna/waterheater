"""Tests for LDR heater detection logic."""
import json
import os
import sys
import tempfile
import threading
from unittest.mock import MagicMock, patch, call

# Mock hardware and unavailable modules before importing main
sys.modules['RPi'] = MagicMock()
sys.modules['RPi.GPIO'] = MagicMock()
sys.modules['RpiMotorLib'] = MagicMock()
sys.modules['RpiMotorLib.RpiMotorLib'] = MagicMock()
sys.modules['click'] = MagicMock()
sys.modules['flask'] = MagicMock()
sys.modules['flask_socketio'] = MagicMock()

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
        assert result == {"auto_timer_enabled": False, "progressive_enabled": False}

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


class TestLdrStateTransitions:
    def test_off_to_on_transition_sets_heater_on(self):
        """When debounce confirms ON, _heater_on becomes True."""
        main._heater_on = False
        main._ldr_auto_timer_enabled = False
        with patch.object(main, 'sio', MagicMock()), \
             patch('main._start_ldr_timer') as mock_start_timer:
            main._ldr_poll_tick(0, [0, 0, 0])
        assert main._heater_on is True

    def test_on_to_off_transition_sets_heater_off(self):
        """When debounce confirms OFF, _heater_on becomes False."""
        main._heater_on = True
        main._ldr_saved_temp = None
        with patch.object(main, 'sio', MagicMock()):
            main._ldr_poll_tick(1, [1, 1, 1])
        assert main._heater_on is False

    def test_on_to_off_restores_saved_temp(self):
        """When heater turns off and temp was reduced, restore it."""
        main._heater_on = True
        main._ldr_saved_temp = 108
        with patch.object(main, 'sio', MagicMock()), \
             patch('main.set_temperature') as mock_set_temp:
            main._ldr_poll_tick(1, [1, 1, 1])
        mock_set_temp.assert_called_once_with(108)
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
        with patch.object(main, 'sio', MagicMock()), \
             patch('main._start_ldr_timer') as mock_start_timer:
            main._ldr_poll_tick(0, [0, 0, 0])
        mock_start_timer.assert_not_called()


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
