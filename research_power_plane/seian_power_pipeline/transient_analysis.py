"""Event-aligned measurements for PSCAD switching-transient artifacts."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from typing import Any


DEFAULT_VOLTAGE_THRESHOLD_KV = 0.2


def analyze_trace(
    name: str,
    times: Sequence[float],
    values: Sequence[float],
    *,
    event_times_s: list[float],
    before_offset_s: float = 0.1,
    after_offset_s: float = 0.2,
    preview_points: int = 501,
) -> dict[str, Any]:
    """Summarize one trace and sample it on both sides of each event."""

    count = min(len(times), len(values))
    if count == 0:
        return {"samples": 0, "events": [], "preview": {"time": [], "values": []}}

    usable_times = times[:count]
    usable_values = values[:count]
    numeric_values = [float(value) for value in usable_values]
    final_time = float(usable_times[-1])
    events = []
    for event_time in sorted(set(float(value) for value in event_times_s)):
        before_time = max(float(usable_times[0]), event_time - before_offset_s)
        after_time = min(final_time, event_time + after_offset_s)
        before_sample_time, before_value = sample_nearest(usable_times, usable_values, before_time)
        at_sample_time, at_value = sample_nearest(usable_times, usable_values, event_time)
        after_sample_time, after_value = sample_nearest(usable_times, usable_values, after_time)
        events.append(
            {
                "command_time_s": event_time,
                "before_time_s": before_sample_time,
                "before": before_value,
                "at_time_s": at_sample_time,
                "at": at_value,
                "after_time_s": after_sample_time,
                "after": after_value,
                "delta": after_value - before_value,
            }
        )

    preview_indices = _even_indices(count, preview_points)
    result: dict[str, Any] = {
        "final": numeric_values[-1],
        "min": min(numeric_values),
        "max": max(numeric_values),
        "samples": count,
        "events": events,
        "preview": {
            "time": [float(usable_times[index]) for index in preview_indices],
            "values": [float(usable_values[index]) for index in preview_indices],
        },
    }
    if name.startswith("Vrms_"):
        result["interruptions"] = threshold_intervals(
            usable_times,
            usable_values,
            threshold=DEFAULT_VOLTAGE_THRESHOLD_KV,
            ignore_before_s=0.5,
        )
    return result


def sample_nearest(
    times: Sequence[float],
    values: Sequence[float],
    target_s: float,
) -> tuple[float, float]:
    """Return the sample nearest ``target_s`` from monotonic trace data."""

    count = min(len(times), len(values))
    if count == 0:
        raise ValueError("Cannot sample an empty trace.")
    index = bisect_left(times, target_s, 0, count)
    if index <= 0:
        selected = 0
    elif index >= count:
        selected = count - 1
    else:
        left = index - 1
        selected = left if abs(float(times[left]) - target_s) <= abs(float(times[index]) - target_s) else index
    return float(times[selected]), float(values[selected])


def threshold_intervals(
    times: Sequence[float],
    values: Sequence[float],
    *,
    threshold: float,
    ignore_before_s: float = 0.0,
    minimum_duration_s: float = 0.01,
    merge_gap_s: float = 0.02,
) -> list[dict[str, Any]]:
    """Find sustained intervals where a trace remains below ``threshold``."""

    count = min(len(times), len(values))
    if count == 0:
        return []
    start_index = bisect_left(times, ignore_before_s, 0, count)
    raw: list[tuple[float, float, bool]] = []
    interval_start: float | None = None
    for index in range(start_index, count):
        time_s = float(times[index])
        is_low = float(values[index]) < threshold
        if is_low and interval_start is None:
            interval_start = time_s
        elif not is_low and interval_start is not None:
            raw.append((interval_start, time_s, False))
            interval_start = None
    if interval_start is not None:
        raw.append((interval_start, float(times[count - 1]), True))

    merged: list[list[Any]] = []
    for start_s, end_s, ongoing in raw:
        if merged and start_s - float(merged[-1][1]) <= merge_gap_s:
            merged[-1][1] = end_s
            merged[-1][2] = ongoing
        else:
            merged.append([start_s, end_s, ongoing])

    return [
        {
            "start_s": start_s,
            "end_s": end_s,
            "duration_s": end_s - start_s,
            "ongoing_at_end": bool(ongoing),
            "threshold": float(threshold),
        }
        for start_s, end_s, ongoing in merged
        if end_s - start_s >= minimum_duration_s
    ]


def _even_indices(size: int, maximum_points: int) -> list[int]:
    if size <= 0 or maximum_points <= 0:
        return []
    if size <= maximum_points:
        return list(range(size))
    if maximum_points == 1:
        return [size - 1]
    return sorted({round(index * (size - 1) / (maximum_points - 1)) for index in range(maximum_points)})
