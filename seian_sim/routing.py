"""Grid-aware route-cost calculation and graph routing."""

from __future__ import annotations

import networkx as nx

from seian_sim.config import RoutingWeights
from seian_sim.enums import FaultStatus
from seian_sim.models import RoutingEntry, fault_penalty
from seian_sim.node import SeianNode


def route_cost(
    *,
    hop_count: int,
    link_quality: float,
    health_score: float,
    load_percent: float,
    fault_status: FaultStatus,
    leads_to_gateway: bool,
    weights: RoutingWeights,
) -> float:
    """Compute SEIAN-AMRP grid-aware route cost; lower is better."""

    return (
        weights.hop_count * hop_count
        + weights.link_loss * (1.0 - link_quality)
        + weights.node_health * (1.0 - health_score)
        + weights.load * (load_percent / 100.0)
        + weights.fault * fault_penalty(fault_status)
        + weights.gateway_bonus * (1.0 if leads_to_gateway else 0.0)
    )


class RoutingEngine:
    """Builds shortest paths over current neighbor observations."""

    def __init__(self, weights: RoutingWeights, route_lifetime_s: float, max_hops: int) -> None:
        self.weights = weights
        self.route_lifetime_s = route_lifetime_s
        self.max_hops = max_hops

    def build_graph(self, nodes: dict[str, SeianNode]) -> nx.Graph:
        """Create an undirected graph from active nodes and neighbor tables."""

        graph = nx.Graph()
        for node in nodes.values():
            if node.active:
                graph.add_node(node.node_id)
        online_gateways = {n.node_id for n in nodes.values() if n.gateway_capable and n.gateway_online and n.active}
        for node in nodes.values():
            if not node.active:
                continue
            for neighbor_id, entry in node.neighbor_table.items():
                neighbor = nodes.get(neighbor_id)
                if not neighbor or not neighbor.active:
                    continue
                leads_to_gateway = neighbor_id in online_gateways or neighbor.gateway_distance is not None
                cost = route_cost(
                    hop_count=1,
                    link_quality=entry.link_quality,
                    health_score=neighbor.health_score,
                    load_percent=neighbor.load_percent,
                    fault_status=neighbor.fault_status,
                    leads_to_gateway=leads_to_gateway,
                    weights=self.weights,
                )
                graph.add_edge(node.node_id, neighbor_id, weight=max(0.01, cost), link_quality=entry.link_quality)
        return graph

    def recalculate(self, nodes: dict[str, SeianNode], timestamp: float) -> int:
        """Recalculate all routing tables and return changed-entry count."""

        graph = self.build_graph(nodes)
        changes = 0
        gateways = [n.node_id for n in nodes.values() if n.gateway_capable and n.gateway_online and n.active]
        for node in nodes.values():
            if not node.active:
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

    def _backup_next_hop(self, graph: nx.Graph, source: str, destination: str, primary: str) -> str | None:
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
