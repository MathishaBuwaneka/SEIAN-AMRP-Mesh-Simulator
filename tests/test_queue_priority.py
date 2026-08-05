from seian_sim.enums import PacketType
from seian_sim.packets import PRIORITY_EMERGENCY, PRIORITY_TELEMETRY
from seian_sim.scenarios import build_scenario
from tests.test_discovery import reliable_config


def test_emergency_packet_evicts_telemetry_when_queue_is_full():
    sim = build_scenario("Basic five-node mesh", reliable_config())
    node = sim.nodes["N02"]
    telemetry = sim.create_packet(
        sim.nodes["N01"], PacketType.GRID_STATE_UPDATE, priority=PRIORITY_TELEMETRY
    )
    emergency = sim.create_packet(
        sim.nodes["N01"], PacketType.FAULT_ALERT, priority=PRIORITY_EMERGENCY
    )

    assert node.enqueue_packet(telemetry, sim.now, queue_limit=1)
    assert node.enqueue_packet(emergency, sim.now, queue_limit=1)
    queued = node.dequeue_packet()
    assert queued is not None
    assert queued.packet.priority == PRIORITY_EMERGENCY
