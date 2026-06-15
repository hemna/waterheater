#######################################
# Copyright (c) 2021 Maker Portal LLC
# Author: Joshua Hrisko
#######################################
#
# NEMA 17 (17HS4023) Raspberry Pi Tests
# --- rotating the NEMA 17 to test
# --- wiring and motor functionality
#
#
#######################################
#
import click
import RPi.GPIO as GPIO
from RpiMotorLib import RpiMotorLib
import time
from flask import Flask, render_template, request, jsonify
import threading
from flask_socketio import SocketIO, Namespace
import json
import os
import mqtt_bridge
import heater_history

################################
# RPi and Motor Pre-allocations
################################
#
# define GPIO pins
DEFAULT_STEPS_PER_DEGREE = 14
DEFAULT_INITIAL_TEMPERATURE = 110
CURRENT_TEMPERATURE = 110
APP_NAMESPACE = "/control"

direction = 22  # Direction (DIR) GPIO Pin
step = 23  # Step GPIO Pin
EN_pin = 24  # enable pin (LOW to enable)

# LDR sensor (photoresistor) GPIO config
# DO pin goes LOW when light detected (heater burner on)
LDR_GPIO_PIN = 17
LDR_HEATER_ON_LEVEL = 0        # GPIO.LOW — DO goes LOW when light detected
LDR_POLL_INTERVAL = 0.25       # seconds between GPIO reads
LDR_DEBOUNCE_SAMPLES = 3       # consecutive matching reads to confirm state change
LDR_AUTO_TIMER_MINUTES = 20
LDR_REDUCED_TEMP = 97
LDR_PROGRESSIVE_INTERVAL_MINUTES = 0.5  # drop every N minutes after initial reduction
LDR_PROGRESSIVE_STEP = 1               # degrees to drop each interval
LDR_PROGRESSIVE_MIN_TEMP_DEFAULT = 80  # default floor, user can change
LDR_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ldr_settings.json")

TEMPERATURE_FILE = "/tmp/current_temperature.json"
HEATER_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "heater_state.json")

RESET_TEMPERATURE = 108  # default temperature to reset to after timer
WEB_PORT = 80

# Timer state: reset to RESET_TEMPERATURE after a delay
_timer_end_timestamp = None  # Unix time when reset will run, or None
_timer_cancel_event = None  # threading.Event to cancel the active timer
_timer_lock = threading.Lock()

# Start timer state: reduce to intermediate temp, then trigger reset timer
_start_timer_end_timestamp = None  # Unix time when start timer expires, or None
_start_timer_cancel_event = None  # threading.Event to cancel the active start timer
_start_timer_lock = threading.Lock()
_start_timer_intermediate_temp = (
    None  # Temperature to reduce to when start timer expires
)
_start_timer_reset_duration = (
    None  # Duration (minutes) for the reset timer after start timer expires
)

# LDR heater detection state
_heater_on = False
_heater_on_since = None                # Unix timestamp when heater turned ON, or None
_ldr_auto_timer_enabled = False        # persisted to LDR_SETTINGS_FILE
_ldr_progressive_enabled = False       # persisted to LDR_SETTINGS_FILE
_ldr_progressive_active = False        # True while progressive cooling is running
_ldr_progressive_min_temp = LDR_PROGRESSIVE_MIN_TEMP_DEFAULT  # user-adjustable floor
_ldr_saved_temp = None                 # temp to restore when heater turns off
_ldr_timer_end_timestamp = None        # Unix time when auto-reduce will fire, or None
_ldr_timer_cancel_event = None         # threading.Event to cancel 15-min timer
_ldr_timer_lock = threading.Lock()
_ldr_progressive_cancel_event = None   # threading.Event to cancel progressive drops
_ldr_progressive_lock = threading.Lock()
_heater_state_lock = threading.Lock()  # protects _heater_on and _heater_on_since

# Off-timer: reset to base temperature after heater has been off for N minutes
HEATER_OFF_RESET_MINUTES = 5
_off_timer_cancel_event = None
_off_timer_end_timestamp = None  # Unix time when off-timer will fire, or None
_off_timer_lock = threading.Lock()

# Motor lock — prevents concurrent motor operations from corrupting step state
_motor_lock = threading.Lock()

# SocketIO instance (set in __main__ or init_flask)
sio = None

###########################
# Actual motor control
###########################
#


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


def _load_ldr_settings(path: str = LDR_SETTINGS_FILE) -> dict:
    """Load LDR settings from JSON file. Returns defaults if missing or corrupt."""
    defaults = {"auto_timer_enabled": False, "progressive_enabled": False, "progressive_min_temp": LDR_PROGRESSIVE_MIN_TEMP_DEFAULT}
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


def _load_heater_state() -> dict:
    """Load persisted heater on_since from disk. Returns defaults if missing."""
    defaults = {"on": False, "on_since": None}
    if not os.path.exists(HEATER_STATE_FILE):
        return defaults
    try:
        with open(HEATER_STATE_FILE, "r") as f:
            return {**defaults, **json.load(f)}
    except Exception:
        return defaults


def _save_heater_state() -> None:
    """Persist heater on/on_since to disk so restarts don't lose duration."""
    try:
        with open(HEATER_STATE_FILE, "w") as f:
            json.dump({"on": _heater_on, "on_since": _heater_on_since}, f)
    except Exception as e:
        print(f"Failed to save heater state: {e}")


def _safe_emit(event, data, namespace=APP_NAMESPACE):
    """Emit a SocketIO event only if sio is initialized."""
    if sio is not None:
        sio.emit(event, data, namespace=namespace)


def _emit_heater_state():
    """Broadcast current heater on/off state, settings, and on_since to all clients."""
    with _heater_state_lock:
        on = _heater_on
        on_since = _heater_on_since
    _safe_emit(
        "heater_state",
        {
            "on": on,
            "on_since": on_since,
            "auto_timer_enabled": _ldr_auto_timer_enabled,
            "progressive_enabled": _ldr_progressive_enabled,
            "progressive_active": _ldr_progressive_active,
            "progressive_min_temp": _ldr_progressive_min_temp,
        },
    )
    mqtt_bridge.publish_state()


def _ldr_poll_tick(reading: int, buffer: list) -> None:
    """
    Process one LDR sample. Updates global heater state and triggers side effects.

    Args:
        reading: Raw GPIO value (0=LOW, 1=HIGH)
        buffer:  Rolling sample buffer (last LDR_DEBOUNCE_SAMPLES readings)
    """
    global _heater_on, _heater_on_since, _ldr_saved_temp
    global _ldr_timer_cancel_event, _ldr_timer_end_timestamp

    confirmed = _check_ldr_debounce(buffer, LDR_HEATER_ON_LEVEL)
    if confirmed is None:
        return  # inconclusive — wait for more samples

    with _heater_state_lock:
        if confirmed == _heater_on:
            return  # no change

        if confirmed is True:
            # OFF → ON transition
            _heater_on = True
            _heater_on_since = time.time()
            heater_history.record_on(_heater_on_since)
        else:
            # ON → OFF transition
            _heater_on = False
            _heater_on_since = None
            heater_history.record_off(time.time())

    _save_heater_state()
    _emit_heater_state()

    if confirmed is True:
        _cancel_off_timer()
        if _ldr_auto_timer_enabled:
            _start_ldr_timer()
    else:
        # Start off-timer: reset to base temp after HEATER_OFF_RESET_MINUTES
        # (only if not already at base temperature)
        if CURRENT_TEMPERATURE != RESET_TEMPERATURE:
            _start_off_timer()
        # Cancel LDR timer if still running
        with _ldr_timer_lock:
            ev = _ldr_timer_cancel_event
            _ldr_timer_end_timestamp = None
        if ev:
            ev.set()
        _emit_ldr_timer_state()
        # Cancel progressive cooling if still running
        with _ldr_progressive_lock:
            pev = _ldr_progressive_cancel_event
        if pev:
            pev.set()
        # Restore temperature if it was reduced
        if _ldr_saved_temp is not None:
            set_temperature(_ldr_saved_temp)
            _ldr_saved_temp = None


def _ldr_polling_thread():
    """Background daemon thread: polls LDR GPIO pin every LDR_POLL_INTERVAL seconds.

    Retries GPIO setup until the pin is available. Wraps the read loop in
    exception handling so transient GPIO errors don't kill the thread permanently.
    """
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    while True:
        try:
            GPIO.setup(LDR_GPIO_PIN, GPIO.IN)
            print(f"LDR polling started on GPIO {LDR_GPIO_PIN}")
            break
        except Exception as e:
            print(f"LDR GPIO setup failed ({e}), retrying in 2s...")
            time.sleep(2)
    buffer = []
    consecutive_errors = 0
    while True:
        try:
            reading = GPIO.input(LDR_GPIO_PIN)
            consecutive_errors = 0  # reset on success
            buffer.append(reading)
            # Keep buffer from growing indefinitely
            if len(buffer) > LDR_DEBOUNCE_SAMPLES * 2:
                buffer = buffer[-LDR_DEBOUNCE_SAMPLES:]
            _ldr_poll_tick(reading, buffer)
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors <= 3 or consecutive_errors % 100 == 0:
                print(f"LDR poll error (#{consecutive_errors}): {e}")
            # If GPIO got de-configured, try to reclaim the pin
            if consecutive_errors == 5:
                print("LDR: attempting GPIO re-setup after repeated errors...")
                try:
                    GPIO.setmode(GPIO.BCM)
                    GPIO.setup(LDR_GPIO_PIN, GPIO.IN)
                    print("LDR: GPIO re-setup successful")
                    buffer = []
                except Exception as re_err:
                    print(f"LDR: GPIO re-setup failed: {re_err}")
        time.sleep(LDR_POLL_INTERVAL)


def _emit_ldr_timer_state():
    """Broadcast LDR auto-reduce timer end timestamp to all clients."""
    _safe_emit("ldr_timer_state", {"end_timestamp": _ldr_timer_end_timestamp})


def _start_ldr_timer():
    """Start the LDR auto-reduce timer. Cancels any existing one."""
    global _ldr_timer_cancel_event, _ldr_timer_end_timestamp
    with _ldr_timer_lock:
        if _ldr_timer_cancel_event:
            _ldr_timer_cancel_event.set()
        _ldr_timer_cancel_event = threading.Event()
        _ldr_timer_end_timestamp = time.time() + LDR_AUTO_TIMER_MINUTES * 60
    _emit_ldr_timer_state()
    threading.Thread(target=_ldr_timer_worker, daemon=True).start()
    print(f"LDR auto-timer started: will reduce to {LDR_REDUCED_TEMP}°F in {LDR_AUTO_TIMER_MINUTES} min")


def _ldr_timer_worker():
    """Background thread: wait LDR_AUTO_TIMER_MINUTES, then save temp and reduce to 97°F.
    If progressive mode is enabled, kick off the progressive cooling worker afterward.
    """
    global _ldr_saved_temp, _ldr_timer_cancel_event, _ldr_timer_end_timestamp
    with _ldr_timer_lock:
        cancel_ev = _ldr_timer_cancel_event
    if cancel_ev is None:
        return
    duration_seconds = LDR_AUTO_TIMER_MINUTES * 60
    if cancel_ev.wait(timeout=duration_seconds):
        # Cancelled before timer fired
        with _ldr_timer_lock:
            _ldr_timer_end_timestamp = None
        _emit_ldr_timer_state()
        print("LDR auto-timer cancelled")
        return
    # Timer fired — save current temp and reduce
    with _ldr_timer_lock:
        _ldr_timer_end_timestamp = None
    _emit_ldr_timer_state()
    _ldr_saved_temp = CURRENT_TEMPERATURE
    set_temperature(LDR_REDUCED_TEMP)
    print(f"LDR auto-timer fired: saved {_ldr_saved_temp}°F, reduced to {LDR_REDUCED_TEMP}°F")
    # Start progressive cooling if enabled
    if _ldr_progressive_enabled:
        _start_ldr_progressive()


def _start_ldr_progressive():
    """Start progressive cooling: drop LDR_PROGRESSIVE_STEP°F every LDR_PROGRESSIVE_INTERVAL_MINUTES
    until _ldr_progressive_min_temp or heater turns off."""
    global _ldr_progressive_cancel_event, _ldr_progressive_active
    with _ldr_progressive_lock:
        if _ldr_progressive_cancel_event:
            _ldr_progressive_cancel_event.set()
        _ldr_progressive_cancel_event = threading.Event()
    _ldr_progressive_active = True
    _emit_heater_state()
    threading.Thread(target=_ldr_progressive_worker, daemon=True).start()
    print(f"LDR progressive cooling started: -{LDR_PROGRESSIVE_STEP}°F every {LDR_PROGRESSIVE_INTERVAL_MINUTES * 60:.0f}s, floor {_ldr_progressive_min_temp}°F")


def _ldr_progressive_worker():
    """Background thread: every LDR_PROGRESSIVE_INTERVAL_MINUTES drop CURRENT_TEMPERATURE
    by LDR_PROGRESSIVE_STEP°F, stopping at _ldr_progressive_min_temp or when cancelled."""
    global _ldr_progressive_cancel_event, _ldr_progressive_active
    with _ldr_progressive_lock:
        cancel_ev = _ldr_progressive_cancel_event
    if cancel_ev is None:
        _ldr_progressive_active = False
        _emit_heater_state()
        return
    interval_seconds = LDR_PROGRESSIVE_INTERVAL_MINUTES * 60
    while True:
        if cancel_ev.wait(timeout=interval_seconds):
            print("LDR progressive cooling cancelled")
            _ldr_progressive_active = False
            _emit_heater_state()
            return
        new_temp = max(CURRENT_TEMPERATURE - LDR_PROGRESSIVE_STEP, _ldr_progressive_min_temp)
        if CURRENT_TEMPERATURE <= _ldr_progressive_min_temp:
            print(f"LDR progressive cooling reached floor {_ldr_progressive_min_temp}°F, stopping")
            _ldr_progressive_active = False
            _emit_heater_state()
            return
        set_temperature(new_temp)
        print(f"LDR progressive cooling: reduced to {new_temp}°F")


def _emit_off_timer_state():
    """Broadcast off-timer end timestamp to all clients."""
    _safe_emit("off_timer_state", {"end_timestamp": _off_timer_end_timestamp})


def _start_off_timer():
    """Start the off-timer: reset to RESET_TEMPERATURE after HEATER_OFF_RESET_MINUTES."""
    global _off_timer_cancel_event, _off_timer_end_timestamp
    with _off_timer_lock:
        if _off_timer_cancel_event:
            _off_timer_cancel_event.set()
        _off_timer_cancel_event = threading.Event()
        _off_timer_end_timestamp = time.time() + HEATER_OFF_RESET_MINUTES * 60
    _emit_off_timer_state()
    threading.Thread(target=_off_timer_worker, daemon=True).start()
    print(f"Off-timer started: will reset to {RESET_TEMPERATURE}°F in {HEATER_OFF_RESET_MINUTES} min if heater stays off")


def _cancel_off_timer():
    """Cancel the off-timer (heater turned back on)."""
    global _off_timer_cancel_event, _off_timer_end_timestamp
    with _off_timer_lock:
        ev = _off_timer_cancel_event
        _off_timer_cancel_event = None
        _off_timer_end_timestamp = None
    if ev:
        ev.set()
        print("Off-timer cancelled (heater turned on)")
    _emit_off_timer_state()


def _off_timer_worker():
    """Background thread: wait HEATER_OFF_RESET_MINUTES, then reset to base temp."""
    global _off_timer_end_timestamp
    with _off_timer_lock:
        cancel_ev = _off_timer_cancel_event
    if cancel_ev is None:
        return
    duration_seconds = HEATER_OFF_RESET_MINUTES * 60
    if cancel_ev.wait(timeout=duration_seconds):
        # Cancelled — heater turned back on
        return
    # Timer expired — heater has been off for the full duration, reset to base
    with _off_timer_lock:
        _off_timer_end_timestamp = None
    if not _heater_on:
        set_temperature(RESET_TEMPERATURE)
        print(f"Off-timer fired: heater off for {HEATER_OFF_RESET_MINUTES} min, reset to {RESET_TEMPERATURE}°F")
    _emit_off_timer_state()


def motor_control(steps, clockwise=True, steptype="Full"):
    """Clockwise to increase temperature. Thread-safe via _motor_lock."""
    print(f"Move motor {steps} clockwise? {clockwise} type {steptype}")
    with _motor_lock:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(EN_pin, GPIO.OUT)  # set enable pin as output
        GPIO.output(EN_pin, GPIO.LOW)  # pull enable to low to enable motor
        mymotortest = RpiMotorLib.A4988Nema(direction, step, (21, 21, 21), "DRV8825")
        mymotortest.motor_go(
            clockwise,  # True=Clockwise, False=Counter-Clockwise
            steptype,  # Step type (Full,Half,1/4,1/8,1/16,1/32)
            steps,  # number of steps
            0.005,  # step delay [sec]
            True,  # True = print verbose output
            0.05,  # initial delay [sec]
        )
        # Only clean up motor pins — leave LDR pin (GPIO 17) intact for polling thread
        GPIO.cleanup([direction, step, EN_pin])


def load_temperature():
    global CURRENT_TEMPERATURE
    if os.path.exists(TEMPERATURE_FILE):
        try:
            with open(TEMPERATURE_FILE, "r") as f:
                data = json.load(f)
                CURRENT_TEMPERATURE = data.get(
                    "current_temperature", CURRENT_TEMPERATURE
                )
        except Exception as e:
            CURRENT_TEMPERATURE = DEFAULT_INITIAL_TEMPERATURE
            print(f"Error loading temperature: {e}.")
            print(f"Using default temperature: {CURRENT_TEMPERATURE}")
    else:
        CURRENT_TEMPERATURE = DEFAULT_INITIAL_TEMPERATURE
        print(f"No temperature file found, using default: {CURRENT_TEMPERATURE}")
    print(f"Loaded current temperature: {CURRENT_TEMPERATURE}")


def save_temperature():
    global CURRENT_TEMPERATURE
    print(f"Saving Current temperature: {CURRENT_TEMPERATURE} to {TEMPERATURE_FILE}")
    try:
        with open(TEMPERATURE_FILE, "w") as f:
            json.dump({"current_temperature": CURRENT_TEMPERATURE}, f)
    except Exception as e:
        print(f"Error saving temperature: {e}")
    print(f"Saved Current temperature: {CURRENT_TEMPERATURE} to {TEMPERATURE_FILE}")


def change_temperature(degrees):
    global CURRENT_TEMPERATURE
    print(f"Changing temperature by {degrees} degrees")
    if degrees > 0:
        steps = int(degrees * DEFAULT_STEPS_PER_DEGREE)
        motor_control(steps, clockwise=False, steptype="Full")
        CURRENT_TEMPERATURE += degrees
    else:
        steps = int(degrees * DEFAULT_STEPS_PER_DEGREE)
        motor_control(abs(steps), clockwise=True, steptype="Full")
        CURRENT_TEMPERATURE += degrees
    save_temperature()
    _safe_emit(
        "temperature_status",
        {"message": f"Temperature changed to {CURRENT_TEMPERATURE} degrees"},
    )
    _safe_emit("temperature_update", {"temperature": CURRENT_TEMPERATURE})
    mqtt_bridge.publish_state()


def set_temperature(temperature):
    global CURRENT_TEMPERATURE
    print(f"Setting temperature to {temperature}")
    diff = temperature - CURRENT_TEMPERATURE
    if diff > 0:
        steps = int(diff * DEFAULT_STEPS_PER_DEGREE)
        motor_control(steps, clockwise=False, steptype="Full")
    elif diff < 0:
        steps = int(abs(diff) * DEFAULT_STEPS_PER_DEGREE)
        motor_control(steps, clockwise=True, steptype="Full")
    CURRENT_TEMPERATURE = temperature
    save_temperature()
    _safe_emit(
        "temperature_status",
        {"message": f"Temperature changed to {CURRENT_TEMPERATURE} degrees"},
    )
    _safe_emit("temperature_update", {"temperature": CURRENT_TEMPERATURE})
    mqtt_bridge.publish_state()


def _emit_timer_state():
    """Broadcast current timer state so clients can show accurate countdown."""
    with _timer_lock:
        end = _timer_end_timestamp
    payload = {"end_timestamp": end}
    if end is not None:
        payload["reset_temperature"] = RESET_TEMPERATURE
    _safe_emit("timer_state", payload)
    mqtt_bridge.publish_state()


def _emit_start_timer_state():
    """Broadcast current start timer state so clients can show accurate countdown."""
    with _start_timer_lock:
        end = _start_timer_end_timestamp
        intermediate_temp = _start_timer_intermediate_temp
        reset_duration = _start_timer_reset_duration
    payload = {"end_timestamp": end}
    if end is not None:
        payload["intermediate_temperature"] = intermediate_temp
        payload["reset_duration"] = reset_duration
    _safe_emit("start_timer_state", payload)


def _start_timer_worker():
    """Background thread: wait until end time (or cancel), then reduce to intermediate temp and start reset timer."""
    global _start_timer_end_timestamp, _timer_end_timestamp, _timer_cancel_event
    while True:
        with _start_timer_lock:
            end = _start_timer_end_timestamp
            cancel_ev = _start_timer_cancel_event
            intermediate_temp = _start_timer_intermediate_temp
            reset_duration = _start_timer_reset_duration
        if end is None or cancel_ev is None:
            return
        if cancel_ev.wait(timeout=1.0):
            with _start_timer_lock:
                _start_timer_end_timestamp = None
            _emit_start_timer_state()
            return
        if time.time() >= end:
            with _start_timer_lock:
                _start_timer_end_timestamp = None
            # Reduce to intermediate temperature
            set_temperature(intermediate_temp)
            _emit_start_timer_state()
            # Now start the reset timer
            duration_seconds = max(1, reset_duration * 60)
            with _timer_lock:
                if _timer_cancel_event:
                    _timer_cancel_event.set()
                _timer_cancel_event = threading.Event()
                _timer_end_timestamp = time.time() + duration_seconds
            threading.Thread(target=_timer_worker, daemon=True).start()
            _emit_timer_state()
            print(
                f"Start timer expired: set to {intermediate_temp}°F, reset timer started for {reset_duration} min"
            )
            return


def _timer_worker():
    """Background thread: wait until end time (or cancel), then set temperature to RESET_TEMPERATURE."""
    global _timer_end_timestamp
    while True:
        with _timer_lock:
            end = _timer_end_timestamp
            cancel_ev = _timer_cancel_event
        if end is None or cancel_ev is None:
            return
        if cancel_ev.wait(timeout=1.0):
            with _timer_lock:
                _timer_end_timestamp = None
            _emit_timer_state()
            return
        if time.time() >= end:
            with _timer_lock:
                _timer_end_timestamp = None
            set_temperature(RESET_TEMPERATURE)
            _emit_timer_state()
            return


# --- Flask Web UI with SocketIO ---

def _get_full_state() -> dict:
    """Return complete waterheater state for MQTT publication."""
    with _heater_state_lock:
        on = _heater_on
        on_since = _heater_on_since
    with _timer_lock:
        timer_end = _timer_end_timestamp
    with _start_timer_lock:
        start_timer_end = _start_timer_end_timestamp
        intermediate_temp = _start_timer_intermediate_temp
        reset_duration = _start_timer_reset_duration
    return {
        "temperature": CURRENT_TEMPERATURE,
        "heater_on": on,
        "heater_on_since": on_since,
        "auto_timer_enabled": _ldr_auto_timer_enabled,
        "progressive_enabled": _ldr_progressive_enabled,
        "progressive_active": _ldr_progressive_active,
        "progressive_min_temp": _ldr_progressive_min_temp,
        "timer_end_timestamp": timer_end,
        "reset_temperature": RESET_TEMPERATURE,
        "start_timer_end_timestamp": start_timer_end,
        "start_timer_intermediate_temp": intermediate_temp,
        "start_timer_reset_duration": reset_duration,
        "ldr_timer_end_timestamp": _ldr_timer_end_timestamp,
        "history_stats": heater_history.get_stats(),
    }


flask_app = Flask(
    __name__,
    static_url_path="/static",
    static_folder="web/static",
    template_folder="web/templates",
)


def init_flask():
    global flask_app
    sio = SocketIO(
        flask_app, debug=True, logger=True, engineio_logger=True, async_mode="threading"
    )

    sio.on_namespace(ControlNamespace(APP_NAMESPACE))
    return sio


class ControlNamespace(Namespace):
    def on_connect(self):
        global sio
        print("Client connected")
        _safe_emit("motor_status", {"message": "Connected to server"})
        _emit_timer_state()
        _emit_start_timer_state()
        _emit_heater_state()
        _emit_ldr_timer_state()
        _emit_off_timer_state()
        _safe_emit("heater_history", {
            "events": heater_history.get_history(20),
            "stats": heater_history.get_stats(),
        })

    def on_disconnect(self):
        print("Client disconnected")

    def on_get_history(self, data):
        """Client requests heater history."""
        limit = int(data.get("limit", 20)) if data else 20
        _safe_emit("heater_history", {
            "events": heater_history.get_history(limit),
            "stats": heater_history.get_stats(),
        })

    def on_message(self, sid, data):
        print(f"on_message: Received message: {data}")

    def on_move_motor(self, data):
        print(f"on_move_motor: {data}")
        steps = int(data.get("steps", 100))
        steptype = data.get("steptype", "Full")
        clockwise = bool(data.get("clockwise", True))
        print(f"Moving motor {steps} steps, {'CW' if clockwise else 'CCW'}, {steptype}")
        motor_control(steps, clockwise=clockwise, steptype=steptype)
        _safe_emit(
            "motor_status",
            {"message": f"Motor moving {steps} steps, {'CW' if clockwise else 'CCW'}, {steptype}"},
        )

    def on_change_temperature(self, data):
        print(f"on_change_temperature: {data}")
        temperature = int(data.get("temperature", 1))
        change_temperature(temperature)

    def on_set_temperature_reading(self, data):
        """Set the current temperature reading from the heater.

        This is used to set the current temperature reading from the heater.
        This is a manual override, since there is no way to read the temperature
        from the heater.
        """
        global CURRENT_TEMPERATURE
        print(f"on_set_temperature_reading: {data}")
        temperature = int(data.get("temperature", 1))
        CURRENT_TEMPERATURE = temperature
        save_temperature()
        print(f"Setting temperature to {CURRENT_TEMPERATURE}")
        _safe_emit("temperature_update", {"temperature": temperature})

    def on_set_temperature(self, data):
        """User wants to set the temperature setting to this exact value."""
        global CURRENT_TEMPERATURE
        print(f"on_set_temperature: {data}")
        temperature = int(data.get("temperature", 1))
        set_temperature(temperature)
        print(f"Setting temperature to {CURRENT_TEMPERATURE}")

    def on_set_timer(self, data):
        """Start a timer to reset temperature to RESET_TEMPERATURE after duration_minutes."""
        global _timer_end_timestamp, _timer_cancel_event
        duration_minutes = float(data.get("duration_minutes", 30))
        duration_seconds = max(1, duration_minutes * 60)
        with _timer_lock:
            if _timer_cancel_event:
                _timer_cancel_event.set()
            _timer_cancel_event = threading.Event()
            _timer_end_timestamp = time.time() + duration_seconds
        threading.Thread(target=_timer_worker, daemon=True).start()
        _emit_timer_state()
        print(f"Timer set: reset to {RESET_TEMPERATURE}°F in {duration_minutes} min")

    def on_force_reset(self, data):
        """Reset temperature to RESET_TEMPERATURE now and cancel the timer."""
        global _timer_end_timestamp, _timer_cancel_event
        with _timer_lock:
            ev = _timer_cancel_event
            _timer_end_timestamp = None
            _timer_cancel_event = None
        if ev:
            ev.set()
        set_temperature(RESET_TEMPERATURE)
        _emit_timer_state()
        print("Force reset: temperature set to 108°F, timer cancelled")

    def on_set_start_timer(self, data):
        """Start a start timer: after duration_minutes, reduce to intermediate_temperature, then start reset timer."""
        global _start_timer_end_timestamp, _start_timer_cancel_event
        global _start_timer_intermediate_temp, _start_timer_reset_duration
        duration_minutes = float(data.get("duration_minutes", 15))
        intermediate_temp = int(data.get("intermediate_temperature", 106))
        reset_duration = float(data.get("reset_duration_minutes", 30))
        duration_seconds = max(1, duration_minutes * 60)
        with _start_timer_lock:
            if _start_timer_cancel_event:
                _start_timer_cancel_event.set()
            _start_timer_cancel_event = threading.Event()
            _start_timer_end_timestamp = time.time() + duration_seconds
            _start_timer_intermediate_temp = intermediate_temp
            _start_timer_reset_duration = reset_duration
        threading.Thread(target=_start_timer_worker, daemon=True).start()
        _emit_start_timer_state()
        print(
            f"Start timer set: {duration_minutes} min -> {intermediate_temp}°F -> {reset_duration} min reset timer"
        )

    def on_cancel_start_timer(self, data):
        """Cancel the start timer without affecting the reset timer."""
        global _start_timer_end_timestamp, _start_timer_cancel_event
        with _start_timer_lock:
            ev = _start_timer_cancel_event
            _start_timer_end_timestamp = None
            _start_timer_cancel_event = None
        if ev:
            ev.set()
        _emit_start_timer_state()
        print("Start timer cancelled")

    def on_set_ldr_auto_timer(self, data):
        """Enable or disable the LDR auto-timer. Persists to file."""
        global _ldr_auto_timer_enabled, _ldr_timer_cancel_event
        enabled = bool(data.get("enabled", False))
        _ldr_auto_timer_enabled = enabled
        _save_ldr_settings({"auto_timer_enabled": enabled, "progressive_enabled": _ldr_progressive_enabled})
        # If disabling while a timer is running, cancel it
        if not enabled:
            with _ldr_timer_lock:
                ev = _ldr_timer_cancel_event
            if ev:
                ev.set()
        _emit_heater_state()
        print(f"LDR auto-timer {'enabled' if enabled else 'disabled'}")

    def on_set_ldr_progressive(self, data):
        """Enable or disable progressive cooling. Persists to file."""
        global _ldr_progressive_enabled, _ldr_progressive_cancel_event, _ldr_progressive_active
        enabled = bool(data.get("enabled", False))
        _ldr_progressive_enabled = enabled
        _save_ldr_settings({"auto_timer_enabled": _ldr_auto_timer_enabled, "progressive_enabled": enabled})
        # If disabling while progressive cooling is running, cancel it
        if not enabled:
            with _ldr_progressive_lock:
                ev = _ldr_progressive_cancel_event
            if ev:
                ev.set()
            _ldr_progressive_active = False
        _emit_heater_state()
        print(f"LDR progressive cooling {'enabled' if enabled else 'disabled'}")

    def on_set_progressive_floor(self, data):
        """Set the progressive cooling floor temperature. Persists to file."""
        global _ldr_progressive_min_temp
        temp = int(data.get("temperature", LDR_PROGRESSIVE_MIN_TEMP_DEFAULT))
        temp = max(60, min(temp, 100))  # clamp to sane range
        _ldr_progressive_min_temp = temp
        _save_ldr_settings({
            "auto_timer_enabled": _ldr_auto_timer_enabled,
            "progressive_enabled": _ldr_progressive_enabled,
            "progressive_min_temp": temp,
        })
        _emit_heater_state()
        print(f"Progressive floor set to {temp}°F")

    def on_start_progressive_now(self, data):
        """Immediately reduce to LDR_REDUCED_TEMP and start progressive cooling."""
        global _ldr_saved_temp, _ldr_timer_cancel_event, _ldr_timer_end_timestamp
        # Cancel any running LDR auto-timer since we're doing it manually
        with _ldr_timer_lock:
            ev = _ldr_timer_cancel_event
            _ldr_timer_end_timestamp = None
        if ev:
            ev.set()
        _emit_ldr_timer_state()
        # Save current temp and reduce
        _ldr_saved_temp = CURRENT_TEMPERATURE
        set_temperature(LDR_REDUCED_TEMP)
        print(f"Progressive now: saved {_ldr_saved_temp}°F, reduced to {LDR_REDUCED_TEMP}°F")
        # Start progressive cooling
        _start_ldr_progressive()
        _emit_heater_state()

    def on_stop_progressive_now(self, data):
        """Stop progressive cooling immediately."""
        global _ldr_progressive_cancel_event, _ldr_progressive_active
        with _ldr_progressive_lock:
            ev = _ldr_progressive_cancel_event
        if ev:
            ev.set()
        _ldr_progressive_active = False
        _emit_heater_state()
        print("Progressive cooling stopped manually")


@flask_app.route("/")
def index():
    global CURRENT_TEMPERATURE
    print(f"Index page requested, current temperature: {CURRENT_TEMPERATURE}")
    return render_template("index.html", initial_temperature=CURRENT_TEMPERATURE)


@click.command()
@click.option("--steps", default=100, help="Number of steps.")
@click.option(
    "--steptype",
    type=click.Choice(["Full", "1/2", "1/4", "1/8", "1/16", "1/32"]),
    default="Full",
    help="Step Type",
)
@click.option("--clockwise", type=click.BOOL, default=True, help="Rotate clockwise?.")
def main(steps, steptype, clockwise):
    print("Hello from waterheater!")
    motor_control(steps, clockwise=clockwise, steptype=steptype)


if __name__ == "__main__":
    import sys

    load_temperature()
    heater_history.init()
    settings = _load_ldr_settings()
    _ldr_auto_timer_enabled = settings["auto_timer_enabled"]
    _ldr_progressive_enabled = settings["progressive_enabled"]
    _ldr_progressive_min_temp = settings.get("progressive_min_temp", LDR_PROGRESSIVE_MIN_TEMP_DEFAULT)
    # Restore heater on_since from disk so restarts don't reset the duration
    _persisted = _load_heater_state()
    if _persisted["on"] and _persisted["on_since"] is not None:
        _heater_on = _persisted["on"]
        _heater_on_since = _persisted["on_since"]
        print(f"Restored heater state: ON since {_heater_on_since}")
    else:
        print("No persisted heater state (or heater was off)")
    if len(sys.argv) > 1 and sys.argv[1].startswith("--"):
        main()
    else:
        print("init_flask()")
        sio = init_flask()

        # Initialize MQTT bridge with command handlers
        def _mqtt_set_temperature(data):
            temperature = int(data.get("temperature", CURRENT_TEMPERATURE))
            set_temperature(temperature)

        def _mqtt_change_temperature(data):
            degrees = int(data.get("degrees", 0))
            if degrees != 0:
                change_temperature(degrees)

        def _mqtt_set_temperature_reading(data):
            global CURRENT_TEMPERATURE
            temperature = int(data.get("temperature", CURRENT_TEMPERATURE))
            CURRENT_TEMPERATURE = temperature
            save_temperature()
            _safe_emit("temperature_update", {"temperature": temperature})
            mqtt_bridge.publish_state()

        def _mqtt_set_timer(data):
            global _timer_end_timestamp, _timer_cancel_event
            duration_minutes = float(data.get("duration_minutes", 30))
            duration_seconds = max(1, duration_minutes * 60)
            with _timer_lock:
                if _timer_cancel_event:
                    _timer_cancel_event.set()
                _timer_cancel_event = threading.Event()
                _timer_end_timestamp = time.time() + duration_seconds
            threading.Thread(target=_timer_worker, daemon=True).start()
            _emit_timer_state()
            print(f"MQTT: Timer set: reset to {RESET_TEMPERATURE}°F in {duration_minutes} min")

        def _mqtt_force_reset(data):
            global _timer_end_timestamp, _timer_cancel_event
            with _timer_lock:
                ev = _timer_cancel_event
                _timer_end_timestamp = None
                _timer_cancel_event = None
            if ev:
                ev.set()
            set_temperature(RESET_TEMPERATURE)
            _emit_timer_state()

        def _mqtt_start_progressive(data):
            global _ldr_saved_temp, _ldr_timer_cancel_event, _ldr_timer_end_timestamp
            with _ldr_timer_lock:
                ev = _ldr_timer_cancel_event
                _ldr_timer_end_timestamp = None
            if ev:
                ev.set()
            _emit_ldr_timer_state()
            _ldr_saved_temp = CURRENT_TEMPERATURE
            set_temperature(LDR_REDUCED_TEMP)
            _start_ldr_progressive()
            _emit_heater_state()

        def _mqtt_stop_progressive(data):
            global _ldr_progressive_cancel_event, _ldr_progressive_active
            with _ldr_progressive_lock:
                ev = _ldr_progressive_cancel_event
            if ev:
                ev.set()
            _ldr_progressive_active = False
            _emit_heater_state()

        def _mqtt_set_ldr_auto_timer(data):
            global _ldr_auto_timer_enabled, _ldr_timer_cancel_event
            enabled = bool(data.get("enabled", False))
            _ldr_auto_timer_enabled = enabled
            _save_ldr_settings({"auto_timer_enabled": enabled, "progressive_enabled": _ldr_progressive_enabled})
            if not enabled:
                with _ldr_timer_lock:
                    ev = _ldr_timer_cancel_event
                if ev:
                    ev.set()
            _emit_heater_state()

        def _mqtt_set_ldr_progressive(data):
            global _ldr_progressive_enabled, _ldr_progressive_cancel_event, _ldr_progressive_active
            enabled = bool(data.get("enabled", False))
            _ldr_progressive_enabled = enabled
            _save_ldr_settings({"auto_timer_enabled": _ldr_auto_timer_enabled, "progressive_enabled": enabled})
            if not enabled:
                with _ldr_progressive_lock:
                    ev = _ldr_progressive_cancel_event
                if ev:
                    ev.set()
                _ldr_progressive_active = False
            _emit_heater_state()

        def _mqtt_set_start_timer(data):
            global _start_timer_end_timestamp, _start_timer_cancel_event
            global _start_timer_intermediate_temp, _start_timer_reset_duration
            duration_minutes = float(data.get("duration_minutes", 15))
            intermediate_temp = int(data.get("intermediate_temperature", 106))
            reset_duration = float(data.get("reset_duration_minutes", 30))
            duration_seconds = max(1, duration_minutes * 60)
            with _start_timer_lock:
                if _start_timer_cancel_event:
                    _start_timer_cancel_event.set()
                _start_timer_cancel_event = threading.Event()
                _start_timer_end_timestamp = time.time() + duration_seconds
                _start_timer_intermediate_temp = intermediate_temp
                _start_timer_reset_duration = reset_duration
            threading.Thread(target=_start_timer_worker, daemon=True).start()
            _emit_start_timer_state()

        def _mqtt_cancel_start_timer(data):
            global _start_timer_end_timestamp, _start_timer_cancel_event
            with _start_timer_lock:
                ev = _start_timer_cancel_event
                _start_timer_end_timestamp = None
                _start_timer_cancel_event = None
            if ev:
                ev.set()
            _emit_start_timer_state()

        mqtt_bridge.init(
            get_state_fn=_get_full_state,
            cmd_handlers={
                "set_temperature": _mqtt_set_temperature,
                "change_temperature": _mqtt_change_temperature,
                "set_temperature_reading": _mqtt_set_temperature_reading,
                "set_timer": _mqtt_set_timer,
                "force_reset": _mqtt_force_reset,
                "start_progressive": _mqtt_start_progressive,
                "stop_progressive": _mqtt_stop_progressive,
                "set_ldr_auto_timer": _mqtt_set_ldr_auto_timer,
                "set_ldr_progressive": _mqtt_set_ldr_progressive,
                "set_progressive_floor": lambda data: _mqtt_set_progressive_floor(data),
                "set_start_timer": _mqtt_set_start_timer,
                "cancel_start_timer": _mqtt_cancel_start_timer,
            },
        )

        def _mqtt_set_progressive_floor(data):
            global _ldr_progressive_min_temp
            temp = int(data.get("temperature", LDR_PROGRESSIVE_MIN_TEMP_DEFAULT))
            temp = max(60, min(temp, 100))
            _ldr_progressive_min_temp = temp
            _save_ldr_settings({
                "auto_timer_enabled": _ldr_auto_timer_enabled,
                "progressive_enabled": _ldr_progressive_enabled,
                "progressive_min_temp": temp,
            })
            _emit_heater_state()

        threading.Thread(target=_ldr_polling_thread, daemon=True).start()
        print("LDR polling thread started")
        print(f"Starting web server with SocketIO on http://0.0.0.0:{WEB_PORT} ...")
        sio.run(
            flask_app,
            debug=True,
            use_reloader=False,  # one process only — avoids two-process GPIO conflict
            host="0.0.0.0",
            port=WEB_PORT,
            allow_unsafe_werkzeug=True,
        )
        print("sio.run() returned")
