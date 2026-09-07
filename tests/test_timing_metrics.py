import pytest

from seian_sim.config import SimulationConfig
from seian_sim.enums import PacketType
from seian_sim.manual_simulation import ManualPacketSession
from seian_sim.packets import PRIORITY_TELEMETRY
from seian_sim.simulator import SeianMeshSimulator


def deterministic_config() -> SimulationConfig:
    config = SimulationConfig(random_seed=17, area_width_m=400, area_height_m=200)
    config.lora.max_range_m = 125.0
    config.lora.packet_loss_probability = 0.0
    config.lora.channel_busy_probability = 0.0
    config.lora.collision_probability = 0.0
    config.lora.interference_probability = 0.0
    config.lora.shadow_fading_std_db = 0.0
    return config


def chain_sim() -> SeianMeshSimulator:
    sim = SeianMeshSimulator(deterministic_config())
    sim.add_node("N01", 20, 50)
    sim.add_node("N02", 120, 50)
    sim.add_node("N03", 220, 50, gateway_capable=True, gateway_online=True)
    sim.discover_neighbors()
    return sim


def create_manual_unicast(sim: SeianMeshSimulator, destination_id: str = "N03") -> ManualPacketSession:
    return ManualPacketSession.create(
        sim,
        source_id="N01",
        destination_id=destination_id,
        packet_type=PacketType.GRID_STATE_UPDATE,
        priority=PRIORITY_TELEMETRY,
        ttl=6,
        payload={"voltage": 230.0},
    )


def expected_link_delay(sim: SeianMeshSimulator, payload_length: int) -> float:
    return (
        sim.config.lora.transmission_delay_s
        + sim.config.lora.airtime_base_s
        + payload_length * 0.0015
    )


def test_forwarding_preserves_packet_creation_time() -> None:
    sim = chain_sim()
    packet = sim.create_packet(
        sim.nodes["N01"],
        PacketType.GRID_STATE_UPDATE,
        destination_id="N03",
    )
    sim.env.run(until=2.0)

    forwarded = packet.forwarded("N02", sim.now)

    assert forwarded.timestamp == packet.timestamp
    assert forwarded.last_forwarded_at == pytest.approx(2.0)


def test_manual_two_hop_latency_uses_both_link_delays() -> None:
    sim = chain_sim()
    session = create_manual_unicast(sim)
    link_delay = expected_link_delay(sim, session.packet.payload_length)

    session.forward_one(sim)
    assert sim.now == pytest.approx(link_delay)
    assert session.last_forwarded_at == pytest.approx(link_delay)

    session.forward_one(sim)
    assert sim.now == pytest.approx(2 * link_delay)
    assert session.last_forwarded_at == pytest.approx(link_delay)

    summary = sim.metrics.summary()
    assert summary["unicast_packets_generated"] == 1
    assert summary["unicast_packets_delivered"] == 1
    assert summary["packet_delivery_ratio"] == pytest.approx(1.0)
    assert summary["average_latency_s"] == pytest.approx(2 * link_delay)


def test_batch_two_hop_latency_uses_both_link_delays() -> None:
    sim = chain_sim()
    packet = sim.create_packet(
        sim.nodes["N01"],
        PacketType.GRID_STATE_UPDATE,
        destination_id="N03",
        priority=PRIORITY_TELEMETRY,
        ttl=6,
        payload={"voltage": 230.0},
    )
    link_delay = expected_link_delay(sim, packet.payload_length)

    assert sim.route_packet("N01", packet)
    sim.process_queues()

    summary = sim.metrics.summary()
    assert sim.now == pytest.approx(2 * link_delay)
    assert summary["unicast_packets_generated"] == 1
    assert summary["unicast_packets_delivered"] == 1
    assert summary["packet_delivery_ratio"] == pytest.approx(1.0)
    assert summary["average_latency_s"] == pytest.approx(2 * link_delay)


def test_failed_radio_delivery_counts_as_attempt_not_success() -> None:
    sim = chain_sim()
    sim.config.lora.packet_loss_probability = 1.0
    session = create_manual_unicast(sim)

    session.forward_one(sim)

    summary = sim.metrics.summary()
    assert summary["transmission_attempts"] == 1
    assert summary["successful_link_transmissions"] == 0
    assert summary["unicast_packets_generated"] == 1
    assert summary["unicast_packets_delivered"] == 0
    assert summary["packet_delivery_ratio"] == pytest.approx(0.0)


def test_pdr_uses_unique_unicast_generation_and_final_delivery() -> None:
    sim = chain_sim()

    for _ in range(3):
        session = create_manual_unicast(sim, destination_id="N02")
        session.forward_one(sim)

    sim.remove_node("N02")
    create_manual_unicast(sim, destination_id="N03")

    summary = sim.metrics.summary()
    assert summary["unicast_packets_generated"] == 4
    assert summary["unicast_packets_delivered"] == 3
    assert summary["packet_delivery_ratio"] == pytest.approx(0.75)
