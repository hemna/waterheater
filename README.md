# waterheater

Water heater control using a NEMA 17 stepper motor (17HS4023) on a Raspberry Pi, with a web UI for temperature control.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Raspberry Pi with GPIO access when using motor control

## Install

With uv:

```bash
uv sync
```

With pip:

```bash
pip install -e .
```

## Run the app

**Web server** (Flask + SocketIO on port 80):

```bash
uv run python main.py
```

Or with pip:

```bash
python main.py
```

Then open http://localhost/ (or your Pi’s IP) in a browser. On Linux, binding to port 80 may require `sudo`.

**CLI motor test** (steps only, no web server):

```bash
uv run python main.py --steps 100 --steptype Full --clockwise
```

Options: `--steps`, `--steptype` (Full, 1/2, 1/4, 1/8, 1/16, 1/32), `--clockwise` / `--no-clockwise`.

## LDR burner detection

The app supports an optional LDR (light-dependent resistor) sensor to detect when the water heater burner fires. When detected, the web UI shows a red indicator light. Optionally, it can automatically reduce the temperature to 97°F after 15 minutes and restore it when the burner turns off.

### Hardware

**Sensor:** LDR photoresistor module with LM393 comparator (e.g. WWZMDiB 5516). Connect the module's **DO** (digital output) pin to a free GPIO pin on the Pi:

| Module pin | Pi pin        |
|------------|---------------|
| VCC        | 3.3V or 5V    |
| GND        | GND           |
| DO         | Any free GPIO |

Aim the sensor at the heater's sight glass or pilot light window. The onboard potentiometer controls the light threshold — turn it until the DO LED lights up only when the burner is on.

### Configuration

In `main.py`, update two constants near the top of the file:

```python
LDR_GPIO_PIN = 17          # BCM pin 17 (DO wire)
LDR_HEATER_ON_LEVEL = 0    # 0 = LOW when burner on; change to 1 if your
                            # module outputs HIGH when light is detected
```

To find the right pin number and verify polarity, run this one-liner on the Pi after wiring:

```bash
python3 -c "
import RPi.GPIO as GPIO, time
GPIO.setmode(GPIO.BCM)
GPIO.setup(17, GPIO.IN)          # BCM pin 17
for _ in range(20):
    print(GPIO.input(17))
    time.sleep(0.5)
GPIO.cleanup()
"
```

Point a light at the sensor — if you see `0` when lit and `1` when dark, `LDR_HEATER_ON_LEVEL = 0` is correct. If reversed, set it to `1`.

### How it works

1. A background thread polls the DO pin every 250 ms.
2. Three consecutive matching readings are required before a state change is confirmed (debounce).
3. When the burner turns **on**:
   - The web UI indicator turns red and pulses.
   - If **Auto-reduce** is enabled, a 15-minute countdown starts.
4. After 15 minutes, the temperature is reduced to 97°F.
5. When the burner turns **off**, the temperature is restored to what it was before the reduction.

The auto-reduce toggle in the web UI is saved to `/tmp/ldr_settings.json` and reloaded on startup.

### Running tests

```bash
python3 -m pytest tests/ -v
```

The tests mock RPi.GPIO and run on any platform (no Pi required).
