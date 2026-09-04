"""SDN-style network-control command schema for SEIAN power switching."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ControlAction(str, Enum):
    """Supported commands from the always-connected network control plane."""

    REROUTE_POWER_PATH = "reroute_power_path"
    APPLY_SWITCH_SET = "apply_switch_set"
    OPEN_LINE = "open_line"
    CLOSE_LINE = "close_line"
    ISOLATE_NODE = "isolate_node"
    RESTORE_NODE = "restore_node"


LineEndpoint = tuple[str, str]


@dataclass(slots=True)
class NetworkControlCommand:
    """One normalized command emitted by the AMRP/SDN controller."""

    command_id: str
    action: ControlAction
    timestamp: float = 0.0
    controller_id: str = "network-control"
    priority: int = 5
    source_node_id: str | None = None
    destination_node_id: str | None = None
    target_node_id: str | None = None
    target_line_id: str | None = None
    path: list[str] = field(default_factory=list)
    open_lines: list[LineEndpoint] = field(default_factory=list)
    close_lines: list[LineEndpoint] = field(default_factory=list)
    blocked_nodes: list[str] = field(default_factory=list)
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, row: dict[str, Any], *, index: int = 0) -> "NetworkControlCommand":
        if not isinstance(row, dict):
            raise ValueError(f"Command {index} must be an object.")
        raw_action = str(row.get("action", row.get("type", ""))).strip()
        if not raw_action:
            raise ValueError(f"Command {index} must include an action.")
        try:
            action = ControlAction(raw_action)
        except ValueError as exc:
            choices = ", ".join(item.value for item in ControlAction)
            raise ValueError(f"Unsupported action '{raw_action}'. Expected one of: {choices}.") from exc

        command_id = str(row.get("command_id", row.get("id", f"cmd-{index + 1:03d}")))
        source = row.get("source_node_id", row.get("source_node"))
        destination = row.get("destination_node_id", row.get("destination_node"))
        target_node = row.get("target_node_id", row.get("target_node"))
        target_line = row.get("target_line_id", row.get("target_line"))
        path = row.get("path", row.get("route", row.get("preferred_path", [])))

        timestamp = float(row.get("timestamp", 0.0))
        if not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError(f"{command_id}: timestamp must be a finite, non-negative number.")

        return cls(
            command_id=command_id,
            action=action,
            timestamp=timestamp,
            controller_id=str(row.get("controller_id", "network-control")),
            priority=int(row.get("priority", 5)),
            source_node_id=str(source) if source is not None else None,
            destination_node_id=str(destination) if destination is not None else None,
            target_node_id=str(target_node) if target_node is not None else None,
            target_line_id=str(target_line) if target_line is not None else None,
            path=_parse_node_path(path, command_id),
            open_lines=_parse_line_list(row.get("open_lines", row.get("open_edges", [])), command_id),
            close_lines=_parse_line_list(row.get("close_lines", row.get("close_edges", [])), command_id),
            blocked_nodes=[str(node) for node in row.get("blocked_nodes", row.get("avoid_nodes", []))],
            reason=str(row.get("reason", "")),
            metadata=dict(row.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["action"] = self.action.value
        row["open_lines"] = [list(edge) for edge in self.open_lines]
        row["close_lines"] = [list(edge) for edge in self.close_lines]
        return row


def command_edges_for_path(path: list[str]) -> list[LineEndpoint]:
    """Return unordered line endpoints implied by an ordered node path."""

    return [_normalize_edge(a, b) for a, b in zip(path, path[1:])]


def control_commands_from_payload(data: Any) -> list[NetworkControlCommand]:
    """Parse decoded JSON containing a command list or ``commands`` object."""

    rows = data.get("commands") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("Control command JSON must be a list or contain a 'commands' list.")
    return [NetworkControlCommand.from_dict(row, index=index) for index, row in enumerate(rows)]


def load_control_commands(path: str | Path) -> list[NetworkControlCommand]:
    return control_commands_from_payload(json.loads(Path(path).read_text(encoding="utf-8")))


def chronological_commands(commands: list[NetworkControlCommand]) -> list[NetworkControlCommand]:
    """Return commands in stable physical-time order."""

    return [
        command
        for _index, command in sorted(
            enumerate(commands),
            key=lambda item: (item[1].timestamp, item[0]),
        )
    ]


def _parse_node_path(value: Any, command_id: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or any(not isinstance(node, str) for node in value):
        raise ValueError(f"{command_id}: path must be a list of node IDs.")
    if len(value) == 1:
        raise ValueError(f"{command_id}: path must contain at least two nodes when supplied.")
    return list(value)


def _parse_line_list(value: Any, command_id: str) -> list[LineEndpoint]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError(f"{command_id}: line list must be a list.")
    return [_parse_edge(edge, command_id) for edge in value]


def _parse_edge(value: Any, command_id: str) -> LineEndpoint:
    if isinstance(value, str):
        parts = [part.strip() for part in value.replace("->", "-").split("-") if part.strip()]
    elif isinstance(value, (list, tuple)):
        parts = [str(part) for part in value]
    else:
        raise ValueError(f"{command_id}: each line must be a pair of node IDs or 'A-B'.")
    if len(parts) != 2:
        raise ValueError(f"{command_id}: line endpoint {value!r} must contain exactly two nodes.")
    return _normalize_edge(parts[0], parts[1])


def _normalize_edge(node_a: str, node_b: str) -> LineEndpoint:
    if node_a == node_b:
        raise ValueError("A power line cannot connect a node to itself.")
    return tuple(sorted((str(node_a), str(node_b))))  # type: ignore[return-value]
