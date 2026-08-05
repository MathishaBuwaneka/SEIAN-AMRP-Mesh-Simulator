"""Fault injection and distributed boundary classification."""

from __future__ import annotations

import math
import uuid

from seian_sim.enums import FaultStatus, FaultType
from seian_sim.models import FaultEvent
from seian_sim.node import SeianNode


SEVERITY_TTL = {"minor": 2, "moderate": 4, "severe": 8, "emergency": 20}


def recommendation_for_fault(fault_type: FaultType) -> str:
    """Return a simulated corrective recommendation label."""

    return {
        FaultType.VOLTAGE_SAG: "Simulated recommendation: request reactive-power or voltage support.",
        FaultType.VOLTAGE_SURGE: "Simulated recommendation: reduce local voltage support.",
        FaultType.FREQUENCY_DROP: "Simulated recommendation: request nearby active-power support.",
        FaultType.FREQUENCY_RISE: "Simulated recommendation: reduce non-critical generation output.",
        FaultType.PHASE_IMBALANCE: "Simulated recommendation: gradual phase resynchronization.",
        FaultType.OVERLOAD: "Simulated recommendation: non-critical load shedding.",
        FaultType.SHORT_CIRCUIT_SUSPECTED: "Simulated recommendation: isolate affected region in the model.",
        FaultType.ISLANDING_DETECTED: "Simulated recommendation: hold local protection override.",
        FaultType.INVERTER_OVERHEAT: "Simulated recommendation: reduce output due to overtemperature.",
        FaultType.COMMUNICATION_LOSS: "Simulated recommendation: reroute via healthy neighbors.",
    }[fault_type]


def create_fault(
    origin: SeianNode,
    fault_type: FaultType,
    severity: str,
    timestamp: float,
    duration: float,
    radius_m: float,
) -> FaultEvent:
    """Create a fault event with default impact values."""

    impacts = {
        FaultType.VOLTAGE_SAG: (-35.0, -0.02, 1.0, 8.0),
        FaultType.VOLTAGE_SURGE: (30.0, 0.01, 1.0, -5.0),
        FaultType.FREQUENCY_DROP: (-4.0, -0.45, 0.8, 8.0),
        FaultType.FREQUENCY_RISE: (2.0, 0.35, 0.6, -5.0),
        FaultType.PHASE_IMBALANCE: (-8.0, 0.0, 18.0, 4.0),
        FaultType.OVERLOAD: (-16.0, -0.05, 2.0, 35.0),
        FaultType.SHORT_CIRCUIT_SUSPECTED: (-70.0, -0.3, 25.0, 45.0),
        FaultType.ISLANDING_DETECTED: (-12.0, -0.8, 15.0, 10.0),
        FaultType.INVERTER_OVERHEAT: (-4.0, 0.0, 1.0, 25.0),
        FaultType.COMMUNICATION_LOSS: (0.0, 0.0, 0.0, 0.0),
    }[fault_type]
    return FaultEvent(
        fault_id=f"F-{uuid.uuid4().hex[:8]}",
        origin_node=origin.node_id,
        fault_type=fault_type,
        severity=severity,
        start_time=timestamp,
        duration=duration,
        affected_radius_m=radius_m,
        affected_nodes=set(),
        voltage_impact=impacts[0],
        frequency_impact=impacts[1],
        phase_impact=impacts[2],
        load_impact=impacts[3],
        recommended_action=recommendation_for_fault(fault_type),
    )


def apply_fault_to_nodes(fault: FaultEvent, nodes: dict[str, SeianNode]) -> None:
    """Apply simplified fault impacts to nodes inside the affected radius."""

    origin = nodes[fault.origin_node]
    for node in nodes.values():
        distance = math.dist(origin.position, node.position)
        if distance <= fault.affected_radius_m:
            factor = max(0.2, 1.0 - distance / max(1.0, fault.affected_radius_m))
            node.voltage_rms += fault.voltage_impact * factor
            node.frequency_hz += fault.frequency_impact * factor
            node.phase_angle_deg += fault.phase_impact * factor
            node.load_percent = max(0.0, min(130.0, node.load_percent + fault.load_impact * factor))
            node.fault_status = FaultStatus.FAULT if fault.severity in {"severe", "emergency"} else FaultStatus.WARNING
            node.health_score = max(0.15, node.health_score - 0.25 * factor)
            fault.affected_nodes.add(node.node_id)


def classify_fault_boundary(fault: FaultEvent, nodes: dict[str, SeianNode]) -> dict[str, str]:
    """Classify propagated, boundary, and unconfirmed nodes after a fault alert."""

    classifications: dict[str, str] = {}
    affected = fault.affected_nodes
    for node in nodes.values():
        if node.node_id in affected or node.fault_status != FaultStatus.NORMAL:
            label = "FAULT_PROPAGATED"
        elif any(neighbor_id in affected for neighbor_id in node.neighbor_table):
            label = "BOUNDARY_NODE"
        elif node.active:
            label = "UNCONFIRMED"
        else:
            label = "NORMAL"
        node.fault_classification = label
        classifications[node.node_id] = label
    return classifications
