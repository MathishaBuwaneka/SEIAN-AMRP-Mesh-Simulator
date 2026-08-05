from seian_sim.config import SimulationConfig
from seian_sim.enums import PacketType
from seian_sim.manual_simulation import ManualPacketSession
from seian_sim.packets import PRIORITY_FAULT, PRIORITY_TELEMETRY
from seian_sim.simulator import SeianMeshSimulator


def deterministic_config() -> SimulationConfig:
    config = SimulationConfig(random_seed=7, area_width_m=400, area_height_m=200)
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


def test_unicast_moves_only_when_forward_is_pressed() -> None:
    sim = chain_sim()
    session = ManualPacketSession.create(
        sim,
        source_id="N01",
        destination_id="N03",
        packet_type=PacketType.GRID_STATE_UPDATE,
        priority=PRIORITY_TELEMETRY,
        ttl=6,
        payload={"voltage": 230.0},
    )

    assert session.history == []
    assert session.pending_count == 1
    assert session.pending[0].sender_id == "N01"
    assert session.pending[0].receiver_id == "N02"

    first = session.forward_one(sim)
    assert first is not None
    assert first.receiver_id == "N02"
    assert session.pending_count == 1
    assert "N03" not in session.delivered_nodes

    second = session.forward_one(sim)
    assert second is not None
    assert second.receiver_id == "N03"
    assert session.complete
    assert "N03" in session.delivered_nodes


def test_no_route_finishes_without_sending() -> None:
    sim = chain_sim()
    sim.remove_node("N02")
    session = ManualPacketSession.create(
        sim,
        source_id="N01",
        destination_id="N03",
        packet_type=PacketType.GRID_STATE_UPDATE,
        priority=PRIORITY_TELEMETRY,
        ttl=6,
    )
    assert session.complete
    assert session.pending_count == 0
    assert session.history[-1].status == "NO_ROUTE"


def test_fault_alert_uses_controlled_flooding() -> None:
    sim = chain_sim()
    session = ManualPacketSession.create(
        sim,
        source_id="N01",
        destination_id=None,
        packet_type=PacketType.FAULT_ALERT,
        priority=PRIORITY_FAULT,
        ttl=4,
        payload={"fault_id": "F-1"},
        generate_fault_acks=False,
    )

    safety = 0
    while session.pending and safety < 20:
        session.forward_one(sim)
        safety += 1

    assert session.complete
    assert {"N02", "N03"}.issubset(session.delivered_nodes)
    assert any(row.status == "DUPLICATE" for row in session.history) is False


def test_ttl_stops_before_third_node() -> None:
    sim = chain_sim()
    session = ManualPacketSession.create(
        sim,
        source_id="N01",
        destination_id="N03",
        packet_type=PacketType.GRID_STATE_UPDATE,
        priority=PRIORITY_TELEMETRY,
        ttl=1,
    )
    session.forward_one(sim)
    assert session.complete
    assert "N02" in session.delivered_nodes
    assert "N03" not in session.delivered_nodes
    assert any(row.status == "TTL_EXPIRED" for row in session.history)
