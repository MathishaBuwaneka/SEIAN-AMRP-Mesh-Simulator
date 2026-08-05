from seian_sim.config import SimulationConfig
from seian_sim.scenarios import build_scenario
from seian_sim.simulator import SeianMeshSimulator


def reliable_config() -> SimulationConfig:
    config = SimulationConfig(random_seed=7)
    config.lora.packet_loss_probability = 0.0
    config.lora.channel_busy_probability = 0.0
    config.lora.collision_probability = 0.0
    config.lora.shadow_fading_std_db = 0.0
    return config


def test_same_network_nodes_discover_each_other():
    sim = build_scenario("Basic five-node mesh", reliable_config())
    assert "N02" in sim.nodes["N01"].neighbor_table
    assert sim.nodes["N05"].routing_table


def test_different_network_nodes_do_not_join():
    sim = SeianMeshSimulator(reliable_config())
    sim.add_node("A", 0, 0, gateway_capable=True, gateway_online=True)
    sim.add_node("B", 50, 0, network_id="OTHER")
    sim.discover_neighbors()
    assert "B" not in sim.nodes["A"].neighbor_table
    assert "A" not in sim.nodes["B"].neighbor_table


def test_neighbor_entries_expire():
    config = reliable_config()
    config.neighbor_timeout_s = 5
    sim = build_scenario("Basic five-node mesh", config)
    sim.env.run(until=6)
    sim.expire_neighbors()
    assert not sim.nodes["N01"].neighbor_table
