"""Node-local route learning from SEIAN-AMRP advertisements."""

from __future__ import annotations

from dataclasses import dataclass, replace

from seian_sim.config import RoutingWeights
from seian_sim.models import RoutingEntry
from seian_sim.node import SeianNode
from seian_sim.route_messages import RouteAdvertisement
from seian_sim.enums import CommunicationFaultStatus
from seian_sim.routing import advertised_route_cost, electrical_risk_score


@dataclass(frozen=True, slots=True)
class RouteUpdateResult:
    """Outcome of processing one route advertisement."""

    accepted: bool
    route_changed: bool
    reason: str


class DecentralizedRoutingEngine:
    """Maintain node-owned route candidates without global topology knowledge."""

    def __init__(
        self,
        weights: RoutingWeights,
        route_lifetime_s: float,
        max_hops: int,
        switch_hysteresis: float,
    ) -> None:
        self.weights = weights
        self.route_lifetime_s = route_lifetime_s
        self.max_hops = max_hops
        self.switch_hysteresis = switch_hysteresis

    def reset(self, nodes: dict[str, SeianNode]) -> None:
        """Clear learned protocol routes while retaining direct neighbors."""

        for node in nodes.values():
            node.routing_table.clear()
            node.route_candidates.clear()
            node.gateway_distance = 0 if node.gateway_capable and node.gateway_online else None

    def advertisements_for(
        self,
        node: SeianNode,
        nodes: dict[str, SeianNode],
    ) -> list[RouteAdvertisement]:
        """Build the node's self-route and selected learned-route advertisements."""

        if not node.communication_available:
            return []
        advertisements = [
            RouteAdvertisement(
                destination_id=node.node_id,
                destination_sequence=node._route_sequence,
                hop_count=0,
                route_cost=0.0,
                lifetime_s=self.route_lifetime_s,
                advertised_next_hop=None,
                gateway_path=node.gateway_capable and node.gateway_online,
                electrical_risk=electrical_risk_score(
                    power_health=node.power_health,
                    power_load_percent=node.load_percent,
                    power_fault_status=node.power_fault_status,
                    weights=self.weights,
                ),
                communication_health=max(0.0, min(1.0, node.communication_health)),
                communication_congestion=max(
                    0.0,
                    min(1.0, max(node.communication_load, node.communication_congestion)),
                ),
                communication_fault_status=node.communication_fault_status.value,
            )
        ]
        for destination_id, route in sorted(node.routing_table.items()):
            destination = nodes.get(destination_id)
            advertisements.append(
                RouteAdvertisement(
                    destination_id=destination_id,
                    destination_sequence=route.destination_sequence,
                    hop_count=route.hop_count,
                    route_cost=route.route_cost,
                    lifetime_s=max(0.001, route.route_lifetime - route.last_update_time),
                    advertised_next_hop=route.next_hop_id,
                    gateway_path=bool(
                        destination
                        and destination.gateway_capable
                        and destination.gateway_online
                    ),
                    electrical_risk=electrical_risk_score(
                        power_health=node.power_health,
                        power_load_percent=node.load_percent,
                        power_fault_status=node.power_fault_status,
                        weights=self.weights,
                    ),
                    communication_health=max(0.0, min(1.0, node.communication_health)),
                    communication_congestion=max(
                        0.0,
                        min(1.0, max(node.communication_load, node.communication_congestion)),
                    ),
                    communication_fault_status=node.communication_fault_status.value,
                )
            )
        return advertisements

    def process_advertisement(
        self,
        receiver: SeianNode,
        sender: SeianNode,
        advertisement: RouteAdvertisement,
        timestamp: float,
    ) -> RouteUpdateResult:
        """Evaluate one neighbor advertisement and update receiver-owned state."""

        neighbor = receiver.neighbor_table.get(sender.node_id)
        if neighbor is None or not sender.communication_available:
            return RouteUpdateResult(False, False, "sender_not_neighbor")
        if advertisement.destination_id == receiver.node_id:
            return RouteUpdateResult(False, False, "own_destination")
        if advertisement.advertised_next_hop == receiver.node_id:
            return RouteUpdateResult(False, False, "split_horizon")
        candidate_hops = advertisement.hop_count + 1
        if candidate_hops > self.max_hops:
            return RouteUpdateResult(False, False, "max_hops")

        destination_id = advertisement.destination_id
        candidates = receiver.route_candidates.setdefault(destination_id, {})
        known_sequences = [
            candidate.destination_sequence for candidate in candidates.values()
        ]
        current = receiver.routing_table.get(destination_id)
        if current is not None:
            known_sequences.append(current.destination_sequence)
        if known_sequences and advertisement.destination_sequence < max(known_sequences):
            return RouteUpdateResult(False, False, "stale_sequence")

        edge_cost = advertised_route_cost(
            hop_count=1,
            link_quality=min(neighbor.link_quality, neighbor.link_reliability),
            communication_health=advertisement.communication_health,
            communication_congestion=advertisement.communication_congestion,
            communication_fault_status=CommunicationFaultStatus(
                advertisement.communication_fault_status
            ),
            electrical_risk=advertisement.electrical_risk,
            leads_to_gateway=advertisement.gateway_path,
            weights=self.weights,
        )
        old_signature = self._selected_signature(receiver, destination_id)
        candidates[sender.node_id] = RoutingEntry(
            destination_id=destination_id,
            next_hop_id=sender.node_id,
            hop_count=candidate_hops,
            route_cost=edge_cost + advertisement.route_cost,
            route_lifetime=timestamp + min(
                advertisement.lifetime_s,
                self.route_lifetime_s,
            ),
            backup_next_hop=None,
            supports_emergency=True,
            last_update_time=timestamp,
            destination_sequence=advertisement.destination_sequence,
            learned_from=sender.node_id,
        )
        self._select_route(receiver, destination_id, timestamp)
        new_signature = self._selected_signature(receiver, destination_id)
        return RouteUpdateResult(True, old_signature != new_signature, "accepted")

    def expire_routes(self, node: SeianNode, timestamp: float) -> list[str]:
        """Expire stale candidates and return destinations whose selected route changed."""

        changed_destinations: list[str] = []
        for destination_id in list(node.route_candidates):
            old_signature = self._selected_signature(node, destination_id)
            candidates = node.route_candidates[destination_id]
            for next_hop_id, candidate in list(candidates.items()):
                if candidate.route_lifetime < timestamp or next_hop_id not in node.neighbor_table:
                    del candidates[next_hop_id]
            if not candidates:
                del node.route_candidates[destination_id]
            self._select_route(node, destination_id, timestamp)
            if old_signature != self._selected_signature(node, destination_id):
                changed_destinations.append(destination_id)
        return changed_destinations

    def invalidate_next_hop(
        self,
        node: SeianNode,
        failed_next_hop: str,
        timestamp: float,
    ) -> list[str]:
        """Remove candidates learned through a failed neighbor."""

        changed_destinations: list[str] = []
        for destination_id, candidates in list(node.route_candidates.items()):
            old_signature = self._selected_signature(node, destination_id)
            candidates.pop(failed_next_hop, None)
            if not candidates:
                del node.route_candidates[destination_id]
            self._select_route(node, destination_id, timestamp)
            if old_signature != self._selected_signature(node, destination_id):
                changed_destinations.append(destination_id)
        return changed_destinations

    def invalidate_destination_from_next_hop(
        self,
        node: SeianNode,
        destination_id: str,
        next_hop_id: str,
        timestamp: float,
    ) -> bool:
        """Invalidate one advertised candidate and report selected-route change."""

        old_signature = self._selected_signature(node, destination_id)
        candidates = node.route_candidates.get(destination_id)
        if candidates is None or next_hop_id not in candidates:
            return False
        del candidates[next_hop_id]
        if not candidates:
            del node.route_candidates[destination_id]
        self._select_route(node, destination_id, timestamp)
        return old_signature != self._selected_signature(node, destination_id)

    def _select_route(self, node: SeianNode, destination_id: str, timestamp: float) -> None:
        candidates = [
            candidate
            for candidate in node.route_candidates.get(destination_id, {}).values()
            if candidate.route_lifetime >= timestamp
            and candidate.next_hop_id in node.neighbor_table
        ]
        if not candidates:
            node.routing_table.pop(destination_id, None)
            return
        newest_sequence = max(candidate.destination_sequence for candidate in candidates)
        candidates = [
            candidate
            for candidate in candidates
            if candidate.destination_sequence == newest_sequence
        ]
        candidates.sort(
            key=lambda candidate: (
                candidate.route_cost,
                candidate.hop_count,
                candidate.next_hop_id,
            )
        )
        current = node.routing_table.get(destination_id)
        current_candidate = next(
            (
                candidate
                for candidate in candidates
                if current and candidate.next_hop_id == current.next_hop_id
            ),
            None,
        )
        selected = candidates[0]
        if (
            current_candidate is not None
            and selected.next_hop_id != current_candidate.next_hop_id
            and selected.route_cost + self.switch_hysteresis >= current_candidate.route_cost
        ):
            selected = current_candidate
        backup = next(
            (
                candidate.next_hop_id
                for candidate in candidates
                if candidate.next_hop_id != selected.next_hop_id
            ),
            None,
        )
        node.routing_table[destination_id] = replace(
            selected,
            backup_next_hop=backup,
        )

    @staticmethod
    def _selected_signature(node: SeianNode, destination_id: str) -> tuple | None:
        route = node.routing_table.get(destination_id)
        if route is None:
            return None
        return (
            route.next_hop_id,
            route.hop_count,
            round(route.route_cost, 9),
            route.destination_sequence,
            route.backup_next_hop,
        )
