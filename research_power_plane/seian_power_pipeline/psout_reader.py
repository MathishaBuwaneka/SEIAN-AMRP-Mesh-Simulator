"""Read selected PSCAD PSOUT traces into the dashboard response shape."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable


def read_selected_channels(
    output_file: str | Path,
    channel_paths: Iterable[str],
    *,
    max_points: int = 500,
) -> dict[str, Any]:
    """Read summaries and bounded previews directly from a fresh PSOUT file."""

    import mhi.psout

    path = Path(output_file).resolve()
    wanted = list(channel_paths)
    wanted_set = set(wanted)
    channels: dict[str, Any] = {}
    sample_count: int | None = None
    max_points = max(1, int(max_points))

    with mhi.psout.File(str(path)) as handle:
        run = handle.run(0)
        for call, trace, trace_path in _iter_traces(handle, run):
            if trace_path not in wanted_set:
                continue
            values = [float(value) for value in trace.data]
            try:
                domain = trace.domain
                times = [float(value) for value in domain.data] if domain is not None else []
            except Exception:
                times = []
            sample_count = len(values)
            count = min(len(values), max_points)
            indices = (
                [round(index * (len(values) - 1) / (count - 1)) for index in range(count)]
                if count > 1 else list(range(count))
            )
            channels[trace_path] = {
                "path": trace_path,
                "name": _meta(call, "Name"),
                "unit": _meta(call, "Unit"),
                "preview": {
                    "time": [times[index] for index in indices] if times else [],
                    "values": [values[index] for index in indices],
                },
                "summary": _summarize(values),
            }

    return {
        "file": str(path),
        "run_index": 0,
        "sample_count": sample_count,
        "channel_count": len(channels),
        "channels": channels,
        "not_found": [path for path in wanted if path not in channels],
    }


def _iter_traces(handle: Any, run: Any):
    separator = getattr(handle, "_sep", "/")
    pgb_by_path: dict[str, Any] = {}
    traces: list[tuple[Any, str]] = []
    for call, path in handle.call_paths("**"):
        source = call.get("Source")
        if source == "PGB":
            pgb_by_path[path] = call
        elif source == "Trace":
            traces.append((call, path))
    for call, path in traces:
        parts = path.split(separator)
        parent = separator.join(parts[:-2]) if len(parts) > 2 else path
        yield pgb_by_path.get(parent), run.trace(call), path


def _meta(call: Any, key: str) -> Any:
    if call is None:
        return None
    try:
        return call.get(key)
    except Exception:
        return None


def _summarize(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    count = len(values)
    return {
        "count": count,
        "min": min(values),
        "max": max(values),
        "mean": math.fsum(values) / count,
        "final": values[-1],
        "rms": math.sqrt(math.fsum(value * value for value in values) / count),
    }
