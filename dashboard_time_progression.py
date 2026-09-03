"""Date ranges and completion-time aggregates shared by the Dashboard UI."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import math


DATE_FILTER_DAYS = {
    "last_week": 7, "last_month": 30, "3_months": 90,
    "6_months": 180, "1_year": 365,
}
DATE_FILTER_LABELS = {
    "all_time": "All Time", "last_week": "Last Week", "last_month": "Last Month",
    "3_months": "Last 3 Months", "6_months": "Last 6 Months", "1_year": "Last Year",
}


def period_start(date_filter, today):
    """Rolling periods include today and the preceding N-1 calendar dates."""
    days = DATE_FILTER_DAYS.get(date_filter)
    return today - timedelta(days=days - 1) if days else None


def completion_date(record):
    try:
        return datetime.strptime(record.get("completed_date"), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def completion_in_period(record, date_filter, today):
    start = period_start(date_filter, today)
    completed = completion_date(record)
    if start is None:
        # Undated completion still counts in all-time summary metrics.
        return completed is None or completed <= today
    return bool(record.get("completed") and completed and start <= completed <= today)


def build_time_progression(records, date_filter, today):
    """Build daily/ monthly buckets, filtering before averaging each hack once."""
    daily = date_filter in ("last_week", "last_month")
    key_format = "%Y-%m-%d" if daily else "%Y-%m"
    label_format = "%d %b" if daily else "%b %Y"
    grouped = defaultdict(lambda: defaultdict(list))
    earliest = None
    for record in records.values():
        if not record.get("completed") or not completion_in_period(record, date_filter, today):
            continue
        completed = completion_date(record)
        if completed is None:
            continue  # An undated completion cannot be placed on a timeline.
        raw_duration = record.get("time_to_beat", 0)
        if isinstance(raw_duration, bool):
            continue
        try:
            duration = float(raw_duration)
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(duration) or duration <= 0:
            continue
        types = record.get("hack_types") or [record.get("hack_type") or "standard"]
        if isinstance(types, str):
            types = [types]
        types = tuple(sorted({str(value).strip().lower() for value in types if str(value).strip()}))
        difficulty = record.get("current_difficulty") or "Unknown"
        grouped[completed.strftime(key_format)][difficulty].append((duration / 3600, types))
        earliest = completed if earliest is None else min(earliest, completed)

    start = period_start(date_filter, today) or earliest
    if start is None:
        return {}
    cursor = start if daily else start.replace(day=1)
    result = {}
    while cursor <= today:
        key = cursor.strftime(key_format)
        difficulties = {}
        for difficulty, completions in grouped.get(key, {}).items():
            by_type = defaultdict(list)
            for duration, types in completions:
                for kind in types:
                    by_type[kind].append(duration)
            difficulties[difficulty] = {
                "avg_time": sum(row[0] for row in completions) / len(completions),
                "count": len(completions),
                "types": sorted(by_type),
                "by_type": {
                    kind: {"avg_time": sum(times) / len(times), "count": len(times)}
                    for kind, times in by_type.items()
                },
            }
        result[key] = {"month_name": cursor.strftime(label_format), "difficulties": difficulties}
        if daily:
            cursor += timedelta(days=1)
        elif cursor.month == 12:
            if cursor.year == 9999:
                break
            cursor = cursor.replace(year=cursor.year + 1, month=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1)
    return result


def progression_average(bucket, difficulty, filter_type="All Types"):
    values = bucket.get("difficulties", {}).get(difficulty)
    if not values:
        return None
    if filter_type == "All Types":
        return values["avg_time"]
    return values.get("by_type", {}).get(filter_type, {}).get("avg_time")


def timeline_label_indices(count, width, minimum_spacing=90):
    """Thin only axis labels, retaining all data points and both endpoint labels."""
    if count <= 0:
        return ()
    if count == 1:
        return (0,)
    capacity = max(2, int(width // minimum_spacing) + 1)
    step = max(1, math.ceil((count - 1) / (capacity - 1)))
    indices = list(range(0, count, step))
    if indices[-1] != count - 1:
        if len(indices) > 1 and count - 1 - indices[-1] < step:
            indices.pop()
        indices.append(count - 1)
    return tuple(indices)
