"""Convert AMRP/SDN controller output into NetworkControlCommand JSON.

The colleagues' simulator (``seian_sim``) does not emit power-switching
commands directly -- it emits *events*: ``FaultEvent`` rows (fault_id,
origin_node, fault_type, severity, start_time, affected_nodes,
recommended_action) and ``EventRecord`` rows (timestamp, category, message,
node_id, fault_id, details), both reachable via
``Simulator.export_tables_json()``. This module turns those into the
switching-command contract in :mod:`seian_power_pipeline.control_plane`.

There is no frozen spec for the controller's eventual output format, so this
is deliberately tolerant: it accepts a payload that is already in native
command form (passed through untouched), a simulator export dict, or a bare
list of fault rows, and it accepts common key aliases for each field. When the
real format lands, the expected place to extend is ``_FIELD_ALIASES`` and
``commands_from_fault_events``.

Typical use::

    from seian_power_pipeline.controller_adapter import commands_from_controller_payload
    payload = json.loads(Path("controller_output.json").read_text())
    commands_json = commands_from_controller_payload(payload)
    commands = control_commands_from_payload(commands_json)
"""

from __future__ import annotations

from typing import Any, Iterable

__all__ = [
    "commands_from_controller_payload",
    "commands_from_fault_events",
    "RESTORATION_ACTION_HINTS",
]

# ``recommended_action`` values that should also emit a restoration command
# after the isolation, when the payload carries a usable alternate path.
RESTORATION_ACTION_HINTS = ("reroute", "restore", "transfer", "switch")

# Accepted input key -> canonical field. Extend here when the real controller
# format is known rather than reworking the conversion logic.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "fault_id": ("fault_id", "id", "event_id"),
    "origin_node": ("origin_node", "node_id", "node", "origin", "source_node"),
    "fault_type": ("fault_type", "type", "kind"),
    "severity": ("severity", "level"),
    "start_time": ("start_time", "timestamp", "time", "t"),
    "affected_nodes": ("affected_nodes", "affected", "impacted_nodes"),
    "recommended_action": ("recommended_action", "action", "recommendation"),
    "restoration_path": ("restoration_path", "reroute_path", "alternate_path", "path"),
}


def commands_from_controller_payload(
    payload: Any,
    *,
    controller_id: str = "amrp-sdn-controller",
    restoration_delay_s: float = 1.0,
) -> dict[str, Any]:
    """Normalize any recognized controller output into ``{"commands": [...]}``.

    Accepts, in priority order: a payload already carrying a ``commands``
    list (returned unchanged), a simulator export dict carrying
    ``fault_events``, or a bare list of fault rows.
    """

    if isinstance(payload, dict) and isinstance(payload.get("commands"), list):
        return payload

    rows: Iterable[Any]
    if isinstance(payload, dict):
        rows = payload.get("fault_events") or payload.get("faults") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError(
            "Controller payload must be a dict (with 'commands' or 'fault_events') or a list of fault rows."
        )

    return {
        "commands": commands_from_fault_events(
            rows,
            controller_id=controller_id,
            restoration_delay_s=restoration_delay_s,
        )
    }


def commands_from_fault_events(
    rows: Iterable[Any],
    *,
    controller_id: str = "amrp-sdn-controller",
    restoration_delay_s: float = 1.0,
) -> list[dict[str, Any]]:
    """Turn fault rows into isolate (and, where warranted, restore) commands.

    Every fault yields an ``isolate_node`` on its origin node. A fault whose
    ``recommended_action`` hints at rerouting *and* that carries a usable
    alternate path additionally yields a ``reroute_power_path`` issued
    ``restoration_delay_s`` after the fault.
    """

    commands: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        fields = _extract(row)
        origin = fields.get("origin_node")
        if not origin:
            continue

        fault_id = fields.get("fault_id") or f"fault-{index + 1:03d}"
        start_time = _as_float(fields.get("start_time"), 0.0)
        reason = _isolation_reason(fields)

        commands.append(
            {
                "command_id": f"{fault_id}-isolate",
                "timestamp": start_time,
                "controller_id": controller_id,
                "action": "isolate_node",
                "target_node_id": str(origin),
                "reason": reason,
                "metadata": _isolation_metadata(fields),
            }
        )

        path = _as_node_list(fields.get("restoration_path"))
        if path and _wants_restoration(fields.get("recommended_action")):
            commands.append(
                {
                    "command_id": f"{fault_id}-restore",
                    "timestamp": start_time + restoration_delay_s,
                    "controller_id": controller_id,
                    "action": "reroute_power_path",
                    "source_node_id": path[0],
                    "destination_node_id": path[-1],
                    "blocked_nodes": [str(origin)],
                    "path": path,
                    "reason": f"Restoration path after {fault_id} isolated {origin}.",
                    "metadata": {"fault_id": fault_id, "derived_from": "recommended_action"},
                }
            )
    return commands


def _extract(row: Any) -> dict[str, Any]:
    """Pull canonical fields out of a dict row or a FaultEvent-like object."""

    if not isinstance(row, dict):
        row = {
            key: getattr(row, key)
            for key in dir(row)
            if not key.startswith("_") and not callable(getattr(row, key, None))
        }
    fields: dict[str, Any] = {}
    for canonical, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            if alias in row and row[alias] is not None:
                fields[canonical] = row[alias]
                break
    return fields


def _isolation_reason(fields: dict[str, Any]) -> str:
    fault_type = fields.get("fault_type")
    severity = fields.get("severity")
    origin = fields.get("origin_node")
    parts = [str(fault_type) if fault_type else "Fault"]
    if severity:
        parts.append(f"({severity})")
    parts.append(f"at {origin}; isolate all incident LV paths.")
    return " ".join(parts)


def _isolation_metadata(fields: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("fault_id", "fault_type", "severity", "recommended_action"):
        if fields.get(key) is not None:
            metadata[key] = _plain(fields[key])
    affected = _as_node_list(fields.get("affected_nodes"))
    if affected:
        metadata["affected_nodes"] = affected
    return metadata


def _wants_restoration(action: Any) -> bool:
    if action is None:
        return False
    text = str(action).lower()
    return any(hint in text for hint in RESTORATION_ACTION_HINTS)


def _as_node_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [part.strip() for part in value.replace("->", ",").split(",")]
        return [part for part in parts if part]
    if isinstance(value, (list, tuple, set)):
        # A set (FaultEvent.affected_nodes) has no meaningful order; sort it so
        # the generated command is deterministic run-to-run.
        items = sorted(value) if isinstance(value, set) else list(value)
        return [str(item) for item in items]
    return []


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _plain(value: Any) -> Any:
    """Enum-ish values (FaultType, severity) render as their plain value."""

    return getattr(value, "value", value)
