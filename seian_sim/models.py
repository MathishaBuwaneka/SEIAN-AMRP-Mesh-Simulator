"""Dataclasses for node, route, neighbor, fault, and event records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seian_sim.enums import EventCategory, FaultStatus, FaultType, NodeRole, TrustStatus


@dataclass(slots=True)
class NeighborEntry:
    """A node's latest observation of one neighbor."""

    neighbor_id: str
    rssi: float
    snr: float
    last_seen: float
    hop_count: int
    link_quality: float
    neighbor_health_score: float
    neighbor_fault_status: FaultStatus
    neighbor_voltage: float
    neighbor_frequency: float
    neighbor_phase_angle: float
    neighbor_load_percent: float
    gateway_distance: int | None
    route_cost: float
    trust_status: TrustStatus


@dataclass(slots=True)
class RoutingEntry:
    """Selected next hop for a destination."""

    destination_id: str
    next_hop_id: str
    hop_count: int
    route_cost: float
    route_lifetime: float
    backup_next_hop: str | None
    supports_emergency: bool
    last_update_time: float


@dataclass(slots=True)
class EventRecord:
    """Timestamped simulator event."""

    timestamp: float
    category: EventCategory
    message: str
    node_id: str | None = None
    packet_type: str | None = None
    priority: int | None = None
    fault_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FaultEvent:
    """Injected or detected simulated grid fault."""

    fault_id: str
    origin_node: str
    fault_type: FaultType
    severity: str
    start_time: float
    duration: float
    affected_radius_m: float
    affected_nodes: set[str]
    voltage_impact: float
    frequency_impact: float
    phase_impact: float
    load_impact: float
    recommended_action: str


@dataclass(slots=True)
class NodeSnapshot:
    """Historical measurement row for export and plotting."""

    timestamp: float
    node_id: str
    voltage_rms: float
    frequency_hz: float
    phase_angle_deg: float
    current_a: float
    active_power_kw: float
    reactive_power_kvar: float
    load_percent: float
    power_factor: float
    thd_percent: float
    temperature_c: float
    fault_status: FaultStatus


def fault_penalty(status: FaultStatus) -> float:
    """Return the normalized route penalty for a fault status."""

    return {FaultStatus.NORMAL: 0.0, FaultStatus.WARNING: 0.4, FaultStatus.FAULT: 1.0}[status]


def role_for_gateway(gateway_capable: bool) -> NodeRole:
    """Choose the role implied by gateway capability."""

    return NodeRole.GATEWAY if gateway_capable else NodeRole.STANDARD
