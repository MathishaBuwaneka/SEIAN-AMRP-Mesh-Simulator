from seian_sim.enums import PacketType
from seian_sim.packets import PRIORITY_TELEMETRY
from seian_sim.scenarios import build_scenario
from tests.test_discovery import reliable_config


def test_duplicate_packets_are_suppressed():
    sim = build_scenario("Basic five-node mesh", reliable_config())
    source = sim.nodes["N01"]
    packet = sim.create_packet(source, PacketType.GRID_STATE_UPDATE, priority=PRIORITY_TELEMETRY, ttl=3, payload={"x": 1})
    sim._deliver("N01", "N02", packet)
    sim._deliver("N01", "N02", packet)
    sim.process_queues()
    assert sim.metrics.duplicate_drops >= 1


def test_ttl_prevents_indefinite_flooding():
    sim = build_scenario("Basic five-node mesh", reliable_config())
    source = sim.nodes["N01"]
    packet = sim.create_packet(source, PacketType.FAULT_ALERT, priority=3, ttl=1, payload={"fault_id": "F"})
    sim.broadcast("N01", packet)
    sim.process_queues()
    forwarded = [e for e in sim.packet_events if e["origin_id"] == "N01" and e["packet_type"] == "FAULT_ALERT"]
    assert len(forwarded) <= len(sim.nodes["N01"].neighbor_table)
