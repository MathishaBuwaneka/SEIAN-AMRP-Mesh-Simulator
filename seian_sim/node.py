"""SEIAN inverter node state and packet queue behavior."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any

from seian_sim.enums import (
    CommunicationFaultStatus,
    CommunicationStatus,
    FaultStatus,
    NodeRole,
    TrustStatus,
)
from seian_sim.models import NeighborEntry, RoutingEntry
from seian_sim.packets import DuplicateCache, Packet


@dataclass(order=True, slots=True)
class QueuedPacket:
    """Priority queue item for a packet."""

    sort_key: tuple[int, float, int]
    packet: Packet = field(compare=False)
    enqueued_at: float = field(compare=False)


@dataclass(slots=True)
class SeianNode:
    """One SEIAN smart inverter participating in the adaptive LoRa mesh."""

    node_id: str
    local_address: int
    network_id: str
    position_x: float
    position_y: float
    role: NodeRole = NodeRole.STANDARD
    gateway_capable: bool = False
    gateway_online: bool = False
    active: bool = True
    communication_status: CommunicationStatus = CommunicationStatus.OPERATIONAL
    communication_health: float = 1.0
    communication_fault_status: CommunicationFaultStatus = CommunicationFaultStatus.NORMAL
    communication_load: float = 0.0
    communication_congestion: float = 0.0
    link_reliability: float = 1.0
    power_stage_operational: bool = True
    health_score: float = 1.0
    trust_status: TrustStatus = TrustStatus.TRUSTED
    voltage_rms: float = 230.0
    frequency_hz: float = 50.0
    phase_angle_deg: float = 0.0
    current_a: float = 10.0
    active_power_kw: float = 2.2
    reactive_power_kvar: float = 0.3
    load_percent: float = 40.0
    power_factor: float = 0.96
    thd_percent: float = 3.0
    temperature_c: float = 35.0
    fault_status: FaultStatus = FaultStatus.NORMAL
    neighbor_table: dict[str, NeighborEntry] = field(default_factory=dict)
    routing_table: dict[str, RoutingEntry] = field(default_factory=dict)
    route_candidates: dict[str, dict[str, RoutingEntry]] = field(default_factory=dict)
    recent_packet_cache: DuplicateCache = field(default_factory=DuplicateCache)
    gateway_distance: int | None = None
    fault_classification: str = "NORMAL"
    cached_gateway_telemetry: list[dict[str, Any]] = field(default_factory=list)
    recent_received_packets: list[dict[str, Any]] = field(default_factory=list)
    recent_transmitted_packets: list[dict[str, Any]] = field(default_factory=list)
    packet_drop_reasons: dict[str, int] = field(default_factory=dict)
    _packet_queue: list[QueuedPacket] = field(default_factory=list)
    _queue_limit_hint: int = 1
    _queue_counter: int = 0
    _sequence: int = 0
    _route_sequence: int = 0

    @property
    def position(self) -> tuple[float, float]:
        """Return the node's x/y position."""

        return (self.position_x, self.position_y)

    @property
    def packet_queue(self) -> list[QueuedPacket]:
        """Expose the internal priority queue for inspection."""

        return self._packet_queue

    @property
    def communication_available(self) -> bool:
        """Return whether the CCP radio can currently send and receive."""

        return self.active and self.communication_status != CommunicationStatus.FAILED

    @property
    def power_health(self) -> float:
        """Expose the legacy electrical health field with explicit EP naming."""

        return self.health_score

    @power_health.setter
    def power_health(self, value: float) -> None:
        self.health_score = value

    @property
    def power_fault_status(self) -> FaultStatus:
        """Expose the legacy fault field as electrical-plane state."""

        return self.fault_status

    @power_fault_status.setter
    def power_fault_status(self, value: FaultStatus) -> None:
        self.fault_status = value

    def next_sequence(self) -> int:
        """Return the next local sequence number."""

        self._sequence += 1
        return self._sequence

    def bump_route_sequence(self) -> int:
        """Advance the freshness sequence owned by this destination."""

        self._route_sequence += 1
        return self._route_sequence

    def enqueue_packet(self, packet: Packet, timestamp: float, queue_limit: int) -> bool:
        """Queue a packet, using higher packet priority first."""

        if len(self._packet_queue) >= queue_limit:
            # Evict the oldest packet among the lowest-priority queued items.
            # The previous implementation used max(priority), which could remove
            # emergency traffic instead of background/telemetry traffic.
            lowest_priority = min(item.packet.priority for item in self._packet_queue)
            candidates = [
                item for item in self._packet_queue
                if item.packet.priority == lowest_priority
            ]
            victim = min(candidates, key=lambda item: (item.enqueued_at, item.sort_key[2]))
            if packet.priority > lowest_priority:
                self._packet_queue.remove(victim)
                heapq.heapify(self._packet_queue)
            else:
                self.communication_load = min(1.0, len(self._packet_queue) / max(1, queue_limit))
                return False
        self._queue_limit_hint = max(1, queue_limit)
        self._queue_counter += 1
        key = (-packet.priority, timestamp, self._queue_counter)
        heapq.heappush(self._packet_queue, QueuedPacket(key, packet, timestamp))
        self.communication_load = min(1.0, len(self._packet_queue) / self._queue_limit_hint)
        return True

    def dequeue_packet(self) -> QueuedPacket | None:
        """Return the next packet to transmit."""

        if not self._packet_queue:
            return None
        item = heapq.heappop(self._packet_queue)
        self.communication_load = min(1.0, len(self._packet_queue) / self._queue_limit_hint)
        return item

    def remember_drop(self, reason: str) -> None:
        """Record a node-local packet drop reason."""

        self.packet_drop_reasons[reason] = self.packet_drop_reasons.get(reason, 0) + 1
