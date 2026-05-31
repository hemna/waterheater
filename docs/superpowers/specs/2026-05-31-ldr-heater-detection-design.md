# LDR Heater Detection — Design Spec

**Date:** 2026-05-31  
**Status:** Approved  

## Overview

Add a photoresistor (LDR) sensor to detect when the water heater burner is on. Show a large red indicator light in the web UI, and optionally auto-start a 15-minute timer that reduces the temperature to 97°F. When the burner turns off, restore the temperature to what it was before the reduction.

## Hardware

- **Sensor:** WWZMDiB 5MM LDR 5516 Photoresistor + LM393 comparator module (6-pack)
- **Output used:** Digital output (DO pin) — LOW when light detected, HIGH when dark
- **GPIO pin:** Configurable constant `LDR_GPIO_PIN` (exact pin TBD when hardware arrives)
- **Power:** 3.3V or 5V from Raspberry Pi header

## Architecture

```
LDR DO pin ──► GPIO polling thread (250ms, 3-sample debounce)
                       │
              ┌────────┴─────────┐
           heater ON          heater OFF
              │                  │
       emit heater_state     emit heater_state
       if auto-timer:        if temp was reduced:
         save current temp     restore saved temp
         start 15-min timer    clear saved temp
              │                 cancel LDR timer
         (15 min later)
           save current temp
           set temp → 97°F
```

## Backend (`main.py`)

### New constants

```python
LDR_GPIO_PIN = 25           # change when physical pin is known
LDR_HEATER_ON_LEVEL = GPIO.LOW  # DO goes LOW when light detected
LDR_POLL_INTERVAL = 0.25    # seconds between GPIO reads
LDR_DEBOUNCE_SAMPLES = 3    # consecutive matching reads to confirm state change
LDR_AUTO_TIMER_MINUTES = 15
LDR_REDUCED_TEMP = 97
LDR_SETTINGS_FILE = "/tmp/ldr_settings.json"
```

### New state variables

```python
_heater_on = False
_ldr_auto_timer_enabled = False      # persisted to LDR_SETTINGS_FILE
_ldr_saved_temp = None               # temperature to restore on heater-off
_ldr_timer_cancel_event = None       # threading.Event to cancel 15-min timer
_ldr_timer_lock = threading.Lock()
```

### LDR polling thread

Started at app startup (daemon thread). Every `LDR_POLL_INTERVAL` seconds:

1. Read `GPIO.input(LDR_GPIO_PIN)`
2. Append to a rolling buffer of last `LDR_DEBOUNCE_SAMPLES` readings
3. If all samples agree and differ from `_heater_on`:
   - **OFF → ON transition:**
     - Set `_heater_on = True`
     - Emit `heater_state {on: true}` to all clients
     - If `_ldr_auto_timer_enabled`: start `_ldr_timer_worker` thread
   - **ON → OFF transition:**
     - Set `_heater_on = False`
     - Emit `heater_state {on: false}` to all clients
     - Cancel LDR timer if running
     - If `_ldr_saved_temp` is not None: call `set_temperature(_ldr_saved_temp)`, clear `_ldr_saved_temp`

### `_ldr_timer_worker`

Background thread started when heater turns on (auto-timer enabled):

1. Wait `LDR_AUTO_TIMER_MINUTES` × 60 seconds (cancellable via `_ldr_timer_cancel_event`)
2. If timer completes (not cancelled):
   - Save `CURRENT_TEMPERATURE` → `_ldr_saved_temp`
   - Call `set_temperature(LDR_REDUCED_TEMP)` (97°F)
3. If cancelled (heater turned off before timer fired): do nothing

### Persistence

`LDR_SETTINGS_FILE` (`/tmp/ldr_settings.json`) stores:
```json
{"auto_timer_enabled": false}
```
Loaded at startup, written on each `set_ldr_auto_timer` event.

### New Socket.IO events

| Direction | Event | Payload | Description |
|-----------|-------|---------|-------------|
| server → client | `heater_state` | `{on: bool}` | Emitted on state change and on client connect |
| client → server | `set_ldr_auto_timer` | `{enabled: bool}` | Enable/disable auto-timer; persisted to file |

The `on_connect` handler gains a call to `_emit_heater_state()` alongside existing timer state emits.

## Frontend

### Heater status indicator

A new "Heater Status" card at the top of the page (above temperature controls) containing:

- **Large circle indicator** (~80px diameter):
  - OFF state: dark grey (`#374151`)
  - ON state: bright red (`#ef4444`) with a CSS pulse/glow animation
- **Label** beneath: "Heater ON" (red) or "Heater OFF" (grey)

```html
<!-- OFF -->
<div class="indicator indicator-off"></div>
<p>Heater OFF</p>

<!-- ON -->
<div class="indicator indicator-on"></div>  <!-- pulsing red glow -->
<p>Heater ON</p>
```

### Auto-timer toggle

Below the indicator, inside the same card:

```
[ ] Auto-reduce temp to 97°F after 15 min
```

- Checkbox state reflects server-side `_ldr_auto_timer_enabled`
- On `change`: emits `set_ldr_auto_timer {enabled: bool}` via Socket.IO

### `main.js` additions

- Handle `heater_state` event: toggle indicator class and label text
- On page load (connect): server sends current heater state — JS applies it immediately
- Checkbox `change` listener: emit `set_ldr_auto_timer`

## State machine summary

```
IDLE (heater off)
  → LDR detects light → HEATER_ON
      → if auto-timer: start 15-min countdown
          → timer fires → save temp, set 97°F → WAITING_FOR_OFF
          → heater turns off (before timer) → cancel timer → restore none → IDLE
  → heater turns off (no timer/not fired) → IDLE

WAITING_FOR_OFF (heater on, temp reduced to 97°F)
  → LDR detects dark → restore saved temp → IDLE
```

## What is NOT in scope

- Analog AO pin reading (digital DO is sufficient)
- Configuring the 15-minute duration from the UI (hardcoded constant)
- Notification/alerting beyond the UI indicator
