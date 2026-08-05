from seian_sim.config import SimulationConfig
from seian_sim.scenarios import build_scenario
from seian_sim.simulator import SeianMeshSimulator
from seian_sim.topology import analyze_topology, trace_route
from tests.test_discovery import reliable_config


def test_trace_route_reaches_gateway():
    sim = build_scenario("Basic five-node mesh", reliable_config())
    path = trace_route(sim, "N05", "N01")
    assert path[0] == "N05"
    assert path[-1] == "N01"
    assert len(path) - 1 <= sim.config.max_hops


def test_disconnected_and_isolated_nodes_are_reported():
    config = SimulationConfig(random_seed=3)
    config.lora.max_range_m = 100.0
    config.lora.packet_loss_probability = 0.0
    config.lora.channel_busy_probability = 0.0
    config.lora.collision_probability = 0.0
    config.lora.shadow_fading_std_db = 0.0
    sim = SeianMeshSimulator(config)
    sim.add_node("N01", 0, 0, gateway_capable=True, gateway_online=True)
    sim.add_node("N02", 50, 0)
    sim.add_node("N03", 500, 0)
    sim.discover_neighbors()

    report = analyze_topology(sim)
    assert report["connected"] is False
    assert report["component_count"] == 2
    assert "N03" in report["isolated_nodes"]
    assert "N03" in report["gateway_unreachable_nodes"]


def test_gateway_outage_is_warning_not_local_mesh_failure():
    sim = build_scenario("Basic five-node mesh", reliable_config())
    sim.set_gateway("N01", False)
    report = analyze_topology(sim)
    codes = {issue["code"] for issue in report["issues"]}
    assert report["connected"] is True
    assert "NO_ONLINE_GATEWAY" in codes
