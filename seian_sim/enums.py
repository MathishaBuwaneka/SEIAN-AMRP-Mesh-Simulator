"""Protocol and grid enumerations."""

from __future__ import annotations

from enum import Enum


class NodeRole(str, Enum):
    """SEIAN inverter node role."""

    STANDARD = "Standard inverter"
    RELAY = "Relay-capable inverter"
    GATEWAY = "Gateway-capable inverter"


class TrustStatus(str, Enum):
    """Lightweight security trust state."""

    TRUSTED = "trusted"
    SUSPICIOUS = "suspicious"
    BLOCKED = "blocked"


class FaultStatus(str, Enum):
    """Current local fault status."""

    NORMAL = "normal"
    WARNING = "warning"
    FAULT = "fault"


class FaultType(str, Enum):
    """Supported simulated grid and communication faults."""

    VOLTAGE_SAG = "voltage_sag"
    VOLTAGE_SURGE = "voltage_surge"
    FREQUENCY_DROP = "frequency_drop"
    FREQUENCY_RISE = "frequency_rise"
    PHASE_IMBALANCE = "phase_imbalance"
    OVERLOAD = "overload"
    SHORT_CIRCUIT_SUSPECTED = "short_circuit_suspected"
    ISLANDING_DETECTED = "islanding_detected"
    INVERTER_OVERHEAT = "inverter_overheat"
    COMMUNICATION_LOSS = "communication_loss"


class PacketType(str, Enum):
    """SEIAN-AMRP packet types."""

    HELLO = "HELLO"
    HELLO_REPLY = "HELLO_REPLY"
    HEARTBEAT = "HEARTBEAT"
    GRID_STATE_UPDATE = "GRID_STATE_UPDATE"
    ROUTE_ADVERTISEMENT = "ROUTE_ADVERTISEMENT"
    FAULT_ALERT = "FAULT_ALERT"
    FAULT_ACK = "FAULT_ACK"
    CONTROL_COORDINATION = "CONTROL_COORDINATION"
    GATEWAY_ANNOUNCE = "GATEWAY_ANNOUNCE"
    ROUTE_ERROR = "ROUTE_ERROR"


class EventCategory(str, Enum):
    """Event-log categories."""

    DISCOVERY = "discovery"
    ROUTING = "routing"
    PACKET = "packet"
    FAULT = "fault"
    GATEWAY = "gateway"
    SECURITY = "security"
    QUEUE = "queue"
    GRID = "grid"
