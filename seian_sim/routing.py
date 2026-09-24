"""Grid-aware route-cost calculation and graph routing."""

from __future__ import annotations

import networkx as nx

from seian_sim.config import RoutingWeights
from seian_sim.enums import CommunicationFaultStatus, FaultStatus
from seian_sim.models import RoutingEntry, fault_penalty
from seian_sim.node import SeianNode


def route_cost(
    *,
    hop_count: int,
    link_quality: float,
    communication_health: float,
    communication_congestion: float,
    communication_fault_status: CommunicationFaultStatus,
    power_health: float,
    power_load_percent: float,
    power_fault_status: FaultStatus,
    leads_to_gateway: bool,
    weights: RoutingWeights,
) -> float:
    """Compute cross-plane route cost without coupling subsystem availability."""

    return advertised_route_cost(
        hop_count=hop_count,
        link_quality=link_quality,
        communication_health=communication_health,
        communication_congestion=communication_congestion,
        communication_fault_status=communication_fault_status,
        electrical_risk=electrical_risk_score(
            power_health=power_health,
            power_load_percent=power_load_percent,
            power_fault_status=power_fault_status,
            weights=weights,
        ),
        leads_to_gateway=leads_to_gateway,
        weights=weights,
    )


def advertised_route_cost(
    *,
    hop_count: int,
    link_quality: float,
    communication_health: float,
    communication_congestion: float,
    communication_fault_status: CommunicationFaultStatus,
    electrical_risk: float,
    leads_to_gateway: bool,
    weights: RoutingWeights,
) -> float:
    """Compute edge cost from bounded state carried by a neighbor advertisement."""

    communication_fault_penalty = {
        CommunicationFaultStatus.NORMAL: 0.0,
        CommunicationFaultStatus.WARNING: 0.4,
        CommunicationFaultStatus.FAULT: 1.0,
    }[communication_fault_status]
    normalized_electrical_risk = max(0.0, min(1.0, electrical_risk))
    electrical_weight = weights.power_health + weights.power_load + weights.power_fault
    return (
        weights.hop_count * hop_count
        + weights.link_loss * (1.0 - link_quality)
        + weights.communication_health * (1.0 - communication_health)
        + weights.communication_congestion * communication_congestion
        + weights.communication_fault * communication_fault_penalty
        + weights.cross_plane_risk * electrical_weight * normalized_electrical_risk
        + weights.gateway_bonus * (1.0 if leads_to_gateway else 0.0)
    )


def electrical_route_penalty(
    *,
    power_health: float,
    power_load_percent: float,
    power_fault_status: FaultStatus,
    weights: RoutingWeights,
) -> float:
    """Return the bounded electrical contribution to route cost."""

    total_weight = weights.power_health + weights.power_load + weights.power_fault
    return weights.cross_plane_risk * total_weight * electrical_risk_score(
        power_health=power_health,
        power_load_percent=power_load_percent,
        power_fault_status=power_fault_status,
        weights=weights,
    )


def electrical_risk_score(
    *,
    power_health: float,
    power_load_percent: float,
    power_fault_status: FaultStatus,
    weights: RoutingWeights,
) -> float:
    """Return the normalized electrical routing risk in the range 0..1."""

    normalized_health = max(0.0, min(1.0, power_health))
    normalized_load = max(0.0, min(1.0, power_load_percent / 100.0))
    total_weight = weights.power_health + weights.power_load + weights.power_fault
    if total_weight <= 0:
        return 0.0
    weighted_risk = (
        weights.power_health * (1.0 - normalized_health)
        + weights.power_load * normalized_load
        + weights.power_fault * fault_penalty(power_fault_status)
    )
    return max(0.0, min(1.0, weighted_risk / total_weight))


class RoutingEngine:
    """Builds shortest paths over current neighbor observations."""

    def __init__(self, weights: RoutingWeights, route_lifetime_s: float, max_hops: int) -> None:
        self.weights = weights
        self.route_lifetime_s = route_lifetime_s
        self.max_hops = max_hops

    def build_graph(self, nodes: dict[str, SeianNode]) -> nx.DiGraph:
        """Create directed links so next-hop state determines each edge cost."""

        graph = nx.DiGraph()
        for node in nodes.values():
            if node.communication_available:
                graph.add_node(node.node_id)
        online_gateways = {
            node.node_id
            for node in nodes.values()
            if node.gateway_capable and node.gateway_online and node.communication_available
        }
        for node in nodes.values():
            if not node.communication_available:
                continue
            for neighbor_id, entry in node.neighbor_table.items():
                neighbor = nodes.get(neighbor_id)
                if not neighbor or not neighbor.communication_available:
                    continue
                leads_to_gateway = neighbor_id in online_gateways or neighbor.gateway_distance is not None
                cost = route_cost(
                    hop_count=1,
                    link_quality=min(entry.link_quality, entry.link_reliability),
                    communication_health=neighbor.communication_health,
                    communication_congestion=max(
                        neighbor.communication_load,
                        neighbor.communication_congestion,
                    ),
                    communication_fault_status=neighbor.communication_fault_status,
                    power_health=entry.power_health,
                    power_load_percent=entry.power_load_percent,
                    power_fault_status=entry.power_fault_status,
                    leads_to_gateway=leads_to_gateway,
                    weights=self.weights,
                )
                graph.add_edge(node.node_id, neighbor_id, weight=max(0.01, cost), link_quality=entry.link_quality)
        return graph

    def recalculate(self, nodes: dict[str, SeianNode], timestamp: float) -> int:
        """Recalculate all routing tables and return changed-entry count."""

        graph = self.build_graph(nodes)
        changes = 0
        gateways = [
            node.node_id
            for node in nodes.values()
            if node.gateway_capable and node.gateway_online and node.communication_available
        ]
        for node in nodes.values():
            if not node.communication_available:
                node.routing_table.clear()
                node.gateway_distance = None
                continue
            old_routes = dict(node.routing_table)
            node.routing_table.clear()
            node.gateway_distance = 0 if node.node_id in gateways else None
            if node.node_id not in graph:
                continue
            for destination_id in graph.nodes:
                if destination_id == node.node_id:
                    continue
                try:
                    path = nx.shortest_path(graph, node.node_id, destination_id, weight="weight")
                    cost = nx.shortest_path_length(graph, node.node_id, destination_id, weight="weight")
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    continue
                if len(path) - 1 > self.max_hops:
                    continue
                backup = self._backup_next_hop(graph, node.node_id, destination_id, path[1])
                node.routing_table[destination_id] = RoutingEntry(
                    destination_id=destination_id,
                    next_hop_id=path[1],
                    hop_count=len(path) - 1,
                    route_cost=float(cost),
                    route_lifetime=timestamp + self.route_lifetime_s,
                    backup_next_hop=backup,
                    supports_emergency=True,
                    last_update_time=timestamp,
                )
            if gateways:
                reachable = [(gid, node.routing_table[gid].hop_count) for gid in gateways if gid in node.routing_table]
                if reachable:
                    node.gateway_distance = min(hops for _, hops in reachable)
            if self._route_signature(old_routes) != self._route_signature(node.routing_table):
                changes += 1
        return changes

    def _backup_next_hop(self, graph: nx.DiGraph, source: str, destination: str, primary: str) -> str | None:
        graph_copy = graph.copy()
        if graph_copy.has_edge(source, primary):
            graph_copy.remove_edge(source, primary)
        try:
            path = nx.shortest_path(graph_copy, source, destination, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None
        return path[1] if len(path) > 1 else None

    @staticmethod
    def _route_signature(table: dict[str, RoutingEntry]) -> dict[str, tuple[str, int]]:
        return {dest: (entry.next_hop_id, entry.hop_count) for dest, entry in table.items()}
