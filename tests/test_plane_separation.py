import pytest

from seian_sim.enums import (
    CommunicationFaultStatus,
    CommunicationStatus,
    FaultDomain,
    FaultStatus,
    FaultType,
    PacketType,
)
from seian_sim.fault_model import apply_fault_to_nodes, create_fault
from seian_sim.manual_simulation import ManualPacketSession
from seian_sim.packets import PRIORITY_FAULT, PRIORITY_TELEMETRY
from seian_sim.scenarios import build_from_topology, export_topology
from seian_sim.simulator import SeianMeshSimulator
from tests.test_discovery import reliable_config


def build_line() -> SeianMeshSimulator:
    config = reliable_config()
    config.lora.max_range_m = 130.0
    sim = SeianMeshSimulator(config)
    sim.add_node("N01", 0, 0, gateway_capable=True, gateway_online=True)
    sim.add_node("N02", 100, 0)
    sim.add_node("N03", 200, 0)
    sim.discover_neighbors()
    return sim


def build_diamond() -> SeianMeshSimulator:
    config = reliable_config()
    config.lora.max_range_m = 150.0
    sim = SeianMeshSimulator(config)
    sim.add_node("N01", 0, 0, gateway_capable=True, gateway_online=True)
    sim.add_node("N02", 100, 0)
    sim.add_node("N03", 100, 100)
    sim.add_node("N04", 200, 0)
    sim.discover_neighbors()
    return sim


def forward_all(session: ManualPacketSession, sim: SeianMeshSimulator) -> None:
    while session.pending_count:
        session.forward_one(sim)


def test_electrical_fault_does_not_disable_relay_communication():
    sim = build_line()
    fault = sim.inject_fault("N02", FaultType.VOLTAGE_SAG, severity="severe", radius_m=1.0)

    assert fault.fault_domain == FaultDomain.POWER
    assert not sim.nodes["N02"].power_stage_operational
    assert sim.nodes["N02"].communication_available
    assert sim.nodes["N03"].routing_table["N01"].next_hop_id == "N02"

    session = ManualPacketSession.create(
        sim,
        source_id="N03",
        destination_id="N01",
        packet_type=PacketType.GRID_STATE_UPDATE,
        priority=PRIORITY_TELEMETRY,
        ttl=4,
        payload={"voltage": 210.0},
    )
    forward_all(session, sim)
    assert "N01" in session.delivered_nodes


def test_communication_failure_removes_relay_and_routes_around_it():
    sim = build_diamond()
    assert sim.nodes["N04"].routing_table["N01"].next_hop_id == "N02"

    sim.fail_communication("N02")

    assert sim.nodes["N02"].power_stage_operational
    assert not sim.nodes["N02"].communication_available
    assert sim.nodes["N04"].routing_table["N01"].next_hop_id == "N03"
    assert any(event.packet_type == PacketType.ROUTE_ERROR.value for event in sim.events)


def test_electrical_fault_penalizes_relay_without_disabling_communication():
    sim = build_diamond()
    sim.recalculate_routes("stabilize gateway preference")
    before = sim.nodes["N04"].routing_table["N01"]

    fault = create_fault(sim.nodes["N02"], FaultType.OVERLOAD, "severe", sim.now, 10, 1)
    apply_fault_to_nodes(fault, sim.nodes)
    sim.recalculate_routes("electrical risk changed")
    after = sim.nodes["N04"].routing_table["N01"]

    assert sim.nodes["N02"].fault_status == FaultStatus.FAULT
    assert sim.nodes["N02"].communication_available
    assert before.next_hop_id == "N02"
    assert after.next_hop_id == "N03"


def test_power_stage_recovery_removes_electrical_route_penalty():
    sim = build_diamond()
    sim.fail_power_stage("N02")
    assert sim.nodes["N04"].routing_table["N01"].next_hop_id == "N03"

    sim.recover_power_stage("N02")

    assert sim.nodes["N02"].communication_available
    assert sim.nodes["N02"].fault_status == FaultStatus.NORMAL
    assert sim.nodes["N04"].routing_table["N01"].next_hop_id == "N02"


def test_neighbor_table_refreshes_electrical_routing_state():
    sim = build_diamond()
    sim.nodes["N02"].health_score = 0.2
    sim.nodes["N02"].load_percent = 120.0
    sim.nodes["N02"].fault_status = FaultStatus.WARNING

    sim.recalculate_routes("neighbor electrical state changed")

    advertised = sim.nodes["N04"].neighbor_table["N02"]
    assert advertised.power_health == pytest.approx(0.2)
    assert advertised.power_load_percent == pytest.approx(120.0)
    assert advertised.power_fault_status == FaultStatus.WARNING


def test_route_edges_apply_risk_to_the_next_hop_direction():
    sim = build_diamond()
    sim.nodes["N02"].health_score = 0.1
    sim.nodes["N02"].fault_status = FaultStatus.FAULT
    sim.recalculate_routes("directional electrical risk")

    graph = sim.routing.build_graph(sim.nodes)

    assert graph.is_directed()
    assert graph["N04"]["N02"]["weight"] > graph["N02"]["N04"]["weight"]


def test_communication_only_baseline_ignores_electrical_risk():
    sim = build_diamond()
    sim.config.routing_weights.cross_plane_risk = 0.0
    sim.fail_power_stage("N02")

    assert sim.nodes["N02"].communication_available
    assert sim.nodes["N04"].routing_table["N01"].next_hop_id == "N02"


def test_communication_degradation_changes_route_selection():
    sim = build_diamond()
    degraded = sim.nodes["N02"]
    degraded.communication_status = CommunicationStatus.DEGRADED
    degraded.communication_health = 0.1
    degraded.communication_congestion = 1.0
    degraded.communication_fault_status = CommunicationFaultStatus.FAULT

    sim.recalculate_routes("communication degradation")

    assert sim.nodes["N04"].routing_table["N01"].next_hop_id == "N03"


def test_fault_types_have_separate_domains():
    sim = build_line()

    power = create_fault(sim.nodes["N02"], FaultType.VOLTAGE_SAG, "severe", sim.now, 10, 1)
    communication = create_fault(sim.nodes["N02"], FaultType.COMMUNICATION_LOSS, "severe", sim.now, 10, 1)
    device = create_fault(sim.nodes["N02"], FaultType.INVERTER_OVERHEAT, "severe", sim.now, 10, 1)

    assert power.fault_domain == FaultDomain.POWER
    assert communication.fault_domain == FaultDomain.COMMUNICATION
    assert device.fault_domain == FaultDomain.DEVICE


def test_grid_state_update_is_transport_only_for_routing():
    sim = build_diamond()
    route_before = sim.nodes["N04"].routing_table["N01"].next_hop_id

    session = ManualPacketSession.create(
        sim,
        source_id="N04",
        destination_id="N01",
        packet_type=PacketType.GRID_STATE_UPDATE,
        priority=PRIORITY_TELEMETRY,
        ttl=4,
        payload={"voltage": 170.0, "frequency": 47.0, "load": 125.0},
    )
    forward_all(session, sim)

    assert sim.nodes["N04"].routing_table["N01"].next_hop_id == route_before == "N02"
    assert "N01" in session.delivered_nodes
    assert session.packet.payload["voltage"] == 170.0


def test_topology_round_trip_preserves_electrical_routing_state():
    sim = build_diamond()
    node = sim.nodes["N02"]
    node.health_score = 0.35
    node.load_percent = 112.0
    node.fault_status = FaultStatus.WARNING
    node.power_stage_operational = False

    restored = build_from_topology(export_topology(sim), sim.config)
    restored_node = restored.nodes["N02"]

    assert restored_node.health_score == pytest.approx(0.35)
    assert restored_node.load_percent == pytest.approx(112.0)
    assert restored_node.fault_status == FaultStatus.WARNING
    assert not restored_node.power_stage_operational


def test_power_fault_alert_propagates_from_failed_power_stage():
    sim = build_line()
    sim.fail_power_stage("N02")

    session = ManualPacketSession.create(
        sim,
        source_id="N02",
        destination_id=None,
        packet_type=PacketType.FAULT_ALERT,
        priority=PRIORITY_FAULT,
        ttl=3,
        payload={
            "fault_id": "F-POWER",
            "fault_type": FaultType.VOLTAGE_SAG.value,
            "fault_domain": FaultDomain.POWER.value,
        },
    )
    forward_all(session, sim)

    assert sim.nodes["N02"].communication_available
    assert {"N01", "N03"}.issubset(session.delivered_nodes)
