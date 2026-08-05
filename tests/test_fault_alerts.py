from seian_sim.enums import FaultType, PacketType
from seian_sim.scenarios import build_scenario
from tests.test_discovery import reliable_config


def test_emergency_packets_processed_before_telemetry():
    sim = build_scenario("Basic five-node mesh", reliable_config())
    receiver = sim.nodes["N02"]
    telemetry = sim.create_packet(sim.nodes["N01"], PacketType.GRID_STATE_UPDATE, priority=1, ttl=2)
    emergency = sim.create_packet(sim.nodes["N01"], PacketType.FAULT_ALERT, priority=4, ttl=2, payload={"fault_id": "F"})
    receiver.enqueue_packet(telemetry, sim.now, sim.config.queue_limit)
    receiver.enqueue_packet(emergency, sim.now, sim.config.queue_limit)
    first = receiver.dequeue_packet()
    assert first is not None
    assert first.packet.packet_type == PacketType.FAULT_ALERT


def test_fault_alerts_produce_acknowledgements():
    sim = build_scenario("Basic five-node mesh", reliable_config())
    fault = sim.inject_fault("N03", FaultType.VOLTAGE_SAG, severity="severe")
    sim.process_queues()
    assert any(e.packet_type == PacketType.FAULT_ACK.value and e.fault_id == fault.fault_id for e in sim.events)


def test_faulted_and_boundary_nodes_are_classified():
    sim = build_scenario("Voltage-sag propagation", reliable_config())
    labels = {node.fault_classification for node in sim.nodes.values()}
    assert "FAULT_PROPAGATED" in labels
    assert "BOUNDARY_NODE" in labels
