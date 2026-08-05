from seian_sim.enums import FaultStatus
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


def test_unhealthy_direct_route_can_lose_to_healthy_multihop():
    sim = build_scenario("Healthy route versus short unhealthy route", reliable_config())
    sim.nodes["N02"].health_score = 0.1
    sim.nodes["N02"].load_percent = 115
    sim.nodes["N02"].fault_status = FaultStatus.FAULT
    sim.recalculate_routes("test direct unhealthy")
    route = sim.nodes["N04"].routing_table["N01"]
    assert route.next_hop_id == "N03"
    assert route.hop_count == 2


def test_repeatable_random_seed():
    sim_a = build_scenario("Basic five-node mesh", reliable_config())
    sim_b = build_scenario("Basic five-node mesh", reliable_config())
    sig_a = {nid: sorted(node.neighbor_table) for nid, node in sim_a.nodes.items()}
    sig_b = {nid: sorted(node.neighbor_table) for nid, node in sim_b.nodes.items()}
    assert sig_a == sig_b
