"""Switchable LV power-plane model for SEIAN co-simulation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

import networkx as nx

from seian_power_pipeline.control_plane import (
    ControlAction,
    LineEndpoint,
    NetworkControlCommand,
    command_edges_for_path,
)

if TYPE_CHECKING:
    from seian_sim.simulator import SeianMeshSimulator


@dataclass(slots=True)
class PowerLine:
    """One switchable LV feeder segment, breaker, or tie switch."""

    line_id: str
    node_a: str
    node_b: str
    closed: bool = True
    normally_closed: bool = True
    capacity_kw: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def endpoints(self) -> LineEndpoint:
        return tuple(sorted((self.node_a, self.node_b)))  # type: ignore[return-value]

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["endpoints"] = list(self.endpoints)
        return row


@dataclass(slots=True)
class SwitchingOperation:
    """One accepted, rejected, or no-op switch operation."""

    operation_id: str
    command_id: str
    timestamp: float
    line_id: str
    node_a: str
    node_b: str
    action: str
    before_closed: bool
    after_closed: bool
    accepted: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SwitchingPlan:
    """Result of applying one control command to the LV switch model."""

    command: NetworkControlCommand
    accepted: bool
    operations: list[SwitchingOperation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command.to_dict(),
            "accepted": self.accepted,
            "operations": [operation.to_dict() for operation in self.operations],
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class PowerPlaneAnalysis:
    """Connectivity and energization summary for a switch state."""

    source_nodes: list[str]
    energized_nodes: list[str]
    deenergized_nodes: list[str]
    closed_line_count: int
    open_line_count: int
    island_count: int
    cycles: list[list[str]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PowerPlaneState:
    """Digital switch-state twin controlled by AMRP/SDN decisions."""

    def __init__(
        self,
        nodes: set[str],
        lines: list[PowerLine],
        *,
        source_nodes: set[str],
        preserve_radial: bool = True,
    ) -> None:
        self.nodes = set(nodes)
        self.source_nodes = set(source_nodes)
        self.preserve_radial = preserve_radial
        self.lines: dict[str, PowerLine] = {}
        self._line_by_endpoints: dict[LineEndpoint, str] = {}
        self.history: list[SwitchingPlan] = []
        for line in lines:
            self.add_line(line)

    @classmethod
    def from_simulator(
        cls,
        sim: "SeianMeshSimulator",
        *,
        power_lines: list[dict[str, Any]] | None = None,
        preserve_radial: bool = True,
    ) -> "PowerPlaneState":
        source_nodes = {
            node.node_id
            for node in sim.nodes.values()
            if node.gateway_capable and node.gateway_online and node.active
        }
        if power_lines:
            lines = [_line_from_dict(row) for row in power_lines]
        else:
            from seian_sim.topology import build_topology_graph

            graph = build_topology_graph(sim)
            lines = [
                PowerLine(
                    line_id=_default_line_id(node_a, node_b),
                    node_a=node_a,
                    node_b=node_b,
                    closed=True,
                    normally_closed=True,
                )
                for node_a, node_b in sorted(graph.edges())
            ]
        return cls(set(sim.nodes), lines, source_nodes=source_nodes, preserve_radial=preserve_radial)

    @classmethod
    def from_topology_payload(
        cls,
        payload: dict[str, Any],
        sim: "SeianMeshSimulator",
        *,
        preserve_radial: bool = True,
    ) -> "PowerPlaneState":
        return cls.from_simulator(
            sim,
            power_lines=payload.get("power_lines"),
            preserve_radial=preserve_radial,
        )

    def add_line(self, line: PowerLine) -> None:
        if line.line_id in self.lines:
            raise ValueError(f"Duplicate power line ID: {line.line_id}")
        if line.node_a not in self.nodes or line.node_b not in self.nodes:
            raise ValueError(f"{line.line_id}: line endpoints must exist as nodes.")
        endpoints = line.endpoints
        if endpoints in self._line_by_endpoints:
            existing = self._line_by_endpoints[endpoints]
            raise ValueError(f"{line.line_id}: duplicates endpoint pair already used by {existing}.")
        self.lines[line.line_id] = line
        self._line_by_endpoints[endpoints] = line.line_id

    def apply_command(self, command: NetworkControlCommand) -> SwitchingPlan:
        warnings = self._validate_command(command)
        requests = self._requested_switches(command)
        operations = [
            self._apply_switch(command, index, line_id, close, reason)
            for index, (line_id, close, reason) in enumerate(requests, start=1)
        ]
        accepted = not warnings and all(operation.accepted for operation in operations)
        plan = SwitchingPlan(command=command, accepted=accepted, operations=operations, warnings=warnings)
        self.history.append(plan)
        return plan

    def analyze(self) -> PowerPlaneAnalysis:
        graph = self.closed_graph()
        energized: set[str] = set()
        for source in self.source_nodes:
            if source in graph:
                energized.update(nx.node_connected_component(graph, source))
        cycles = [sorted(cycle) for cycle in nx.cycle_basis(graph)]
        return PowerPlaneAnalysis(
            source_nodes=sorted(self.source_nodes),
            energized_nodes=sorted(energized),
            deenergized_nodes=sorted(self.nodes - energized),
            closed_line_count=sum(1 for line in self.lines.values() if line.closed),
            open_line_count=sum(1 for line in self.lines.values() if not line.closed),
            island_count=nx.number_connected_components(graph) if graph.number_of_nodes() else 0,
            cycles=cycles,
        )

    def closed_graph(self) -> nx.Graph:
        graph = nx.Graph()
        graph.add_nodes_from(sorted(self.nodes))
        for line in self.lines.values():
            if line.closed:
                graph.add_edge(line.node_a, line.node_b, line_id=line.line_id)
        return graph

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": sorted(self.nodes),
            "source_nodes": sorted(self.source_nodes),
            "preserve_radial": self.preserve_radial,
            "lines": [line.to_dict() for line in sorted(self.lines.values(), key=lambda item: item.line_id)],
            "analysis": self.analyze().to_dict(),
        }

    def _validate_command(self, command: NetworkControlCommand) -> list[str]:
        warnings: list[str] = []
        command_nodes = [
            command.source_node_id,
            command.destination_node_id,
            command.target_node_id,
            *command.path,
            *command.blocked_nodes,
        ]
        unknown = sorted({node for node in command_nodes if node is not None and node not in self.nodes})
        if unknown:
            warnings.append(f"Unknown node(s): {', '.join(unknown)}")
        if command.path and command.source_node_id and command.path[0] != command.source_node_id:
            warnings.append("Path does not start at source_node_id.")
        if command.path and command.destination_node_id and command.path[-1] != command.destination_node_id:
            warnings.append("Path does not end at destination_node_id.")
        for edge in command_edges_for_path(command.path) if command.path else []:
            if edge not in self._line_by_endpoints:
                warnings.append(f"Path references unknown line: {edge[0]}-{edge[1]}")
        for edge in [*command.open_lines, *command.close_lines]:
            if edge not in self._line_by_endpoints:
                warnings.append(f"Command references unknown line: {edge[0]}-{edge[1]}")
        if command.target_line_id and command.target_line_id not in self.lines:
            warnings.append(f"Unknown target_line_id: {command.target_line_id}")
        return warnings

    def _requested_switches(self, command: NetworkControlCommand) -> list[tuple[str, bool, str]]:
        requests: list[tuple[str, bool, str]] = []

        def add_edge(edge: LineEndpoint, close: bool, reason: str) -> None:
            line_id = self._line_by_endpoints.get(edge)
            if line_id is not None:
                requests.append((line_id, close, reason))

        if command.action == ControlAction.OPEN_LINE and command.target_line_id:
            requests.append((command.target_line_id, False, command.reason or "open target line"))
        elif command.action == ControlAction.CLOSE_LINE and command.target_line_id:
            requests.append((command.target_line_id, True, command.reason or "close target line"))

        if command.action in {
            ControlAction.APPLY_SWITCH_SET,
            ControlAction.OPEN_LINE,
            ControlAction.CLOSE_LINE,
            ControlAction.REROUTE_POWER_PATH,
        }:
            for edge in command.open_lines:
                add_edge(edge, False, command.reason or "open requested line")
            for edge in command.close_lines:
                add_edge(edge, True, command.reason or "close requested line")

        if command.action in {ControlAction.ISOLATE_NODE, ControlAction.REROUTE_POWER_PATH}:
            blocked_nodes = set(command.blocked_nodes)
            if command.target_node_id:
                blocked_nodes.add(command.target_node_id)
            for node_id in sorted(blocked_nodes):
                for line in self._incident_lines(node_id):
                    requests.append((line.line_id, False, command.reason or f"isolate {node_id}"))

        if command.action == ControlAction.RESTORE_NODE and command.target_node_id:
            for line in self._incident_lines(command.target_node_id):
                if line.normally_closed:
                    requests.append((line.line_id, True, command.reason or f"restore {command.target_node_id}"))

        if command.action == ControlAction.REROUTE_POWER_PATH and command.path:
            for edge in command_edges_for_path(command.path):
                add_edge(edge, True, command.reason or "close reroute path")

        return _dedupe_switch_requests(requests)

    def _incident_lines(self, node_id: str) -> list[PowerLine]:
        return [
            line
            for line in self.lines.values()
            if line.node_a == node_id or line.node_b == node_id
        ]

    def _apply_switch(
        self,
        command: NetworkControlCommand,
        index: int,
        line_id: str,
        close: bool,
        reason: str,
    ) -> SwitchingOperation:
        line = self.lines[line_id]
        before = line.closed
        action = "close" if close else "open"
        accepted = True
        final_reason = reason

        if before == close:
            action = "noop"
            final_reason = f"already {'closed' if close else 'open'}"
        elif close and self.preserve_radial and self._would_create_cycle(line):
            accepted = False
            final_reason = "rejected: closing line would create a closed-loop LV topology"
        else:
            line.closed = close

        return SwitchingOperation(
            operation_id=f"{command.command_id}-{index:02d}",
            command_id=command.command_id,
            timestamp=command.timestamp,
            line_id=line.line_id,
            node_a=line.node_a,
            node_b=line.node_b,
            action=action,
            before_closed=before,
            after_closed=line.closed,
            accepted=accepted,
            reason=final_reason,
        )

    def _would_create_cycle(self, line: PowerLine) -> bool:
        if line.closed:
            return False
        graph = self.closed_graph()
        return nx.has_path(graph, line.node_a, line.node_b)


def _line_from_dict(row: dict[str, Any]) -> PowerLine:
    if not isinstance(row, dict):
        raise ValueError("Each power_lines entry must be an object.")
    endpoints = row.get("endpoints")
    if endpoints is not None:
        if not isinstance(endpoints, list) or len(endpoints) != 2:
            raise ValueError("power line endpoints must be a two-item list.")
        node_a, node_b = str(endpoints[0]), str(endpoints[1])
    else:
        node_a, node_b = str(row["node_a"]), str(row["node_b"])
    return PowerLine(
        line_id=str(row.get("line_id", _default_line_id(node_a, node_b))),
        node_a=node_a,
        node_b=node_b,
        closed=bool(row.get("closed", True)),
        normally_closed=bool(row.get("normally_closed", row.get("closed", True))),
        capacity_kw=float(row["capacity_kw"]) if row.get("capacity_kw") is not None else None,
        metadata=dict(row.get("metadata", {})),
    )


def _default_line_id(node_a: str, node_b: str) -> str:
    a, b = sorted((node_a, node_b))
    return f"SW_{a}_{b}"


def _dedupe_switch_requests(requests: list[tuple[str, bool, str]]) -> list[tuple[str, bool, str]]:
    deduped: list[tuple[str, bool, str]] = []
    seen: set[tuple[str, bool]] = set()
    for line_id, close, reason in requests:
        key = (line_id, close)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((line_id, close, reason))
    return deduped
