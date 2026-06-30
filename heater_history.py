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


def get_chart_data(period: str = "day") -> dict:
    """Return aggregated heating minutes for charting.

    period: 'day' (hourly buckets for today),
            'month' (daily buckets for this month),
            'year' (monthly buckets for this year).
    Returns: {"labels": [...], "values": [...]} where values are minutes.
    """
    import datetime

    now = datetime.datetime.now()
    with _lock:
        completed = [e for e in _history if e["duration"] is not None]

    if period == "day":
        # 24 hourly buckets for today
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        buckets = [0.0] * 24
        labels = [f"{h}:00" for h in range(24)]
        for e in completed:
            ev_start = datetime.datetime.fromtimestamp(e["start"])
            ev_end = datetime.datetime.fromtimestamp(e["end"])
            if ev_end < start_of_day:
                continue
            # Clip to today
            clipped_start = max(ev_start, start_of_day)
            clipped_end = min(ev_end, now)
            if clipped_start >= clipped_end:
                continue
            # Distribute across hour buckets
            cur = clipped_start
            while cur < clipped_end:
                hour_end = cur.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)
                seg_end = min(hour_end, clipped_end)
                minutes = (seg_end - cur).total_seconds() / 60.0
                buckets[cur.hour] += minutes
                cur = seg_end
        return {"labels": labels, "values": [round(v, 1) for v in buckets]}

    elif period == "month":
        # Daily buckets for current month
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        import calendar
        days_in_month = calendar.monthrange(now.year, now.month)[1]
        buckets = [0.0] * days_in_month
        labels = [str(d) for d in range(1, days_in_month + 1)]
        for e in completed:
            ev_start = datetime.datetime.fromtimestamp(e["start"])
            ev_end = datetime.datetime.fromtimestamp(e["end"])
            if ev_end < start_of_month:
                continue
            clipped_start = max(ev_start, start_of_month)
            clipped_end = min(ev_end, now)
            if clipped_start >= clipped_end:
                continue
            cur = clipped_start
            while cur < clipped_end:
                day_end = (cur + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                seg_end = min(day_end, clipped_end)
                minutes = (seg_end - cur).total_seconds() / 60.0
                buckets[cur.day - 1] += minutes
                cur = seg_end
        return {"labels": labels, "values": [round(v, 1) for v in buckets]}

    else:  # year
        # Monthly buckets for current year
        start_of_year = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        buckets = [0.0] * 12
        labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        for e in completed:
            ev_start = datetime.datetime.fromtimestamp(e["start"])
            ev_end = datetime.datetime.fromtimestamp(e["end"])
            if ev_end < start_of_year:
                continue
            clipped_start = max(ev_start, start_of_year)
            clipped_end = min(ev_end, now)
            if clipped_start >= clipped_end:
                continue
            cur = clipped_start
            while cur < clipped_end:
                import calendar as cal
                days_in_m = cal.monthrange(cur.year, cur.month)[1]
                month_end = cur.replace(day=days_in_m, hour=23, minute=59, second=59, microsecond=999999) + datetime.timedelta(microseconds=1)
                seg_end = min(month_end, clipped_end)
                minutes = (seg_end - cur).total_seconds() / 60.0
                buckets[cur.month - 1] += minutes
                cur = seg_end
        return {"labels": labels, "values": [round(v, 1) for v in buckets]}


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
