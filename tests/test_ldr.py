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
        assert result == {"auto_timer_enabled": False}

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
