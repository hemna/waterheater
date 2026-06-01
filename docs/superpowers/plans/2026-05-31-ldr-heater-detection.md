# LDR Heater Detection Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LDR photoresistor-based burner detection to the water heater controller — show a big red indicator in the UI, and optionally auto-reduce temp to 97°F after 15 minutes, restoring when the burner turns off.

**Architecture:** A background polling thread reads a GPIO digital input (LDR module DO pin) every 250ms with a 3-sample software debounce. State transitions trigger Socket.IO events to the browser and optionally start a 15-minute timer. All new backend logic lives in `main.py` following existing patterns; frontend changes are to `index.html`, `main.css`, and `main.js`.

**Tech Stack:** Python 3.11, RPi.GPIO (via rpi-lgpio), Flask-SocketIO, threading, jQuery, Bootstrap 5, pytest (new dev dep)

**Spec:** `docs/superpowers/specs/2026-05-31-ldr-heater-detection-design.md`

---

## Chunk 1: Backend

### Task 1: Add pytest dev dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add pytest to pyproject.toml**

Add an optional dev dependency group:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]
```

- [ ] **Step 2: Install it**

```bash
uv pip install pytest
```

Expected: pytest installed in `.venv`

- [ ] **Step 3: Verify pytest works**

```bash
python -m pytest --version
```

Expected: `pytest 8.x.x`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add pytest dev dependency"
```

---

### Task 2: Add LDR constants and state variables to main.py

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add constants after existing GPIO pin definitions**

In `main.py`, find the block:
```python
direction = 22  # Direction (DIR) GPIO Pin
step = 23  # Step GPIO Pin
EN_pin = 24  # enable pin (LOW to enable)
```

Add immediately after:
```python
# LDR sensor (photoresistor) GPIO config
# DO pin goes LOW when light detected (heater burner on)
# Update LDR_GPIO_PIN to the correct pin once hardware is wired
LDR_GPIO_PIN = 25
LDR_HEATER_ON_LEVEL = 0        # GPIO.LOW — DO goes LOW when light detected
LDR_POLL_INTERVAL = 0.25       # seconds between GPIO reads
LDR_DEBOUNCE_SAMPLES = 3       # consecutive matching reads to confirm state change
LDR_AUTO_TIMER_MINUTES = 15
LDR_REDUCED_TEMP = 97
LDR_SETTINGS_FILE = "/tmp/ldr_settings.json"
```

- [ ] **Step 2: Add state variables near the existing timer state variables**

Find the block starting with `_timer_end_timestamp`:
```python
_timer_end_timestamp = None
_timer_cancel_event = None
_timer_lock = threading.Lock()
```

Add after the last timer state block:
```python
# LDR heater detection state
_heater_on = False
_ldr_auto_timer_enabled = False   # persisted to LDR_SETTINGS_FILE
_ldr_saved_temp = None            # temp to restore when heater turns off
_ldr_timer_cancel_event = None    # threading.Event to cancel 15-min timer
_ldr_timer_lock = threading.Lock()
```

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add LDR constants and state variables"
```

---

### Task 3: Implement debounce helper and tests

**Files:**
- Modify: `main.py`
- Create: `tests/test_ldr.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ldr.py`:

```python
"""Tests for LDR heater detection logic."""
import sys
from unittest.mock import MagicMock

# Mock hardware modules before importing main
sys.modules['RPi'] = MagicMock()
sys.modules['RPi.GPIO'] = MagicMock()
sys.modules['RpiMotorLib'] = MagicMock()
sys.modules['RpiMotorLib.RpiMotorLib'] = MagicMock()

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
        # Buffer longer than DEBOUNCE_SAMPLES — only last 3 matter
        result = main._check_ldr_debounce([1, 1, 1, 0, 0, 0], heater_on_level=0)
        assert result is False

    def test_empty_buffer_is_inconclusive(self):
        result = main._check_ldr_debounce([], heater_on_level=0)
        assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_ldr.py -v
```

Expected: `AttributeError: module 'main' has no attribute '_check_ldr_debounce'`

- [ ] **Step 3: Implement `_check_ldr_debounce` in main.py**

Add this function near the LDR state variables:

```python
def _check_ldr_debounce(buffer: list, heater_on_level: int):
    """
    Inspect the rolling sample buffer and return a confirmed state or None.

    Returns:
        True  — heater is ON (all last N samples == heater_on_level)
        False — heater is OFF (all last N samples != heater_on_level)
        None  — inconclusive (buffer too short or mixed readings)
    """
    if len(buffer) < LDR_DEBOUNCE_SAMPLES:
        return None
    last_n = buffer[-LDR_DEBOUNCE_SAMPLES:]
    if all(r == heater_on_level for r in last_n):
        return True
    if all(r != heater_on_level for r in last_n):
        return False
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_ldr.py::TestLdrDebounceSamples -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_ldr.py
git commit -m "feat: add LDR debounce helper with tests"
```

---

### Task 4: LDR settings persistence (load/save)

**Files:**
- Modify: `main.py`
- Modify: `tests/test_ldr.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_ldr.py`:

```python
import json
import os
import tempfile


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_ldr.py::TestLdrSettingsPersistence -v
```

Expected: `AttributeError: module 'main' has no attribute '_load_ldr_settings'`

- [ ] **Step 3: Implement persistence functions in main.py**

Add near the LDR state variables:

```python
def _load_ldr_settings(path: str = LDR_SETTINGS_FILE) -> dict:
    """Load LDR settings from JSON file. Returns defaults if missing or corrupt."""
    defaults = {"auto_timer_enabled": False}
    if not os.path.exists(path):
        return defaults
    try:
        with open(path, "r") as f:
            return {**defaults, **json.load(f)}
    except Exception:
        return defaults


def _save_ldr_settings(settings: dict, path: str = LDR_SETTINGS_FILE) -> None:
    """Persist LDR settings to JSON file."""
    try:
        with open(path, "w") as f:
            json.dump(settings, f)
    except Exception as e:
        print(f"Failed to save LDR settings: {e}")
```

- [ ] **Step 4: Load settings at startup**

In `main.py`, find `load_temperature()` call at startup in `if __name__ == "__main__":` and add after it:

```python
settings = _load_ldr_settings()
_ldr_auto_timer_enabled = settings["auto_timer_enabled"]
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_ldr.py -v
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_ldr.py
git commit -m "feat: add LDR settings load/save with tests"
```

---

### Task 5: LDR polling thread

**Files:**
- Modify: `main.py`
- Modify: `tests/test_ldr.py`

- [ ] **Step 1: Write failing tests for state transition logic**

Add to `tests/test_ldr.py`:

```python
from unittest.mock import patch, call


class TestLdrStateTransitions:
    def test_off_to_on_transition_sets_heater_on(self):
        """When debounce confirms ON, _heater_on becomes True."""
        main._heater_on = False
        main._ldr_auto_timer_enabled = False
        with patch.object(main, 'sio', MagicMock()), \
             patch('main.GPIO') as mock_gpio:
            mock_gpio.input.return_value = 0  # LOW = heater on
            # Run enough ticks to fill debounce buffer
            main._ldr_poll_tick(mock_gpio.input.return_value, [0, 0, 0])
        assert main._heater_on is True

    def test_on_to_off_transition_sets_heater_off(self):
        """When debounce confirms OFF, _heater_on becomes False."""
        main._heater_on = True
        main._ldr_saved_temp = None
        with patch.object(main, 'sio', MagicMock()):
            main._ldr_poll_tick(1, [1, 1, 1])  # HIGH = heater off
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_ldr.py::TestLdrStateTransitions -v
```

Expected: `AttributeError: module 'main' has no attribute '_ldr_poll_tick'`

- [ ] **Step 3: Implement `_ldr_poll_tick` and `_ldr_polling_thread` in main.py**

Add after `_check_ldr_debounce`:

```python
def _emit_heater_state():
    """Broadcast current heater on/off state and auto-timer setting to all clients."""
    sio.emit(
        "heater_state",
        {"on": _heater_on, "auto_timer_enabled": _ldr_auto_timer_enabled},
        namespace=APP_NAMESPACE,
    )


def _ldr_poll_tick(reading: int, buffer: list) -> None:
    """
    Process one LDR sample. Updates global heater state and triggers side effects.

    Args:
        reading: Raw GPIO value (0=LOW, 1=HIGH)
        buffer:  Rolling sample buffer (last LDR_DEBOUNCE_SAMPLES readings)
    """
    global _heater_on, _ldr_saved_temp, _ldr_timer_cancel_event

    confirmed = _check_ldr_debounce(buffer, LDR_HEATER_ON_LEVEL)
    if confirmed is None:
        return  # inconclusive — wait for more samples
    if confirmed == _heater_on:
        return  # no change

    if confirmed is True:
        # OFF → ON transition
        _heater_on = True
        _emit_heater_state()
        if _ldr_auto_timer_enabled:
            _start_ldr_timer()
    else:
        # ON → OFF transition
        _heater_on = False
        _emit_heater_state()
        # Cancel LDR timer if still running
        with _ldr_timer_lock:
            ev = _ldr_timer_cancel_event
        if ev:
            ev.set()
        # Restore temperature if it was reduced
        if _ldr_saved_temp is not None:
            set_temperature(_ldr_saved_temp)
            _ldr_saved_temp = None


def _ldr_polling_thread():
    """Background daemon thread: polls LDR GPIO pin every LDR_POLL_INTERVAL seconds."""
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(LDR_GPIO_PIN, GPIO.IN)
    buffer = []
    while True:
        reading = GPIO.input(LDR_GPIO_PIN)
        buffer.append(reading)
        # Keep buffer from growing indefinitely
        if len(buffer) > LDR_DEBOUNCE_SAMPLES * 2:
            buffer = buffer[-LDR_DEBOUNCE_SAMPLES:]
        _ldr_poll_tick(reading, buffer)
        time.sleep(LDR_POLL_INTERVAL)
```

- [ ] **Step 4: Start polling thread at app startup**

In `if __name__ == "__main__":`, after `sio = init_flask()`, add:

```python
threading.Thread(target=_ldr_polling_thread, daemon=True).start()
print("LDR polling thread started")
```

- [ ] **Step 5: Run all tests**

```bash
python -m pytest tests/test_ldr.py -v
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_ldr.py
git commit -m "feat: add LDR polling thread with state transition logic"
```

---

### Task 6: LDR timer worker

**Files:**
- Modify: `main.py`
- Modify: `tests/test_ldr.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_ldr.py`:

```python
import threading


class TestLdrTimerWorker:
    def test_timer_reduces_temp_after_firing(self):
        """Timer worker saves current temp and sets to 97°F on completion."""
        main.CURRENT_TEMPERATURE = 108
        main._ldr_saved_temp = None
        cancel_event = threading.Event()
        with main._ldr_timer_lock:
            main._ldr_timer_cancel_event = cancel_event
        with patch('main.set_temperature') as mock_set_temp, \
             patch('main.LDR_AUTO_TIMER_MINUTES', 0.0001):  # fire immediately
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
        with patch('main.set_temperature') as mock_set_temp:
            main._ldr_timer_worker()
        mock_set_temp.assert_not_called()
        assert main._ldr_saved_temp is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_ldr.py::TestLdrTimerWorker -v
```

Expected: `AttributeError: module 'main' has no attribute '_ldr_timer_worker'`

- [ ] **Step 3: Implement `_ldr_timer_worker` and `_start_ldr_timer` in main.py**

Add after `_ldr_polling_thread`:

```python
def _start_ldr_timer():
    """Start the 15-minute LDR auto-timer. Cancels any existing one."""
    global _ldr_timer_cancel_event
    with _ldr_timer_lock:
        if _ldr_timer_cancel_event:
            _ldr_timer_cancel_event.set()
        _ldr_timer_cancel_event = threading.Event()
    threading.Thread(target=_ldr_timer_worker, daemon=True).start()
    print(f"LDR auto-timer started: will reduce to {LDR_REDUCED_TEMP}°F in {LDR_AUTO_TIMER_MINUTES} min")


def _ldr_timer_worker():
    """Background thread: wait LDR_AUTO_TIMER_MINUTES, then save temp and reduce to 97°F."""
    global _ldr_saved_temp, _ldr_timer_cancel_event
    with _ldr_timer_lock:
        cancel_ev = _ldr_timer_cancel_event
    if cancel_ev is None:
        return
    duration_seconds = LDR_AUTO_TIMER_MINUTES * 60
    if cancel_ev.wait(timeout=duration_seconds):
        # Cancelled before timer fired
        print("LDR auto-timer cancelled")
        return
    # Timer fired — save current temp and reduce
    _ldr_saved_temp = CURRENT_TEMPERATURE
    set_temperature(LDR_REDUCED_TEMP)
    print(f"LDR auto-timer fired: saved {_ldr_saved_temp}°F, reduced to {LDR_REDUCED_TEMP}°F")
```

- [ ] **Step 4: Run all tests**

```bash
python -m pytest tests/test_ldr.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_ldr.py
git commit -m "feat: add LDR auto-timer worker with tests"
```

---

### Task 7: Socket.IO event handlers + on_connect update

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add `on_set_ldr_auto_timer` to `ControlNamespace`**

In `main.py`, inside `class ControlNamespace(Namespace)`, add after `on_cancel_start_timer`:

```python
def on_set_ldr_auto_timer(self, data):
    """Enable or disable the LDR auto-timer. Persists to file."""
    global _ldr_auto_timer_enabled, _ldr_timer_cancel_event
    enabled = bool(data.get("enabled", False))
    _ldr_auto_timer_enabled = enabled
    _save_ldr_settings({"auto_timer_enabled": enabled})
    # If disabling while a timer is running, cancel it
    if not enabled:
        with _ldr_timer_lock:
            ev = _ldr_timer_cancel_event
        if ev:
            ev.set()
    _emit_heater_state()
    print(f"LDR auto-timer {'enabled' if enabled else 'disabled'}")
```

- [ ] **Step 2: Update `on_connect` to emit heater state**

Find `on_connect` in `ControlNamespace`:
```python
def on_connect(self):
    global sio
    print("Client connected")
    sio.emit(
        "motor_status", {"message": "Connected to server"}, namespace=APP_NAMESPACE
    )
    _emit_timer_state()
    _emit_start_timer_state()
```

Add `_emit_heater_state()` at the end:
```python
def on_connect(self):
    global sio
    print("Client connected")
    sio.emit(
        "motor_status", {"message": "Connected to server"}, namespace=APP_NAMESPACE
    )
    _emit_timer_state()
    _emit_start_timer_state()
    _emit_heater_state()
```

- [ ] **Step 3: Verify the app starts without errors (syntax check)**

```bash
python -c "import ast; ast.parse(open('main.py').read()); print('syntax OK')"
```

Expected: `syntax OK`

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: add LDR Socket.IO event handlers and on_connect emit"
```

---

## Chunk 2: Frontend

### Task 8: Add heater status card to HTML

**Files:**
- Modify: `web/templates/index.html`

- [ ] **Step 1: Add heater status card as the first card inside `<main class="app-main">`**

Find in `web/templates/index.html`:
```html
<main class="app-main">
            <section class="card card-temp">
```

Insert before `<section class="card card-temp">`:

```html
<section class="card card-heater">
                <h2 class="card-title">Heater Status</h2>
                <div class="heater-indicator-wrap">
                    <div id="heaterIndicator" class="heater-indicator heater-indicator--off" aria-label="Heater status indicator"></div>
                    <p id="heaterLabel" class="heater-label">Heater OFF</p>
                </div>
                <div class="heater-auto">
                    <label class="heater-auto-label">
                        <input type="checkbox" id="ldrAutoTimer" class="heater-auto-checkbox">
                        Auto-reduce to 97°F after 15 min
                    </label>
                    <span class="form-text heater-auto-hint">When burner turns off, temperature is restored automatically.</span>
                </div>
            </section>
```

- [ ] **Step 2: Commit**

```bash
git add web/templates/index.html
git commit -m "feat: add heater status card to HTML"
```

---

### Task 9: Add indicator CSS styles

**Files:**
- Modify: `web/static/main.css`

- [ ] **Step 1: Add heater indicator styles at the end of main.css**

```css
/* ─── Heater status indicator ─── */

.heater-indicator-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
    padding: 1rem 0;
}

.heater-indicator {
    width: 80px;
    height: 80px;
    border-radius: 50%;
    transition: background-color 0.3s ease, box-shadow 0.3s ease;
}

.heater-indicator--off {
    background-color: #374151;
    box-shadow: none;
}

.heater-indicator--on {
    background-color: #ef4444;
    box-shadow: 0 0 24px 8px rgba(239, 68, 68, 0.5);
    animation: heater-pulse 1.4s ease-in-out infinite;
}

@keyframes heater-pulse {
    0%, 100% {
        box-shadow: 0 0 24px 8px rgba(239, 68, 68, 0.5);
    }
    50% {
        box-shadow: 0 0 40px 16px rgba(239, 68, 68, 0.8);
    }
}

.heater-label {
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-muted);
    margin: 0;
}

.heater-label--on {
    color: #ef4444;
}

.heater-auto {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    padding-top: 0.5rem;
    border-top: 1px solid var(--border);
}

.heater-auto-label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.9rem;
    cursor: pointer;
}

.heater-auto-checkbox {
    width: 16px;
    height: 16px;
    cursor: pointer;
}

.heater-auto-hint {
    font-size: 0.8rem;
    color: var(--text-muted);
}
```

- [ ] **Step 2: Verify CSS variable names match existing ones**

```bash
grep -n '\-\-text-muted\|\-\-border' web/static/main.css | head -10
```

Expected: lines showing those variables defined. If the variable names differ, update the new CSS to match.

- [ ] **Step 3: Commit**

```bash
git add web/static/main.css
git commit -m "feat: add heater indicator CSS with pulse animation"
```

---

### Task 10: Wire up Socket.IO in main.js

**Files:**
- Modify: `web/static/main.js`

- [ ] **Step 1: Add heater state handler and auto-timer checkbox to main.js**

In `web/static/main.js`, find the last `socket.on(...)` block and add after it:

```javascript
// ── LDR heater detection ──────────────────────────────────────────────
socket.on('heater_state', function(msg) {
    var on = msg.on;
    var indicator = document.getElementById('heaterIndicator');
    var label = document.getElementById('heaterLabel');
    var checkbox = document.getElementById('ldrAutoTimer');

    if (on) {
        indicator.classList.remove('heater-indicator--off');
        indicator.classList.add('heater-indicator--on');
        label.textContent = 'Heater ON';
        label.classList.add('heater-label--on');
    } else {
        indicator.classList.remove('heater-indicator--on');
        indicator.classList.add('heater-indicator--off');
        label.textContent = 'Heater OFF';
        label.classList.remove('heater-label--on');
    }

    if (checkbox) {
        checkbox.checked = msg.auto_timer_enabled;
    }
});
```

- [ ] **Step 2: Add checkbox change handler inside the existing `$(document).ready` block**

Find the last `$("#cancelStartTimer").click(...)` handler and add after it:

```javascript
$("#ldrAutoTimer").change(function() {
    socket.emit('set_ldr_auto_timer', {'enabled': $(this).is(':checked')});
});
```

- [ ] **Step 3: Verify no JS syntax errors**

Open the page in a browser (or run):
```bash
node --input-type=module < web/static/main.js 2>&1 | head -5
```

Expected: no syntax errors (some `socket`/`$` reference errors are fine since those are browser globals)

- [ ] **Step 4: Commit**

```bash
git add web/static/main.js
git commit -m "feat: add heater state Socket.IO handler and auto-timer checkbox"
```

---

## Chunk 3: Integration & Cleanup

### Task 11: Update LDR_GPIO_PIN when hardware arrives

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Wire the LDR module to the Raspberry Pi**

Connect:
- VCC → 3.3V or 5V pin
- GND → GND pin
- DO → a free GPIO pin (note the BCM number)

- [ ] **Step 2: Update the constant**

In `main.py`, change:
```python
LDR_GPIO_PIN = 25  # change when physical pin is known
```
to the actual BCM pin number.

- [ ] **Step 3: Test the sensor manually**

```bash
python3 -c "
import RPi.GPIO as GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setup(<YOUR_PIN>, GPIO.IN)
import time
for _ in range(20):
    print(GPIO.input(<YOUR_PIN>))
    time.sleep(0.5)
GPIO.cleanup()
"
```

Expected: prints `1` when dark, `0` when light is shining on the sensor (or vice versa — check and update `LDR_HEATER_ON_LEVEL` if reversed).

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "chore: set LDR GPIO pin to <PIN_NUMBER>"
```

---

### Task 12: Full integration smoke test

- [ ] **Step 1: Run all unit tests**

```bash
python -m pytest tests/ -v
```

Expected: all pass

- [ ] **Step 2: Start the app and verify the UI**

```bash
sudo python main.py
```

Open `http://waterheater.hemna.com` in a browser. Verify:
- "Heater Status" card appears at the top
- Grey indicator shows "Heater OFF"
- Auto-timer checkbox is present and reflects the saved setting

- [ ] **Step 3: Simulate heater on (cover the LDR with light)**

Shine a light directly on the sensor. Verify:
- Indicator turns red and pulses
- Label changes to "Heater ON"
- If auto-timer checkbox is checked, verify a 15-minute timer begins

- [ ] **Step 4: Simulate heater off (cover sensor)**

Block the sensor. Verify:
- Indicator returns to grey
- Label changes to "Heater OFF"
- If timer had fired and temp was reduced, verify it restores

- [ ] **Step 5: Deploy to production server**

```bash
git push origin master
# On server:
# git pull && sudo systemctl restart waterheater  (or however the service restarts)
```
