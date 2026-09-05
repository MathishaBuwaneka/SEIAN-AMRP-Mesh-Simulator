"""Turn a read_output_channels reply into plottable per-channel series.

Kept separate from ``dashboard.py`` so the parsing can be tested without a
Streamlit runtime. The response shape this targets, as returned live by the
PSCAD MCP server's ``read_output_channels``::

    {"file": ..., "sample_count": 20001,
     "channels": {"Root/Main/Vrms_N02/0/1": {"name": "Vrms_N02",
                                             "preview": {"time": [...], "values": [...]}}}}

Channel naming comes from ``build_lv_feeder.py``: ``Vrms_<node>`` for bus RMS
voltage, ``Irms_<line_id>`` for line RMS current, ``P_<line_id>`` for active
power flow, and ``State_<line_id>`` for the commanded breaker state. Physical
fault evidence uses ``Ifault[A-C]_<fault_id>`` and ``FaultState_<fault_id>``.
``Q_`` is also understood for future reactive-power recorders.
"""

from __future__ import annotations

from typing import Any

__all__ = ["extract_channel_series", "group_channels", "CHANNEL_GROUPS"]

# (group title, label prefix) in display order.
CHANNEL_GROUPS: tuple[tuple[str, str], ...] = (
    ("Bus RMS Voltage (kV)", "Vrms_"),
    ("Line RMS Current (kA)", "Irms_"),
    ("Line Active Power (MW)", "P_"),
    ("Line Reactive Power (MVAR)", "Q_"),
    ("Breaker Command State (0 closed, 1 open)", "State_"),
    ("Physical Fault Current (kA)", "Ifault"),
    ("Physical Fault State (0 clear, 1 active)", "FaultState_"),
)


def extract_channel_series(channel_data: Any) -> dict[str, dict[str, list[float]]]:
    """Return ``{label: {"time": [...], "values": [...]}}`` for each channel.

    Tolerates the ``{"result": ...}`` wrapper, a missing/!dict payload, and
    channels without preview data -- anything unparseable is skipped rather
    than raising, so an unexpected shape means "no chart", not a crash.
    """

    if not isinstance(channel_data, dict):
        return {}
    payload = channel_data.get("result", channel_data)
    if not isinstance(payload, dict):
        return {}
    rows = payload.get("channels")
    if not isinstance(rows, dict):
        return {}

    series: dict[str, dict[str, list[float]]] = {}
    for path, entry in rows.items():
        if not isinstance(entry, dict):
            continue
        preview = entry.get("preview") or {}
        times = preview.get("time")
        values = preview.get("values")
        if not times or not values:
            continue
        label = entry.get("name") or _label_from_path(str(path))
        try:
            series[str(label)] = {
                "time": [float(t) for t in times],
                "values": [float(v) for v in values],
            }
        except (TypeError, ValueError):
            continue
    return series


def group_channels(
    series: dict[str, dict[str, list[float]]],
) -> list[tuple[str, dict[str, dict[str, list[float]]]]]:
    """Bucket channels into display groups, with anything else last."""

    grouped: list[tuple[str, dict[str, dict[str, list[float]]]]] = []
    claimed: set[str] = set()
    for title, prefix in CHANNEL_GROUPS:
        bucket = {name: data for name, data in series.items() if name.startswith(prefix)}
        claimed.update(bucket)
        if bucket:
            grouped.append((title, bucket))
    rest = {name: data for name, data in series.items() if name not in claimed}
    if rest:
        grouped.append(("Other Channels", rest))
    return grouped


def _label_from_path(path: str) -> str:
    """``Root/Main/Vrms_N02/0/1`` -> ``Vrms_N02`` (fallback when name is absent)."""

    segments = path.split("/")
    return segments[2] if len(segments) >= 3 else path
