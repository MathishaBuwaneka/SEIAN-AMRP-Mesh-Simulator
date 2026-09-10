import pytest

from seian_sim.config import RoutingWeights
from seian_sim.enums import CommunicationFaultStatus, CommunicationStatus, FaultStatus
from seian_sim.routing import electrical_route_penalty
from seian_sim.scenarios import build_scenario
from tests.test_discovery import reliable_config


def test_failed_next_hop_recalculates_route():
    sim = build_scenario("Hotel microgrid", reliable_config())
    before = sim.nodes["N18"].routing_table["N01"].next_hop_id
    sim.fail_node(before)
    assert before not in sim.nodes["N18"].neighbor_table
    assert "N01" in sim.nodes["N18"].routing_table
    assert sim.nodes["N18"].routing_table["N01"].next_hop_id != before


def test_backup_route_is_used_when_available():
    sim = build_scenario("Hotel microgrid", reliable_config())
    route = sim.nodes["N18"].routing_table["N01"]
    assert route.backup_next_hop is not None


def test_communication_unhealthy_route_can_lose_to_healthy_multihop():
    sim = build_scenario("Healthy route versus short unhealthy route", reliable_config())
    sim.nodes["N02"].communication_status = CommunicationStatus.DEGRADED
    sim.nodes["N02"].communication_health = 0.1
    sim.nodes["N02"].communication_congestion = 1.0
    sim.nodes["N02"].communication_fault_status = CommunicationFaultStatus.FAULT
    sim.recalculate_routes("test communication degradation")
    route = sim.nodes["N04"].routing_table["N01"]
    assert route.next_hop_id == "N03"
    assert route.hop_count == 2


def test_grid_aware_scenario_is_driven_by_electrical_not_communication_risk():
    sim = build_scenario("Healthy route versus short unhealthy route", reliable_config())
    risky_relay = sim.nodes["N02"]

    assert risky_relay.communication_status == CommunicationStatus.OPERATIONAL
    assert risky_relay.communication_health == pytest.approx(1.0)
    assert risky_relay.communication_congestion == pytest.approx(0.0)
    assert risky_relay.communication_fault_status == CommunicationFaultStatus.NORMAL
    assert risky_relay.fault_status == FaultStatus.WARNING
    assert sim.nodes["N04"].routing_table["N01"].next_hop_id == "N03"

    sim.recover_power_stage("N02")

    assert sim.nodes["N04"].routing_table["N01"].next_hop_id == "N02"


def test_repeatable_random_seed():
    sim_a = build_scenario("Basic five-node mesh", reliable_config())
    sim_b = build_scenario("Basic five-node mesh", reliable_config())
    sig_a = {nid: sorted(node.neighbor_table) for nid, node in sim_a.nodes.items()}
    sig_b = {nid: sorted(node.neighbor_table) for nid, node in sim_b.nodes.items()}
    assert sig_a == sig_b


def test_electrical_route_penalty_is_weighted_and_bounded():
    weights = RoutingWeights()

    healthy = electrical_route_penalty(
        power_health=1.0,
        power_load_percent=40.0,
        power_fault_status=FaultStatus.NORMAL,
        weights=weights,
    )
    unhealthy = electrical_route_penalty(
        power_health=-1.0,
        power_load_percent=500.0,
        power_fault_status=FaultStatus.FAULT,
        weights=weights,
    )

    assert healthy == pytest.approx(weights.power_load * 0.4)
    assert unhealthy == pytest.approx(
        weights.power_health + weights.power_load + weights.power_fault
    )


def test_cross_plane_weight_can_disable_electrical_penalty_for_baseline():
    weights = RoutingWeights(cross_plane_risk=0.0)

    penalty = electrical_route_penalty(
        power_health=0.0,
        power_load_percent=100.0,
        power_fault_status=FaultStatus.FAULT,
        weights=weights,
    )

    assert penalty == 0.0
