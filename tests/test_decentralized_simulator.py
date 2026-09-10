from seian_sim.enums import PacketType
from seian_sim.packets import PRIORITY_TELEMETRY
from seian_sim.simulator import SeianMeshSimulator
from tests.test_discovery import reliable_config


def decentralized_config():
    config = reliable_config()
    config.routing_mode = "decentralized"
    return config


def build_line(count: int) -> SeianMeshSimulator:
    config = decentralized_config()
    config.lora.max_range_m = 110.0
    sim = SeianMeshSimulator(config)
    for index in range(count):
        sim.add_node(
            f"N{index + 1:02d}",
            index * 100.0,
            0.0,
            gateway_capable=index == 0,
            gateway_online=index == 0,
        )
    return sim


def test_packet_advertisements_learn_multihop_route_without_oracle():
    sim = build_line(3)

    def reject_oracle(*args, **kwargs):
        raise AssertionError("NetworkX route installer must not run in decentralized mode")

    sim.routing.recalculate = reject_oracle
    sim.discover_neighbors()

    route = sim.nodes["N03"].routing_table["N01"]
    assert route.next_hop_id == "N02"
    assert route.hop_count == 2
    assert route.learned_from == "N02"
    assert sim.now > 0.0
    assert sim.metrics.route_advertisements_sent > 0
    assert sim.metrics.route_advertisements_accepted > 0
    assert any(
        event["packet_type"] == PacketType.ROUTE_ADVERTISEMENT.value
        for event in sim.packet_events
    )


def test_data_packet_uses_decentralized_route_after_convergence():
    sim = build_line(3)
    sim.discover_neighbors()
    packet = sim.create_packet(
        sim.nodes["N03"],
        PacketType.GRID_STATE_UPDATE,
        destination_id="N01",
        priority=PRIORITY_TELEMETRY,
        ttl=4,
        payload={"voltage": 230.0},
    )

    assert sim.route_packet("N03", packet)
    sim.process_queues()
    sim.process_queues()

    assert sim.metrics.unicast_packets_delivered == 1


def test_route_error_propagates_across_dependent_line():
    sim = build_line(4)
    sim.discover_neighbors()
    assert sim.nodes["N04"].routing_table["N01"].hop_count == 3

    sim.fail_communication("N02")

    assert "N01" not in sim.nodes["N03"].routing_table
    assert "N01" not in sim.nodes["N04"].routing_table
    assert sim.metrics.route_errors_sent > 0
    assert sim.metrics.route_errors_accepted > 0


def test_diamond_activates_learned_backup_after_relay_failure():
    config = decentralized_config()
    config.lora.max_range_m = 150.0
    sim = SeianMeshSimulator(config)
    sim.add_node("N01", 0, 0, gateway_capable=True, gateway_online=True)
    sim.add_node("N02", 100, 0)
    sim.add_node("N03", 100, 100)
    sim.add_node("N04", 200, 0)
    sim.discover_neighbors()
    before = sim.nodes["N04"].routing_table["N01"]
    failed_next_hop = before.next_hop_id
    backup = before.backup_next_hop

    sim.fail_communication(failed_next_hop)

    after = sim.nodes["N04"].routing_table["N01"]
    assert backup is not None
    assert after.next_hop_id == backup
    assert after.next_hop_id != failed_next_hop
