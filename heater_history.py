"""Heater event history — records ON/OFF transitions with timestamps and durations.

Persists to a JSON file. Keeps the last N events to avoid unbounded growth.
"""

import json
import os
import threading
import time

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "heater_history.json")
MAX_EVENTS = 100  # keep last N events

_lock = threading.Lock()
_history: list = []


def _load():
    """Load history from disk."""
    global _history
    if not os.path.exists(HISTORY_FILE):
        _history = []
        return
    try:
        with open(HISTORY_FILE, "r") as f:
            _history = json.load(f)
    except Exception:
        _history = []


def _save():
    """Persist history to disk."""
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(_history[-MAX_EVENTS:], f, indent=2)
    except Exception as e:
        print(f"Failed to save heater history: {e}")


def init():
    """Load history on startup."""
    with _lock:
        _load()
    print(f"Heater history loaded: {len(_history)} events")


def record_on(timestamp: float):
    """Record a heater ON event (start of a heating cycle)."""
    with _lock:
        _history.append({
            "start": timestamp,
            "end": None,
            "duration": None,
        })
        _save()


def record_off(timestamp: float):
    """Record a heater OFF event — closes the most recent open entry."""
    with _lock:
        # Find the last open event (end == None)
        for event in reversed(_history):
            if event["end"] is None:
                event["end"] = timestamp
                event["duration"] = round(timestamp - event["start"], 1)
                break
        _save()


def get_history(limit: int = 20) -> list:
    """Return the most recent events (newest first)."""
    with _lock:
        events = list(reversed(_history[-limit:]))
    return events


def get_stats() -> dict:
    """Return summary statistics."""
    with _lock:
        completed = [e for e in _history if e["duration"] is not None]
    if not completed:
        return {"total_events": 0, "avg_duration": 0, "max_duration": 0, "today_events": 0}

    durations = [e["duration"] for e in completed]
    today_start = time.time() - (time.time() % 86400)  # midnight UTC approx
    today_events = [e for e in completed if e["start"] >= today_start]

    return {
        "total_events": len(completed),
        "avg_duration": round(sum(durations) / len(durations), 1),
        "max_duration": round(max(durations), 1),
        "today_events": len(today_events),
    }
