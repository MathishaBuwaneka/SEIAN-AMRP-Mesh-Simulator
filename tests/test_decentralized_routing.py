from seian_sim.decentralized_routing import DecentralizedRoutingEngine
from seian_sim.enums import FaultStatus
from seian_sim.route_messages import RouteAdvertisement
from seian_sim.simulator import SeianMeshSimulator
from tests.test_discovery import reliable_config


def build_engine(sim: SeianMeshSimulator) -> DecentralizedRoutingEngine:
    return DecentralizedRoutingEngine(
        sim.config.routing_weights,
        sim.config.route_lifetime_s,
        sim.config.max_hops,
        sim.config.route_switch_hysteresis,
    )


def advertise_self(
    engine: DecentralizedRoutingEngine,
    receiver,
    sender,
    timestamp: float = 0.0,
):
    advertisement = engine.advertisements_for(sender, {sender.node_id: sender})[0]
    return engine.process_advertisement(receiver, sender, advertisement, timestamp)


def test_three_node_line_learns_two_hop_route_from_advertisement():
    config = reliable_config()
    config.lora.max_range_m = 110.0
    sim = SeianMeshSimulator(config)
    sim.add_node("N01", 0, 0)
    sim.add_node("N02", 100, 0)
    sim.add_node("N03", 200, 0)
    sim.discover_neighbors()
    engine = build_engine(sim)
    engine.reset(sim.nodes)

    advertise_self(engine, sim.nodes["N02"], sim.nodes["N01"])
    advertisement = engine.advertisements_for(sim.nodes["N02"], sim.nodes)[1]
    result = engine.process_advertisement(
        sim.nodes["N03"],
        sim.nodes["N02"],
        advertisement,
        1.0,
    )

    assert result.accepted
    assert result.route_changed
    assert sim.nodes["N03"].routing_table["N01"].next_hop_id == "N02"
    assert sim.nodes["N03"].routing_table["N01"].hop_count == 2


def test_split_horizon_rejects_route_back_to_selected_next_hop():
    sim = SeianMeshSimulator(reliable_config())
    sim.add_node("N01", 0, 0)
    sim.add_node("N02", 100, 0)
    sim.discover_neighbors()
    engine = build_engine(sim)
    advertisement = RouteAdvertisement(
        "N03", 1, 1, 2.0, 60.0, "N01", False, 0.0, 1.0, 0.0, "normal"
    )

    result = engine.process_advertisement(
        sim.nodes["N01"],
        sim.nodes["N02"],
        advertisement,
        0.0,
    )

    assert not result.accepted
    assert result.reason == "split_horizon"


def test_newer_destination_sequence_replaces_lower_cost_stale_route():
    sim = SeianMeshSimulator(reliable_config())
    sim.add_node("N01", 0, 0)
    sim.add_node("N02", 100, 0)
    sim.add_node("N03", 0, 100)
    sim.discover_neighbors()
    engine = build_engine(sim)
    old = RouteAdvertisement("D", 1, 1, 1.0, 60.0, None, False, 0.0, 1.0, 0.0, "normal")
    new = RouteAdvertisement("D", 2, 1, 20.0, 60.0, None, False, 0.0, 1.0, 0.0, "normal")

    engine.process_advertisement(sim.nodes["N01"], sim.nodes["N02"], old, 0.0)
    engine.process_advertisement(sim.nodes["N01"], sim.nodes["N03"], new, 1.0)

    route = sim.nodes["N01"].routing_table["D"]
    assert route.next_hop_id == "N03"
    assert route.destination_sequence == 2


def test_hysteresis_keeps_current_route_for_tiny_improvement():
    config = reliable_config()
    config.route_switch_hysteresis = 0.5
    sim = SeianMeshSimulator(config)
    sim.add_node("N01", 0, 0)
    sim.add_node("N02", 100, 0)
    sim.add_node("N03", 0, 100)
    sim.discover_neighbors()
    engine = build_engine(sim)
    first = RouteAdvertisement("D", 1, 1, 3.0, 60.0, None, False, 0.0, 1.0, 0.0, "normal")
    slightly_better = RouteAdvertisement("D", 1, 1, 2.8, 60.0, None, False, 0.0, 1.0, 0.0, "normal")

    engine.process_advertisement(sim.nodes["N01"], sim.nodes["N02"], first, 0.0)
    engine.process_advertisement(
        sim.nodes["N01"],
        sim.nodes["N03"],
        slightly_better,
        1.0,
    )

    assert sim.nodes["N01"].routing_table["D"].next_hop_id == "N02"
    assert sim.nodes["N01"].routing_table["D"].backup_next_hop == "N03"


def test_expiry_activates_valid_backup_candidate():
    sim = SeianMeshSimulator(reliable_config())
    sim.add_node("N01", 0, 0)
    sim.add_node("N02", 100, 0)
    sim.add_node("N03", 0, 100)
    sim.discover_neighbors()
    engine = build_engine(sim)
    short = RouteAdvertisement("D", 1, 1, 1.0, 1.0, None, False, 0.0, 1.0, 0.0, "normal")
    backup = RouteAdvertisement("D", 1, 1, 5.0, 60.0, None, False, 0.0, 1.0, 0.0, "normal")

    engine.process_advertisement(sim.nodes["N01"], sim.nodes["N02"], short, 0.0)
    engine.process_advertisement(sim.nodes["N01"], sim.nodes["N03"], backup, 0.0)
    changed = engine.expire_routes(sim.nodes["N01"], 2.0)

    assert changed == ["D"]
    assert sim.nodes["N01"].routing_table["D"].next_hop_id == "N03"


def test_electrical_risk_changes_local_candidate_cost():
    sim = SeianMeshSimulator(reliable_config())
    sim.add_node("N01", 0, 0)
    sim.add_node("N02", 100, 0)
    sim.discover_neighbors()
    engine = build_engine(sim)
    healthy = advertise_self(engine, sim.nodes["N01"], sim.nodes["N02"])
    healthy_cost = sim.nodes["N01"].routing_table["N02"].route_cost
    sim.nodes["N02"].health_score = 0.1
    sim.nodes["N02"].fault_status = FaultStatus.FAULT
    sim.recalculate_routes("refresh neighbor electrical state")
    risky = advertise_self(engine, sim.nodes["N01"], sim.nodes["N02"], 1.0)
    risky_cost = sim.nodes["N01"].routing_table["N02"].route_cost

    assert healthy.accepted
    assert risky.accepted
    assert risky_cost > healthy_cost
