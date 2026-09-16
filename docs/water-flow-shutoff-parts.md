# Water Flow Meter & Shutoff Valve — Parts & Wiring Guide

Hardware additions to the [waterheater.hemna.com](http://waterheater.hemna.com) Raspberry Pi system,
inline on the ¾" PEX cold water supply line feeding the water heater.

---

## Parts List

| # | Item | Price | Link |
|---|------|-------|------|
| 1 | **GREDIA ¾" Hall Effect Flow Sensor** — G3/4", food-grade, 1–60 L/min, DC 5V, 2-pack | $17.09 | [amazon.com/dp/B07RF49TZH](https://www.amazon.com/dp/B07RF49TZH) |
| 2 | **U.S. Solid ¾" Motorized Ball Valve** — 9–24V AC/DC, 2-wire auto-return, ¾" NPT | $41.52 | [amazon.com/dp/B06XX6XYD8](https://www.amazon.com/dp/B06XX6XYD8) |
| 3 | **JBtek 4-Channel 5V Relay Module** — active LOW, optocoupler isolated, for Raspberry Pi | $5.95 | [amazon.com/dp/B00KTEN3TM](https://www.amazon.com/dp/B00KTEN3TM) |
| 4 | **12V 2A DC Wall Adapter** — 110V→12V, 5.5/2.1mm barrel connector, on/off switch | $8.85 | [amazon.com/dp/B087CS6NHV](https://www.amazon.com/dp/B087CS6NHV) |
| 5 | **Lead-Free Brass ¾" PEX × ¾" NPT Male Adapters** — 4-pack | $11.99 | [amazon.com/dp/B0D7YMLTXF](https://www.amazon.com/dp/B0D7YMLTXF) |
| 6 | **iCrimp Angle PEX Crimper Kit** — ½" & ¾", pipe cutter + go/no-go gauge, ASTM F1807 | $85.49 | [amazon.com/dp/B018VNUCSC](https://www.amazon.com/dp/B018VNUCSC) |
| 7 | **¾" Copper Crimp Rings — 25-pack** | $11.99 | [amazon.com/dp/B0CPPL43ZT](https://www.amazon.com/dp/B0CPPL43ZT) |

**Total: ~$183**

---

## PEX Line Details

Your cold water supply line is **¾" PEX** (measured OD = 0.88", standard OD = 0.875").

Both the flow sensor (G¾" BSP threads) and the ball valve (¾" NPT threads) connect
inline via the brass ¾" PEX barb × ¾" NPT adapters (item 5) and copper crimp rings (item 7).

**Install order on the cold supply line:**

```
[PEX pipe] → [Flow Sensor] → [Ball Valve] → [Water Heater cold inlet]
```

Flow sensor goes upstream of the valve so you can measure flow even when diagnosing
valve behavior.

---

## GPIO Pin Assignments (BCM numbering)

### Existing pins — waterheater app (DO NOT USE)

| BCM Pin | Physical Pin | Function |
|---------|-------------|----------|
| GPIO 17 | Pin 11 | LDR photoresistor input — burner detection |
| GPIO 21 | Pin 40 | DRV8825 MS microstepping (tied, no-op) |
| GPIO 22 | Pin 15 | DRV8825 DIR — stepper motor direction |
| GPIO 23 | Pin 16 | DRV8825 STEP |
| GPIO 24 | Pin 18 | DRV8825 EN — stepper enable (active LOW) |

### New pins — flow meter & valve

| BCM Pin | Physical Pin | Function | Direction |
|---------|-------------|----------|-----------|
| **GPIO 18** | Pin 12 | Flow sensor pulse input | IN |
| **GPIO 25** | Pin 22 | Valve relay control | OUT |

### Remaining free general-purpose pins
`BCM 4, 5, 6, 12, 13, 16, 19, 20, 26, 27`

---

## Wiring Diagrams

### Flow Sensor (GREDIA ¾" Hall Effect) → Raspberry Pi

```
Flow Sensor          Raspberry Pi (40-pin header)
───────────          ────────────────────────────
Red   (VCC)    ───►  Pin 2   (5V)
Black (GND)    ───►  Pin 6   (GND)
Yellow (SIG)   ───►  Pin 12  (GPIO 18, BCM)
                     └─ enable internal pull-up in software
```

> The sensor outputs a pulse train on the yellow wire. Per the GREDIA spec: F(Hz) = 5.5 × Q(L/min),
> so at 1 L/min → 5.5 Hz → 330 pulses/min → **~3.03 mL per pulse**.
> Pulse frequency is directly proportional to flow rate (1–60 L/min range).
> The Pi's internal pull-up resistor on GPIO 18 is sufficient; no external resistor needed.

---

### Ball Valve (U.S. Solid ¾") → Relay Module → Pi + 12V PSU

```
Raspberry Pi         JBtek Relay Module       Ball Valve / PSU
────────────         ──────────────────       ────────────────
Pin 2  (5V)    ───►  VCC
Pin 6  (GND)   ───►  GND
Pin 22 (GPIO25)───►  IN1

                     COM1            ◄───  12V PSU (+) red wire
                     NO1 (norm open) ───►  Ball Valve wire 1 (either)
                     
                                     ◄───  Ball Valve wire 2  ───►  12V PSU (−) black wire
```

**How it works:**
- `GPIO 25 HIGH` → relay closes → 12V reaches valve → **valve OPENS**, water flows
- `GPIO 25 LOW`  → relay opens  → 12V removed  → spring returns valve → **valve CLOSES**

> The valve is **normally closed** (spring-return) — if the Pi crashes, loses power, or
> GPIO goes LOW for any reason, the valve automatically shuts. This is the safe failure mode
> for a water shutoff.

---

### Relay Module IN-pin Logic (JBtek active LOW)

The JBtek relay module triggers on **LOW** (0V), not HIGH. The Pi's `rpi-lgpio` library
defaults are fine — just write the pin LOW to activate.

```python
# Relay IN1 = GPIO 25
# LOW  → relay ON  → valve OPEN
# HIGH → relay OFF → valve CLOSED (spring return)
GPIO.output(VALVE_GPIO_PIN, GPIO.LOW)   # open valve
GPIO.output(VALVE_GPIO_PIN, GPIO.HIGH)  # close valve
```

> Initialize GPIO 25 as OUTPUT HIGH on startup so the valve stays closed until
> explicitly commanded open.

---

### Full System Wiring Overview

```
                    ┌─────────────────────────────────┐
                    │        Raspberry Pi              │
                    │                                  │
  LDR ──────────── │ GPIO17  GPIO18 ─────────────────┐│
  DRV8825 DIR ───── │ GPIO22                           ││
  DRV8825 STEP ──── │ GPIO23  GPIO25 ──────────┐      ││
  DRV8825 EN ─────  │ GPIO24                   │      ││
                    │         5V ──────────┐   │      ││
                    │         GND ─────┐   │   │      ││
                    └──────────────────┼───┼───┼──────┘│
                                       │   │   │       │
                                       │   │   ▼       │
                                       │   │  JBtek     │
                                       │   │  Relay     │
                                       │   │  Module    │
                                       │   └─► GND      │
                                       └────► VCC       │
                                             IN1 ◄──────┘
                                             COM ◄──── 12V PSU (+)
                                             NO  ────► Valve wire 1

  12V PSU (−) ──────────────────────────────────────► Valve wire 2

  5V (Pin 2) ────────────────────────────────────────► Flow Sensor VCC (red)
  GND (Pin 6) ───────────────────────────────────────► Flow Sensor GND (black)
  GPIO18 (Pin 12) ───────────────────────────────────► Flow Sensor SIG (yellow)
```

---

## Physical Installation Notes

1. **Shut off water supply** to the water heater before cutting any PEX.
2. **Cut PEX** using the iCrimp pipe cutter (included with item 6) — clean square cut, no burrs.
3. **Slide crimp ring** onto PEX tube before pushing onto barb fitting.
4. **Push PEX** fully onto the brass barb adapter (item 5) until it bottoms out.
5. **Crimp** with the ¾" jaw. Use the go/no-go gauge to verify each crimp.
6. **Thread** the brass adapters into the flow sensor and ball valve ports (¾" NPT).
   Use PTFE (Teflon) tape on all NPT threads — 2–3 wraps clockwise.
7. **Install flow sensor upstream** (closer to the supply), ball valve downstream
   (closer to the heater inlet).
8. Restore water supply and check for leaks before powering up electronics.

---

## Software Integration Plan

New files to add to the waterheater repo:

| File | Purpose |
|------|---------|
| `flow_meter.py` | Background polling thread, pulse counting, L/min calculation, SocketIO `flow_rate` events |
| `valve.py` | `open_valve()` / `close_valve()` / `get_valve_state()` using RPi.GPIO on BCM 25 |

Changes to existing files:

| File | Change |
|------|--------|
| `main.py` | Import and init `flow_meter` + `valve`; add GPIO 18/25 pin defs; add SocketIO handlers `on_open_valve` / `on_close_valve`; include `flow_lpm` + `valve_open` in `_get_full_state()` |
| `mqtt_bridge.py` | Add `open_valve` / `close_valve` to MQTT `cmd_handlers`; publish `flow_lpm` + `valve_open` in state payload |
| `web/templates/index.html` | Flow rate gauge display + valve open/close toggle button |
| `web/static/main.js` | SocketIO `flow_rate` event handler; valve button state management |
| `pyproject.toml` | No new dependencies — `rpi-lgpio` already handles GPIO 18/25 |
