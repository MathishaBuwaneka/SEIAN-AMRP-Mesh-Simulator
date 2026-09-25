from dataclasses import asdict

import pytest

from seian_sim.enums import PacketType
from seian_sim.lora_airtime import calculate_airtime
from seian_sim.manual_simulation import ManualPacketSession
from seian_sim.scenarios import build_from_topology, export_topology
from seian_sim.simulator import SeianMeshSimulator
from tests.test_timing_metrics import deterministic_config


def config():
    cfg = deterministic_config()
    cfg.packet_encoding = "binary"
    cfg.lora.airtime_mode = "lora"
    cfg.lora.transmission_delay_s = 0
    cfg.radio.mode = "event"
    cfg.radio.carrier_sense = False
    cfg.radio.max_retries = 0
    cfg.radio.initial_backoff_slots = 0
    return cfg


def sim_line():
    sim = SeianMeshSimulator(config())
    for name, x in [("A", -100), ("R", 0), ("B", 100)]: sim.add_node(name, x, 0)
    sim.discover_neighbors()
    return sim


def packet(sim, source, dest):
    return sim.create_packet(sim.nodes[source], PacketType.GRID_STATE_UPDATE,
                             destination_id=dest, payload={"voltage": 230.0})


def test_shared_batch_clock_and_collision_metrics():
    sim = sim_line()
    assert sim.route_packet("A", packet(sim, "A", "R"))
    assert sim.route_packet("B", packet(sim, "B", "R"))
    assert sim.now == 0
    sim.process_queues()
    assert sim.now == pytest.approx(calculate_airtime(37, sim.config.lora).total_s)
    assert sim.metrics.transmission_attempts == 2
    assert sim.metrics.collisions == 2
    assert sim.metrics.unicast_packets_delivered == 0
    assert sim.event_radio.stats["physical_transmissions"] == 2


def test_multihop_delivery_accumulates_actual_link_completion_times():
    sim = sim_line()
    sim.route_packet("A", packet(sim, "A", "B"))
    sim.process_queues()
    assert sim.metrics.unicast_packets_delivered == 1
    assert sim.metrics.transmission_attempts == 2
    assert sim.now == pytest.approx(2 * calculate_airtime(37, sim.config.lora).total_s)
    assert sim.metrics.summary()["average_latency_s"] == pytest.approx(sim.now)
    assert all(row.get("wire_frame_bytes") == 37 for row in sim.packet_events if row.get("delivered"))


def test_broadcast_counts_one_physical_attempt_and_all_receptions():
    sim = sim_line()
    sim.broadcast("R", packet(sim, "R", None))
    sim.process_queues()
    assert sim.metrics.transmission_attempts == 1
    assert sim.metrics.successful_link_transmissions == 1
    assert sim.event_radio.stats["receptions"] == 2
    assert sim.metrics.packets_delivered == 2


def test_retries_advance_clock_but_do_not_regenerate_application_packet():
    sim = sim_line()
    sim.config.radio.max_retries = 2
    sim.config.lora.packet_loss_probability = 1
    sim.route_packet("A", packet(sim, "A", "R"))
    sim.process_queues()
    assert sim.metrics.unicast_packets_generated == 1
    assert sim.metrics.transmission_attempts == 3
    assert sim.event_radio.stats["retry_exhausted"] == 1
    assert sim.now > 3 * calculate_airtime(37, sim.config.lora).total_s


def test_pending_transmission_can_be_removed_or_cleared():
    sim = sim_line()
    sim.route_packet("A", packet(sim, "A", "R"))
    sim.remove_node("R")
    sim.process_queues()
    assert sim.metrics.unicast_packets_delivered == 0
    sim.route_packet("B", packet(sim, "B", "B"))
    sim.clear_network()
    assert not sim.event_radio.pending
    assert sim.event_radio.records == []


def test_topology_preserves_radio_configuration_and_old_files_still_work():
    sim = sim_line()
    restored = build_from_topology(export_topology(sim))
    assert asdict(restored.config.radio) == asdict(sim.config.radio)
    assert restored.config.lora.airtime_mode == "lora"
    old = export_topology(sim)
    del old["radio_config"]
    assert build_from_topology(old).config.radio.mode == "serialized"


def test_manual_tracer_rejects_shared_radio_mode_explicitly():
    sim = sim_line()
    with pytest.raises(ValueError, match="serialized"):
        ManualPacketSession.create(sim, source_id="A", destination_id="R",
                                   packet_type=PacketType.GRID_STATE_UPDATE, priority=1, ttl=3)


def test_radio_probability_settings_do_not_create_fictitious_collisions():
    cfg = config()
    cfg.lora.collision_probability = 1
    cfg.lora.channel_busy_probability = 1
    sim = SeianMeshSimulator(cfg)
    sim.add_node("A", 0, 0); sim.add_node("R", 50, 0)
    sim.discover_neighbors()
    sim.route_packet("A", packet(sim, "A", "R"))
    sim.process_queues()
    assert sim.metrics.unicast_packets_delivered == 1


def test_binary_decentralized_control_uses_shared_radio_with_reproducible_results():
    def run():
        cfg = config()
        cfg.routing_mode = "decentralized"
        cfg.radio.carrier_sense = True
        cfg.radio.initial_backoff_slots = 32
        cfg.radio.max_backoffs = 30
        sim = SeianMeshSimulator(cfg)
        for name, x in [("A", 0), ("B", 100), ("C", 200)]: sim.add_node(name, x, 0)
        sim.discover_neighbors()
        return sim
    sim = run()
    repeat = run()
    assert sim.event_radio.records == repeat.event_radio.records
    assert sim.metrics.route_advertisements_accepted > 0
    assert "C" in sim.nodes["A"].routing_table
    sim.route_packet("A", packet(sim, "A", "C")); sim.process_queues()
    assert sim.metrics.unicast_packets_delivered == 1
    exported = sim.export_tables_json()
    assert exported["radio_events"]
    assert exported["radio_metrics"]["physical_transmissions"] == sim.metrics.transmission_attempts
