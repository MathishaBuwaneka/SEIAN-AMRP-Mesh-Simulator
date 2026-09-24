import pytest

from seian_sim.enums import PacketType
from seian_sim.lora_airtime import calculate_airtime
from seian_sim.manual_simulation import ManualPacketSession
from seian_sim.scenarios import build_from_topology, export_topology
from seian_sim.simulator import SeianMeshSimulator
from seian_sim.wire import WireError, decode_frame
from tests.test_timing_metrics import deterministic_config


def binary_chain(routing="decentralized"):
    config = deterministic_config()
    config.packet_encoding = "binary"
    config.routing_mode = routing
    config.lora.airtime_mode = "lora"
    config.lora.transmission_delay_s = 0
    sim = SeianMeshSimulator(config)
    for index in range(3):
        sim.add_node(f"N0{index + 1}", 20 + 100 * index, 50)
    sim.discover_neighbors()
    return sim


@pytest.mark.parametrize("manual", [False, True])
def test_binary_exact_airtime_decentralized_learning_and_two_hop_delivery(manual):
    sim = binary_chain()
    assert sim.nodes["N01"].routing_table["N03"].next_hop_id == "N02"
    assert sim.metrics.route_advertisements_accepted > 0
    control_frames = [event for event in sim.packet_events if event.get("wire_frame_hex")]
    assert control_frames
    assert all(event["wire_frame_bytes"] <= 255 for event in control_frames)
    assert not sim.metrics.drop_reasons["wire_encode_error"]
    before = sim.now
    delivered = sim.metrics.unicast_packets_delivered
    payload = {"voltage": 230.0}
    if manual:
        trace = ManualPacketSession.create(sim, source_id="N01", destination_id="N03",
                                          packet_type=PacketType.GRID_STATE_UPDATE,
                                          priority=1, ttl=6, payload=payload)
        trace.forward_one(sim); trace.forward_one(sim)
        assert trace.complete
        assert decode_frame(bytes.fromhex(trace.last_wire_frame_hex)).source == 2
        assert trace.last_transmitted_packet.payload_length == 11
    else:
        packet = sim.create_packet(sim.nodes["N01"], PacketType.GRID_STATE_UPDATE,
                                   destination_id="N03", payload=payload)
        assert sim.route_packet("N01", packet)
        sim._drain_packet_queues()
    # 24 header + 11-byte voltage field + 2 CRC = 37 bytes, no assumed overhead.
    assert sim.now - before == pytest.approx(2 * calculate_airtime(37, sim.config.lora).total_s)
    assert sim.metrics.unicast_packets_delivered == delivered + 1
    if not manual:
        assert sim.nodes["N03"].recent_received_packets[-1]["from"] == "N02"


@pytest.mark.parametrize("scenario", [
    "test_route_error_propagates_across_dependent_line",
    "test_diamond_activates_learned_backup_after_relay_failure",
    "test_partition_removes_cross_component_routes_but_keeps_local_routes",
    "test_electrical_risk_advertisement_switches_route_without_disabling_ccp",
])
def test_existing_routing_regressions_over_binary_exact_transport(monkeypatch, scenario):
    from tests import test_decentralized_simulator as regression

    original = regression.decentralized_config

    def binary_config():
        config = original()
        config.packet_encoding = "binary"
        config.lora.airtime_mode = "lora"
        return config

    monkeypatch.setattr(regression, "decentralized_config", binary_config)
    getattr(regression, scenario)()


def test_wire_headers_separate_origin_next_hop_and_destination():
    sim = binary_chain("oracle")
    packet = sim.create_packet(sim.nodes["N01"], PacketType.GRID_STATE_UPDATE,
                               destination_id="N03", payload={"voltage": 230.0})
    wire = sim.encode_wire_packet(packet, "N01", "N02")
    decoded = decode_frame(wire)
    assert (decoded.source, decoded.origin, decoded.next_hop, decoded.destination) == (1, 1, 2, 3)
    forwarded = packet.forwarded("N02", sim.now + 1)
    wire2 = sim.encode_wire_packet(forwarded, "N02", "N03")
    decoded2 = decode_frame(wire2)
    assert (decoded2.source, decoded2.origin, decoded2.next_hop, decoded2.destination) == (2, 1, 3, 3)
    restored = sim.decode_wire_packet(wire2, forwarded, "N03")
    assert restored.timestamp == packet.timestamp
    assert restored.hop_count == 1 and restored.ttl == 5
    with pytest.raises(WireError):
        sim.decode_wire_packet(wire2, forwarded, "N01")


def test_address_map_survives_removal_and_topology_roundtrip():
    sim = binary_chain("oracle")
    sim.remove_node("N02")
    assert sim.add_node("custom-node", 100, 50).local_address == 4
    restored = build_from_topology(export_topology(sim))
    assert restored.config.packet_encoding == "binary"
    assert restored.config.wire_addresses == sim.config.wire_addresses
    assert restored.add_node("N02", 120, 50).local_address == 2
    assert restored.add_node("new-node", 125, 50).local_address == 5


@pytest.mark.parametrize("manual", [False, True])
def test_oversized_binary_payload_drops_without_time_or_radio_attempt(manual):
    sim = binary_chain("oracle")
    payload = {"fault_id": "x" * 227}
    before = sim.now
    attempts = sim.metrics.transmission_attempts
    if manual:
        trace = ManualPacketSession.create(sim, source_id="N01", destination_id="N02",
                                          packet_type=PacketType.FAULT_ACK, priority=2, ttl=6, payload=payload)
        trace.forward_one(sim)
    else:
        packet = sim.create_packet(sim.nodes["N01"], PacketType.FAULT_ACK,
                                   destination_id="N02", payload=payload)
        assert not sim.route_packet("N01", packet)
    assert sim.metrics.drop_reasons["wire_encode_error"] == 1
    assert sim.metrics.transmission_attempts == attempts
    assert sim.now == before


def test_binary_failed_radio_counts_attempt_and_consumes_full_frame_airtime():
    sim = binary_chain("oracle")
    sim.config.lora.packet_loss_probability = 1
    packet = sim.create_packet(sim.nodes["N01"], PacketType.GRID_STATE_UPDATE,
                               destination_id="N02", payload={"voltage": 230.0})
    assert not sim.route_packet("N01", packet)
    assert sim.now == pytest.approx(calculate_airtime(37, sim.config.lora).total_s)
    assert sim.metrics.transmission_attempts == 1
    assert sim.metrics.successful_link_transmissions == 0
