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
from flask import request
from flask_socketio import SocketIO, Namespace
import json
import os

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
# Update LDR_GPIO_PIN to the correct pin once hardware is wired
LDR_GPIO_PIN = 17
LDR_HEATER_ON_LEVEL = 0        # GPIO.LOW — DO goes LOW when light detected
LDR_POLL_INTERVAL = 0.25       # seconds between GPIO reads
LDR_DEBOUNCE_SAMPLES = 3       # consecutive matching reads to confirm state change
LDR_AUTO_TIMER_MINUTES = 15
LDR_REDUCED_TEMP = 97
LDR_PROGRESSIVE_INTERVAL_MINUTES = 1   # drop every N minutes after initial reduction
LDR_PROGRESSIVE_STEP = 1               # degrees to drop each interval
LDR_PROGRESSIVE_MIN_TEMP = 80          # never go below this
LDR_SETTINGS_FILE = "/tmp/ldr_settings.json"

TEMPERATURE_FILE = "/tmp/current_temperature.json"

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
_ldr_auto_timer_enabled = False        # persisted to LDR_SETTINGS_FILE
_ldr_progressive_enabled = False       # persisted to LDR_SETTINGS_FILE
_ldr_saved_temp = None                 # temp to restore when heater turns off
_ldr_timer_cancel_event = None         # threading.Event to cancel 15-min timer
_ldr_timer_lock = threading.Lock()
_ldr_progressive_cancel_event = None   # threading.Event to cancel progressive drops
_ldr_progressive_lock = threading.Lock()

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
    defaults = {"auto_timer_enabled": False, "progressive_enabled": False}
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


def _emit_heater_state():
    """Broadcast current heater on/off state and settings to all clients."""
    sio.emit(
        "heater_state",
        {
            "on": _heater_on,
            "auto_timer_enabled": _ldr_auto_timer_enabled,
            "progressive_enabled": _ldr_progressive_enabled,
        },
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

    Retries GPIO setup until the pin is available — the Werkzeug debug reloader
    briefly runs two processes simultaneously, which can cause a 'GPIO busy' error
    on startup in the short-lived parent process.
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
    while True:
        reading = GPIO.input(LDR_GPIO_PIN)
        buffer.append(reading)
        # Keep buffer from growing indefinitely
        if len(buffer) > LDR_DEBOUNCE_SAMPLES * 2:
            buffer = buffer[-LDR_DEBOUNCE_SAMPLES:]
        _ldr_poll_tick(reading, buffer)
        time.sleep(LDR_POLL_INTERVAL)


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
    """Background thread: wait LDR_AUTO_TIMER_MINUTES, then save temp and reduce to 97°F.
    If progressive mode is enabled, kick off the progressive cooling worker afterward.
    """
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
    # Start progressive cooling if enabled
    if _ldr_progressive_enabled:
        _start_ldr_progressive()


def _start_ldr_progressive():
    """Start progressive cooling: drop LDR_PROGRESSIVE_STEP°F every LDR_PROGRESSIVE_INTERVAL_MINUTES
    until LDR_PROGRESSIVE_MIN_TEMP or heater turns off."""
    global _ldr_progressive_cancel_event
    with _ldr_progressive_lock:
        if _ldr_progressive_cancel_event:
            _ldr_progressive_cancel_event.set()
        _ldr_progressive_cancel_event = threading.Event()
    threading.Thread(target=_ldr_progressive_worker, daemon=True).start()
    print(f"LDR progressive cooling started: -{LDR_PROGRESSIVE_STEP}°F every {LDR_PROGRESSIVE_INTERVAL_MINUTES} min, floor {LDR_PROGRESSIVE_MIN_TEMP}°F")


def _ldr_progressive_worker():
    """Background thread: every LDR_PROGRESSIVE_INTERVAL_MINUTES drop CURRENT_TEMPERATURE
    by LDR_PROGRESSIVE_STEP°F, stopping at LDR_PROGRESSIVE_MIN_TEMP or when cancelled."""
    global _ldr_progressive_cancel_event
    with _ldr_progressive_lock:
        cancel_ev = _ldr_progressive_cancel_event
    if cancel_ev is None:
        return
    interval_seconds = LDR_PROGRESSIVE_INTERVAL_MINUTES * 60
    while True:
        if cancel_ev.wait(timeout=interval_seconds):
            print("LDR progressive cooling cancelled")
            return
        new_temp = max(CURRENT_TEMPERATURE - LDR_PROGRESSIVE_STEP, LDR_PROGRESSIVE_MIN_TEMP)
        if CURRENT_TEMPERATURE <= LDR_PROGRESSIVE_MIN_TEMP:
            print(f"LDR progressive cooling reached floor {LDR_PROGRESSIVE_MIN_TEMP}°F, stopping")
            return
        set_temperature(new_temp)
        print(f"LDR progressive cooling: reduced to {new_temp}°F")


def motor_control(steps, clockwise=True, steptype="Full"):
    """Clockwise to increase temperature."""
    print(f"Move motor {steps} clockwise? {clockwise} type {steptype}")
    # Declare a instance of class pass GPIO pins numbers and the motor type
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(EN_pin, GPIO.OUT)  # set enable pin as output
    GPIO.output(EN_pin, GPIO.LOW)  # pull enable to low to enable motor
    mymotortest = RpiMotorLib.A4988Nema(direction, step, (21, 21, 21), "DRV8825")
    mymotortest.motor_go(
        clockwise,  # True=Clockwise, False=Counter-Clockwise
        steptype,  # Step type (Full,Half,1/4,1/8,1/16,1/32)
        steps,  # number of steps
        # .0005, # step delay [sec]
        0.005,  # step delay [sec]
        True,  # True = print verbose output
        0.05,
    )  # initial delay [sec]
    GPIO.cleanup()  # clear GPIO allocations after run


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
    print(f"Loadded Current temperature: {CURRENT_TEMPERATURE}")


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
    sio.emit(
        "temperature_status",
        {"message": f"Temperature changed to {CURRENT_TEMPERATURE} degrees"},
        namespace=APP_NAMESPACE,
    )
    sio.emit(
        "temperature_update",
        {"temperature": CURRENT_TEMPERATURE},
        namespace=APP_NAMESPACE,
    )


def set_temperature(temperature):
    global CURRENT_TEMPERATURE
    print(f"Setting temperature to {temperature}")
    diff = temperature - CURRENT_TEMPERATURE
    if diff > 0:
        steps = int(diff * DEFAULT_STEPS_PER_DEGREE)
        motor_control(steps, clockwise=False, steptype="Full")
    else:
        steps = int(abs(diff) * DEFAULT_STEPS_PER_DEGREE)
        motor_control(steps, clockwise=True, steptype="Full")
    CURRENT_TEMPERATURE = temperature
    save_temperature()
    sio.emit(
        "temperature_status",
        {"message": f"Temperature changed to {CURRENT_TEMPERATURE} degrees"},
        namespace=APP_NAMESPACE,
    )
    sio.emit(
        "temperature_update",
        {"temperature": CURRENT_TEMPERATURE},
        namespace=APP_NAMESPACE,
    )


def _emit_timer_state():
    """Broadcast current timer state so clients can show accurate countdown."""
    with _timer_lock:
        end = _timer_end_timestamp
    payload = {"end_timestamp": end}
    if end is not None:
        payload["reset_temperature"] = RESET_TEMPERATURE
    sio.emit("timer_state", payload, namespace=APP_NAMESPACE)


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
    sio.emit("start_timer_state", payload, namespace=APP_NAMESPACE)


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
        sio.emit(
            "motor_status", {"message": "Connected to server"}, namespace=APP_NAMESPACE
        )
        _emit_timer_state()
        _emit_start_timer_state()
        _emit_heater_state()

    def on_disconnect(self):
        print("Client disconnected")

    def on_message(self, sid, data):
        print(f"on_message: Received message: {data}")

    def on_move_motor(self, data):
        print(f"on_move_motor: {data}")
        print(f"data.get('steps', 100): {data.get('steps', 100)}")
        print(f"data.get('steptype', 'Full'): {data.get('steptype', 'Full')}")
        print(f"data.get('clockwise', True): {data.get('clockwise', True)}")
        steps = int(data.get("steps", 100))
        steptype = data.get("steptype", "Full")
        clockwise = bool(data.get("clockwise", True))
        print(f"Moving motor {steps} steps, {'CW' if clockwise else 'CCW'}, {steptype}")
        # threading.Thread(target=motor_control, args=(steps, clockwise, steptype)).start()
        motor_control(steps, clockwise=clockwise, steptype=steptype)
        sio.emit(
            "motor_status",
            {
                "message": f"Motor moving {steps} steps, {'CW' if clockwise else 'CCW'}, {steptype}"
            },
        )

    def on_change_temperature(self, data):
        print(f"on_change_temperature: {data}")
        temperature = int(data.get("temperature", 1))
        change_temperature(temperature)
        sio.emit(
            "temperature_status",
            {"message": f"Temperature changed to {temperature} degrees"},
            namespace=APP_NAMESPACE,
        )

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
        sio.emit(
            "temperature_update", {"temperature": temperature}, namespace=APP_NAMESPACE
        )

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
        global _ldr_progressive_enabled, _ldr_progressive_cancel_event
        enabled = bool(data.get("enabled", False))
        _ldr_progressive_enabled = enabled
        _save_ldr_settings({"auto_timer_enabled": _ldr_auto_timer_enabled, "progressive_enabled": enabled})
        # If disabling while progressive cooling is running, cancel it
        if not enabled:
            with _ldr_progressive_lock:
                ev = _ldr_progressive_cancel_event
            if ev:
                ev.set()
        _emit_heater_state()
        print(f"LDR progressive cooling {'enabled' if enabled else 'disabled'}")


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
    settings = _load_ldr_settings()
    _ldr_auto_timer_enabled = settings["auto_timer_enabled"]
    _ldr_progressive_enabled = settings["progressive_enabled"]
    if len(sys.argv) > 1 and sys.argv[1].startswith("--"):
        main()
    else:
        print("init_flask()")
        sio = init_flask()
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
