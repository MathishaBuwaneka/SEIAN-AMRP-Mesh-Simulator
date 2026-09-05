"""Lossless JSON updates and switch-state previews, independent of Streamlit."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import networkx as nx

from seian_power_pipeline.control_plane import control_commands_from_payload
from seian_power_pipeline.faults import physical_faults_from_payload


ACTION_LABELS = {
    "isolate_node": "Isolate bus",
    "restore_node": "Restore bus",
    "open_line": "Open breaker",
    "close_line": "Close breaker",
    "reroute_power_path": "Reroute power",
    "apply_switch_set": "Switch group",
}
FAULT_LABELS = {
    "abc_ground": "ABC to ground", "abc": "ABC (ungrounded)",
    "a_ground": "A to ground", "b_ground": "B to ground", "c_ground": "C to ground",
    "ab_ground": "AB to ground", "bc_ground": "BC to ground", "ca_ground": "CA to ground",
    "ab": "A to B", "bc": "B to C", "ca": "C to A",
}
_ACTION_FIELDS = (
    "source_node_id", "source_node", "destination_node_id", "destination_node",
    "target_node_id", "target_node", "target_line_id", "target_line", "path",
    "route", "preferred_path", "open_lines", "open_edges", "close_lines",
    "close_edges", "blocked_nodes", "avoid_nodes",
)


def command_rows(payload: Any) -> list[dict[str, Any]]:
    control_commands_from_payload(payload)
    return payload["commands"] if isinstance(payload, dict) else payload


def update_command(payload: Any, index: int | None, changes: dict[str, Any]) -> Any:
    updated = deepcopy(payload)
    rows = command_rows(updated)
    row = {} if index is None else rows[index]
    old_action = row.get("action", row.get("type"))
    if "action" in changes and changes["action"] != old_action:
        for field in _ACTION_FIELDS:
            row.pop(field, None)
    row.update(deepcopy(changes))
    if index is None:
        rows.append(row)
    parsed = control_commands_from_payload(updated)
    ids = [command.command_id for command in parsed]
    if len(ids) != len(set(ids)) or any(not value.strip() for value in ids):
        raise ValueError("Command IDs must be nonempty and unique.")
    return updated


def remove_command(payload: Any, index: int) -> Any:
    updated = deepcopy(payload)
    command_rows(updated).pop(index)
    return updated


def update_fault(payload: Any, fault_id: str, event: dict[str, Any] | None) -> dict[str, Any]:
    updated = deepcopy(payload) if isinstance(payload, dict) else {"commands": deepcopy(payload)}
    rows = updated.setdefault("physical_faults", [])
    if rows is None:
        rows = updated["physical_faults"] = []
    existing = next((row for row in rows if row["fault_id"] == fault_id), None)
    if event is None:
        updated["physical_faults"] = [row for row in rows if row["fault_id"] != fault_id]
    else:
        if existing is None:
            existing = {"fault_id": fault_id}
            rows.append(existing)
        existing.update(deepcopy(event))
        existing["fault_id"] = fault_id
        existing.pop("end_s", None)
        existing.pop("phase_flags", None)
    physical_faults_from_payload(updated)
    return updated


def update_switch(topology: dict[str, Any], line_id: str, *, closed: bool, normally_closed: bool) -> dict[str, Any]:
    updated = deepcopy(topology)
    line = next(row for row in updated["power_lines"] if row["line_id"] == line_id)
    line.update(closed=closed, normally_closed=normally_closed)
    return updated


def update_binding(mapping: dict[str, Any], group: str, identity: str, changes: dict[str, int]) -> dict[str, Any]:
    identity_key = "line_id" if group == "line_bindings" else "fault_id"
    if group not in {"line_bindings", "fault_bindings"}:
        raise ValueError("Unknown PSCAD binding group.")
    allowed = {"component_id"} if group == "line_bindings" else {"logic_component_id", "fault_component_id"}
    if set(changes) - allowed or any(type(value) is not int or value <= 0 for value in changes.values()):
        raise ValueError("PSCAD component IDs must be positive integers.")
    updated = deepcopy(mapping)
    row = next(row for row in updated[group] if row[identity_key] == identity)
    row.update(changes)
    return updated


def endpoints(line: dict[str, Any]) -> tuple[str, str]:
    pair = line.get("endpoints") or (line["node_a"], line["node_b"])
    return str(pair[0]), str(pair[1])


def line_label(line: dict[str, Any]) -> str:
    a, b = endpoints(line)
    return f"{a} - {b}" + (" (tie)" if not line.get("normally_closed", True) else "")


def state_at(topology: dict[str, Any], preview: dict[str, Any] | None, time_s: float | None) -> dict[str, Any]:
    states = {row["line_id"]: bool(row.get("closed", True)) for row in topology["power_lines"]}
    active_faults: set[str] = set()
    if preview is not None and time_s is not None:
        for schedule in preview["switching_timeline"]["line_schedules"]:
            for event in schedule["events"]:
                if event["timestamp"] <= time_s:
                    states[event["line_id"]] = event["closed"]
        active_faults = {
            row["node_id"] for row in preview["physical_faults"]
            if row["start_s"] <= time_s < row["end_s"]
        }
    graph = nx.Graph()
    graph.add_nodes_from(row["node_id"] for row in topology["nodes"])
    graph.add_edges_from(endpoints(row) for row in topology["power_lines"] if states[row["line_id"]])
    sources = {
        row["node_id"] for row in topology["nodes"]
        if row.get("gateway_capable") and row.get("gateway_online", True) and row.get("active", True)
    }
    connected: set[str] = set()
    for source in sources:
        connected.update(nx.node_connected_component(graph, source))
    return {"closed": states, "sources": sources, "connected": connected, "faults": active_faults}
