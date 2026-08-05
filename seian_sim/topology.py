"""Topology inspection and resilience analysis for SEIAN-AMRP simulations."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

import networkx as nx

if TYPE_CHECKING:
    from seian_sim.simulator import SeianMeshSimulator


@dataclass(slots=True)
class TopologyIssue:
    """One actionable topology finding."""

    severity: str
    code: str
    message: str
    nodes: list[str]


def build_topology_graph(sim: "SeianMeshSimulator", *, active_only: bool = True) -> nx.Graph:
    """Build an undirected graph from current neighbor-table relationships."""

    graph = nx.Graph()
    for node in sim.nodes.values():
        if active_only and not node.active:
            continue
        graph.add_node(node.node_id)

    for node in sim.nodes.values():
        if node.node_id not in graph:
            continue
        for neighbor_id, entry in node.neighbor_table.items():
            if neighbor_id not in graph:
                continue
            reverse = sim.nodes[neighbor_id].neighbor_table.get(node.node_id)
            qualities = [entry.link_quality]
            if reverse is not None:
                qualities.append(reverse.link_quality)
            graph.add_edge(
                node.node_id,
                neighbor_id,
                link_quality=sum(qualities) / len(qualities),
            )
    return graph


def trace_route(sim: "SeianMeshSimulator", source_id: str, destination_id: str) -> list[str]:
    """Follow routing-table next hops and return a complete path.

    An empty list means no valid current route exists. A ValueError is raised only
    for unknown node IDs so the dashboard can distinguish input errors from a
    disconnected topology.
    """

    if source_id not in sim.nodes or destination_id not in sim.nodes:
        raise ValueError("Source and destination must exist in the simulation.")
    if source_id == destination_id:
        return [source_id]
    if not sim.nodes[source_id].active or not sim.nodes[destination_id].active:
        return []

    path = [source_id]
    current = source_id
    visited = {source_id}
    for _ in range(max(1, sim.config.max_hops)):
        entry = sim.nodes[current].routing_table.get(destination_id)
        if entry is None:
            return []
        next_hop = entry.next_hop_id
        if next_hop in visited or next_hop not in sim.nodes:
            return []
        if not sim.nodes[next_hop].active:
            return []
        if next_hop not in sim.nodes[current].neighbor_table:
            return []
        path.append(next_hop)
        if next_hop == destination_id:
            return path
        visited.add(next_hop)
        current = next_hop
    return []


def link_table(sim: "SeianMeshSimulator") -> list[dict[str, Any]]:
    """Return one row per physical mesh link for dashboard display and export."""

    graph = build_topology_graph(sim)
    bridges = {frozenset(edge) for edge in nx.bridges(graph)} if graph.number_of_edges() else set()
    rows: list[dict[str, Any]] = []
    for node_a, node_b in sorted(graph.edges()):
        a = sim.nodes[node_a]
        b = sim.nodes[node_b]
        ab = a.neighbor_table.get(node_b)
        ba = b.neighbor_table.get(node_a)
        rssi_values = [entry.rssi for entry in (ab, ba) if entry is not None]
        snr_values = [entry.snr for entry in (ab, ba) if entry is not None]
        quality_values = [entry.link_quality for entry in (ab, ba) if entry is not None]
        rows.append(
            {
                "node_a": node_a,
                "node_b": node_b,
                "distance_m": round(math.dist(a.position, b.position), 2),
                "rssi_dbm": round(sum(rssi_values) / len(rssi_values), 2) if rssi_values else None,
                "snr_db": round(sum(snr_values) / len(snr_values), 2) if snr_values else None,
                "link_quality": round(sum(quality_values) / len(quality_values), 4) if quality_values else None,
                "bidirectional": ab is not None and ba is not None,
                "bridge_link": frozenset((node_a, node_b)) in bridges,
            }
        )
    return rows


def _gateway_reachable_nodes(graph: nx.Graph, gateways: list[str]) -> set[str]:
    reachable: set[str] = set()
    for gateway in gateways:
        if gateway not in graph:
            continue
        reachable.update(nx.node_connected_component(graph, gateway))
    return reachable


def node_failure_impact(sim: "SeianMeshSimulator") -> list[dict[str, Any]]:
    """Estimate how each single-node failure affects gateway reachability."""

    graph = build_topology_graph(sim)
    gateways = sorted(
        node.node_id
        for node in sim.nodes.values()
        if node.active and node.gateway_capable and node.gateway_online
    )
    baseline = _gateway_reachable_nodes(graph, gateways)
    rows: list[dict[str, Any]] = []
    for node_id in sorted(graph.nodes):
        reduced = graph.copy()
        reduced.remove_node(node_id)
        remaining_gateways = [gateway for gateway in gateways if gateway != node_id]
        after = _gateway_reachable_nodes(reduced, remaining_gateways)
        newly_unreachable = sorted((baseline - {node_id}) - after)
        rows.append(
            {
                "failed_node": node_id,
                "is_gateway": node_id in gateways,
                "newly_gateway_unreachable": len(newly_unreachable),
                "affected_nodes": ", ".join(newly_unreachable),
            }
        )
    return sorted(
        rows,
        key=lambda row: (row["newly_gateway_unreachable"], row["is_gateway"]),
        reverse=True,
    )


def analyze_topology(sim: "SeianMeshSimulator") -> dict[str, Any]:
    """Calculate connectivity, redundancy, gateway reachability, and issues."""

    graph = build_topology_graph(sim)
    active_nodes = sorted(graph.nodes)
    online_gateways = sorted(
        node.node_id
        for node in sim.nodes.values()
        if node.active and node.gateway_capable and node.gateway_online
    )
    components = [sorted(component) for component in nx.connected_components(graph)] if active_nodes else []
    components.sort(key=lambda component: (-len(component), component))
    isolated_nodes = sorted(nx.isolates(graph)) if active_nodes else []
    articulation_points = sorted(nx.articulation_points(graph)) if graph.number_of_nodes() > 2 else []
    bridges = sorted(tuple(sorted(edge)) for edge in nx.bridges(graph)) if graph.number_of_edges() else []
    gateway_reachable = _gateway_reachable_nodes(graph, online_gateways)
    gateway_unreachable = sorted(set(active_nodes) - gateway_reachable) if online_gateways else active_nodes

    asymmetric_links: list[tuple[str, str]] = []
    for node in sim.nodes.values():
        if not node.active:
            continue
        for neighbor_id in node.neighbor_table:
            neighbor = sim.nodes.get(neighbor_id)
            if neighbor and neighbor.active and node.node_id not in neighbor.neighbor_table:
                asymmetric_links.append((node.node_id, neighbor_id))

    invalid_routes: list[str] = []
    for source_id, node in sim.nodes.items():
        if not node.active:
            continue
        for destination_id in node.routing_table:
            if destination_id == source_id:
                invalid_routes.append(f"{source_id}->{destination_id}: self-route")
                continue
            if not trace_route(sim, source_id, destination_id):
                invalid_routes.append(f"{source_id}->{destination_id}")

    issues: list[TopologyIssue] = []
    if not active_nodes:
        issues.append(TopologyIssue("error", "NO_ACTIVE_NODES", "The topology has no active nodes.", []))
    if len(components) > 1:
        issues.append(
            TopologyIssue(
                "error",
                "DISCONNECTED_MESH",
                f"The active mesh is split into {len(components)} disconnected components.",
                [node for component in components[1:] for node in component],
            )
        )
    if isolated_nodes:
        issues.append(
            TopologyIssue(
                "error",
                "ISOLATED_NODES",
                "Some nodes have no active LoRa neighbors.",
                isolated_nodes,
            )
        )
    if not online_gateways:
        issues.append(
            TopologyIssue(
                "warning",
                "NO_ONLINE_GATEWAY",
                "No gateway is online. Local mesh operation can continue, but cloud delivery is unavailable.",
                [],
            )
        )
    elif gateway_unreachable:
        issues.append(
            TopologyIssue(
                "error",
                "GATEWAY_UNREACHABLE",
                "Some active nodes cannot reach any online gateway.",
                gateway_unreachable,
            )
        )
    if articulation_points:
        issues.append(
            TopologyIssue(
                "warning",
                "CRITICAL_RELAY_NODES",
                "Failure of these relay nodes can split the physical mesh.",
                articulation_points,
            )
        )
    if bridges:
        bridge_nodes = sorted({node for edge in bridges for node in edge})
        issues.append(
            TopologyIssue(
                "warning",
                "SINGLE_LINK_CUTS",
                f"The topology contains {len(bridges)} bridge link(s) with no alternate physical path.",
                bridge_nodes,
            )
        )
    if asymmetric_links:
        issues.append(
            TopologyIssue(
                "warning",
                "ASYMMETRIC_NEIGHBORS",
                "Some neighbor relationships are one-way and may cause routing inconsistencies.",
                sorted({node for edge in asymmetric_links for node in edge}),
            )
        )
    if invalid_routes:
        issues.append(
            TopologyIssue(
                "error",
                "INVALID_ROUTES",
                "Some routing-table entries cannot be followed through active neighbor links.",
                sorted({route.split("->", 1)[0] for route in invalid_routes}),
            )
        )

    average_degree = (
        sum(dict(graph.degree()).values()) / graph.number_of_nodes()
        if graph.number_of_nodes()
        else 0.0
    )
    connected = graph.number_of_nodes() > 0 and nx.is_connected(graph)
    largest_component = graph.subgraph(components[0]) if components else graph
    diameter = nx.diameter(largest_component) if largest_component.number_of_nodes() > 1 else 0

    return {
        "active_node_count": graph.number_of_nodes(),
        "inactive_node_count": sum(1 for node in sim.nodes.values() if not node.active),
        "link_count": graph.number_of_edges(),
        "connected": connected,
        "component_count": len(components),
        "components": components,
        "isolated_nodes": isolated_nodes,
        "online_gateways": online_gateways,
        "gateway_reachable_nodes": sorted(gateway_reachable),
        "gateway_unreachable_nodes": gateway_unreachable,
        "articulation_points": articulation_points,
        "bridge_links": [list(edge) for edge in bridges],
        "asymmetric_links": [list(edge) for edge in asymmetric_links],
        "invalid_routes": invalid_routes,
        "average_degree": round(average_degree, 3),
        "density": round(nx.density(graph), 4) if graph.number_of_nodes() > 1 else 0.0,
        "largest_component_diameter_hops": diameter,
        "issues": [asdict(issue) for issue in issues],
    }
