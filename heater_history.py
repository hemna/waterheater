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


def get_chart_data(period: str = "day", offset: int = 0) -> dict:
    """Return aggregated heating minutes for charting.

    period: 'day' (hourly buckets), 'week' (daily buckets for 7 days),
            'month' (daily buckets), 'year' (monthly buckets).
    offset: 0 = current period, -1 = previous, -2 = two periods back, etc.
    Returns: {"labels": [...], "values": [...], "title": "..."} where values are minutes.
    """
    import datetime
    import calendar

    now = datetime.datetime.now()
    with _lock:
        completed = [e for e in _history if e["duration"] is not None]

    if period == "day":
        # Shift by offset days
        target = now + datetime.timedelta(days=offset)
        start_of_day = target.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + datetime.timedelta(days=1)
        # Clip end to now if viewing today
        if end_of_day > now:
            end_of_day = now
        buckets = [0.0] * 24
        labels = [f"{h}:00" for h in range(24)]
        title = target.strftime("%b %d, %Y")
        for e in completed:
            ev_start = datetime.datetime.fromtimestamp(e["start"])
            ev_end = datetime.datetime.fromtimestamp(e["end"])
            if ev_end <= start_of_day or ev_start >= end_of_day:
                continue
            clipped_start = max(ev_start, start_of_day)
            clipped_end = min(ev_end, end_of_day)
            if clipped_start >= clipped_end:
                continue
            cur = clipped_start
            while cur < clipped_end:
                hour_end = cur.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)
                seg_end = min(hour_end, clipped_end)
                minutes = (seg_end - cur).total_seconds() / 60.0
                buckets[cur.hour] += minutes
                cur = seg_end
        return {"labels": labels, "values": [round(v, 1) for v in buckets], "title": title}

    elif period == "week":
        # Week = 7-day window. offset 0 = current week (Mon-Sun), -1 = last week, etc.
        # Find Monday of current week
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        monday = today - datetime.timedelta(days=today.weekday())
        # Shift by offset weeks
        start_of_week = monday + datetime.timedelta(weeks=offset)
        end_of_week = start_of_week + datetime.timedelta(days=7)
        if end_of_week > now:
            end_of_week = now
        buckets = [0.0] * 7
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        labels = []
        for i in range(7):
            d = start_of_week + datetime.timedelta(days=i)
            labels.append(f"{day_names[i]} {d.day}")
        title = f"{start_of_week.strftime('%b %d')} – {(start_of_week + datetime.timedelta(days=6)).strftime('%b %d, %Y')}"
        for e in completed:
            ev_start = datetime.datetime.fromtimestamp(e["start"])
            ev_end = datetime.datetime.fromtimestamp(e["end"])
            if ev_end <= start_of_week or ev_start >= end_of_week:
                continue
            clipped_start = max(ev_start, start_of_week)
            clipped_end = min(ev_end, end_of_week)
            if clipped_start >= clipped_end:
                continue
            cur = clipped_start
            while cur < clipped_end:
                day_end = (cur + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                seg_end = min(day_end, clipped_end)
                minutes = (seg_end - cur).total_seconds() / 60.0
                day_idx = (cur.date() - start_of_week.date()).days
                if 0 <= day_idx < 7:
                    buckets[day_idx] += minutes
                cur = seg_end
        return {"labels": labels, "values": [round(v, 1) for v in buckets], "title": title}

    elif period == "month":
        # Shift by offset months
        target_year = now.year
        target_month = now.month + offset
        while target_month < 1:
            target_month += 12
            target_year -= 1
        while target_month > 12:
            target_month -= 12
            target_year += 1
        start_of_month = datetime.datetime(target_year, target_month, 1)
        days_in_month = calendar.monthrange(target_year, target_month)[1]
        end_of_month = start_of_month + datetime.timedelta(days=days_in_month)
        if end_of_month > now:
            end_of_month = now
        buckets = [0.0] * days_in_month
        labels = [str(d) for d in range(1, days_in_month + 1)]
        title = start_of_month.strftime("%B %Y")
        for e in completed:
            ev_start = datetime.datetime.fromtimestamp(e["start"])
            ev_end = datetime.datetime.fromtimestamp(e["end"])
            if ev_end <= start_of_month or ev_start >= end_of_month:
                continue
            clipped_start = max(ev_start, start_of_month)
            clipped_end = min(ev_end, end_of_month)
            if clipped_start >= clipped_end:
                continue
            cur = clipped_start
            while cur < clipped_end:
                day_end = (cur + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                seg_end = min(day_end, clipped_end)
                minutes = (seg_end - cur).total_seconds() / 60.0
                buckets[cur.day - 1] += minutes
                cur = seg_end
        return {"labels": labels, "values": [round(v, 1) for v in buckets], "title": title}

    else:  # year
        # Shift by offset years
        target_year = now.year + offset
        start_of_year = datetime.datetime(target_year, 1, 1)
        end_of_year = datetime.datetime(target_year + 1, 1, 1)
        if end_of_year > now:
            end_of_year = now
        buckets = [0.0] * 12
        labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        title = str(target_year)
        for e in completed:
            ev_start = datetime.datetime.fromtimestamp(e["start"])
            ev_end = datetime.datetime.fromtimestamp(e["end"])
            if ev_end <= start_of_year or ev_start >= end_of_year:
                continue
            clipped_start = max(ev_start, start_of_year)
            clipped_end = min(ev_end, end_of_year)
            if clipped_start >= clipped_end:
                continue
            cur = clipped_start
            while cur < clipped_end:
                days_in_m = calendar.monthrange(cur.year, cur.month)[1]
                month_end = cur.replace(day=days_in_m, hour=23, minute=59, second=59, microsecond=999999) + datetime.timedelta(microseconds=1)
                seg_end = min(month_end, clipped_end)
                minutes = (seg_end - cur).total_seconds() / 60.0
                buckets[cur.month - 1] += minutes
                cur = seg_end
        return {"labels": labels, "values": [round(v, 1) for v in buckets], "title": title}


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
