"""Reference vectors hand-evaluated from SX1276 datasheet section 4.1.1.7.

These constants are independent of the implementation under test. They are
formula reference values, not measurements from physical radios.
"""

from dataclasses import asdict
import random

import pytest

from seian_sim.config import LoraConfig
from seian_sim.enums import PacketType
from seian_sim.lora_airtime import calculate_airtime, receiver_sensitivity_dbm
from seian_sim.lora_channel import LoraChannel
from seian_sim.manual_simulation import ManualPacketSession
from seian_sim.packets import encode_payload
from seian_sim.scenarios import build_from_topology, export_topology
from seian_sim.simulator import SeianMeshSimulator
from tests.test_timing_metrics import deterministic_config


@pytest.mark.parametrize("length,sf,bw,cr,implicit,crc,preamble,expected_ms", [
    (20, 7, 125000, 5, False, True, 8, 56.576),
    (20, 8, 125000, 5, False, True, 8, 102.912),
    (20, 9, 125000, 5, False, True, 8, 185.344),
    (20, 10, 125000, 5, False, True, 8, 370.688),
    (20, 11, 125000, 5, False, True, 8, 741.376),
    (20, 12, 125000, 5, False, True, 8, 1318.912),
    (20, 7, 250000, 5, False, True, 8, 28.288),
    (20, 7, 500000, 5, False, True, 8, 14.144),
    (20, 7, 125000, 8, False, True, 8, 78.080),
    (20, 7, 125000, 5, True, False, 8, 46.336),
    (20, 7, 125000, 5, False, True, 12, 60.672),
    (1, 6, 125000, 5, True, True, 8, 12.928),
    (255, 12, 125000, 5, False, True, 8, 9019.392),
])
def test_datasheet_reference_vectors(length, sf, bw, cr, implicit, crc, preamble, expected_ms):
    config = LoraConfig(spreading_factor=sf, bandwidth_hz=bw, coding_rate_denominator=cr,
                        implicit_header=implicit, crc_enabled=crc, preamble_symbols=preamble)
    assert calculate_airtime(length, config).total_s == pytest.approx(expected_ms / 1000, abs=1e-12)


@pytest.mark.parametrize("sf,bw,expected", [(10, 125000, False), (11, 125000, True),
                                          (11, 250000, False), (12, 250000, True),
                                          (12, 500000, False)])
def test_automatic_ldro_threshold(sf, bw, expected):
    result = calculate_airtime(20, LoraConfig(spreading_factor=sf, bandwidth_hz=bw))
    assert result.low_data_rate_optimization is expected


def test_explicit_ldro_changes_symbol_count():
    assert calculate_airtime(20, LoraConfig(low_data_rate_optimization=True)).total_s == pytest.approx(0.066816)


@pytest.mark.parametrize("length", [-1, 0, 256, True, 20.5])
def test_invalid_phy_lengths_are_rejected(length):
    with pytest.raises(ValueError):
        calculate_airtime(length, LoraConfig())


@pytest.mark.parametrize("settings", [
    {"spreading_factor": 5}, {"spreading_factor": 13}, {"spreading_factor": True},
    {"spreading_factor": 6}, {"bandwidth_hz": 0}, {"coding_rate_denominator": 9},
    {"preamble_symbols": 5}, {"protocol_header_bytes": 255}, {"crc_enabled": 1},
    {"implicit_header": "false"}, {"frequency_hz": float("nan")},
    {"transmission_delay_s": -1}, {"receiver_noise_figure_db": float("inf")},
    {"sensitivity_dbm": float("nan")}, {"low_data_rate_optimization": "auto"},
    {"spreading_factor": 12, "low_data_rate_optimization": False},
])
def test_invalid_radio_profiles_are_rejected(settings):
    with pytest.raises(ValueError):
        LoraConfig(**settings).validate()


def test_airtime_is_nondecreasing_with_length_including_symbol_plateaus():
    values = [calculate_airtime(size, LoraConfig()).total_s for size in range(1, 256)]
    assert values == sorted(values)
    assert values[-1] > values[0]
    assert len(set(values)) < len(values)


def test_sensitivity_tracks_sf_and_bandwidth_and_accepts_override():
    config = LoraConfig(airtime_mode="lora")
    sf7 = receiver_sensitivity_dbm(config)
    assert sf7 == pytest.approx(-124.5308998699)
    config.spreading_factor = 12
    assert receiver_sensitivity_dbm(config) == pytest.approx(sf7 - 12.5)
    config.bandwidth_hz = 250000
    assert receiver_sensitivity_dbm(config) == pytest.approx(sf7 - 12.5 + 3.01029995664)
    config.sensitivity_dbm = -110
    assert receiver_sensitivity_dbm(config) == -110
    assert receiver_sensitivity_dbm(LoraConfig()) == -118


def test_payload_encoding_counts_utf8_bytes_not_characters():
    payload = {"z": "é", "a": 1}
    encoded = encode_payload(payload)
    assert encoded == '{"a":1,"z":"é"}'.encode("utf-8")
    assert len(encoded) > len(encoded.decode("utf-8"))
    assert encode_payload({"a": 1, "z": "é"}) == encoded


def exact_chain():
    config = deterministic_config()
    config.lora.airtime_mode = "lora"
    config.lora.transmission_delay_s = 0.01
    sim = SeianMeshSimulator(config)
    for index in range(3):
        sim.add_node(f"N0{index + 1}", 20 + 100 * index, 50)
    sim.discover_neighbors()
    return sim


@pytest.mark.parametrize("manual", [False, True])
def test_exact_two_hop_latency_and_header_budget(manual):
    sim = exact_chain()
    # 20 UTF-8 bytes + 24 assumed protocol-header bytes = 44 PHY bytes.
    payload = {"x": "a" * 12}
    if manual:
        trace = ManualPacketSession.create(sim, source_id="N01", destination_id="N03",
                                          packet_type=PacketType.GRID_STATE_UPDATE,
                                          priority=1, ttl=6, payload=payload)
        trace.forward_one(sim)
        trace.forward_one(sim)
    else:
        packet = sim.create_packet(sim.nodes["N01"], PacketType.GRID_STATE_UPDATE,
                                   destination_id="N03", payload=payload)
        assert sim.route_packet("N01", packet)
        sim.process_queues()
    assert sim.now == pytest.approx(2 * (0.092416 + 0.01))
    assert sim.metrics.summary()["average_latency_s"] == pytest.approx(sim.now)
    assert sim.metrics.transmission_attempts == 2
    assert sim.metrics.unicast_packets_delivered == 1


@pytest.mark.parametrize("manual", [False, True])
def test_oversize_is_rejected_before_radio_attempt_or_time_advance(manual):
    sim = exact_chain()
    payload = {"x": "a" * 224}  # 232 + 24 = 256 bytes.
    if manual:
        trace = ManualPacketSession.create(sim, source_id="N01", destination_id="N02",
                                          packet_type=PacketType.GRID_STATE_UPDATE,
                                          priority=1, ttl=6, payload=payload)
        trace.forward_one(sim)
    else:
        packet = sim.create_packet(sim.nodes["N01"], PacketType.GRID_STATE_UPDATE,
                                   destination_id="N02", payload=payload)
        assert not sim.route_packet("N01", packet)
    assert sim.metrics.drop_reasons["frame_too_large"] == 1
    assert sim.metrics.transmission_attempts == 0
    assert sim.metrics.unicast_packets_delivered == 0
    assert sim.now == 0


def test_failed_frame_still_consumes_airtime():
    sim = exact_chain()
    sim.config.lora.packet_loss_probability = 1.0
    packet = sim.create_packet(sim.nodes["N01"], PacketType.GRID_STATE_UPDATE,
                               destination_id="N02", payload={"x": "a" * 12})
    assert not sim.route_packet("N01", packet)
    assert sim.now == pytest.approx(0.102416)
    assert sim.metrics.transmission_attempts == 1
    assert sim.metrics.successful_link_transmissions == 0


def test_payload_mutation_cannot_bypass_size_check():
    sim = exact_chain()
    packet = sim.create_packet(sim.nodes["N01"], PacketType.GRID_STATE_UPDATE,
                               destination_id="N02", payload={"x": "a"})
    packet.payload["x"] = "a" * 300
    assert not sim.route_packet("N01", packet)
    assert sim.metrics.transmission_attempts == 0


def test_radio_export_import_and_original_config_isolation():
    sim = exact_chain()
    sim.config.lora.spreading_factor = 12
    sim.config.lora.frequency_hz = 433_000_000
    settings = asdict(sim.config.lora)
    caller = deterministic_config()
    restored = build_from_topology(export_topology(sim), caller)
    assert asdict(restored.config.lora) == settings
    assert caller.lora.airtime_mode == "approximate"
    old_file = export_topology(sim)
    del old_file["lora_config"]
    assert build_from_topology(old_file).config.lora.airtime_mode == "approximate"


def test_discovery_probe_does_not_require_a_payload_and_frame_limit_is_inclusive():
    config = LoraConfig(airtime_mode="lora", protocol_header_bytes=0)
    channel = LoraChannel(config, random.Random(1))
    assert channel.observe((0, 0), (1, 0)).airtime_s == 0
    assert channel.supports_payload(255)
    assert not channel.supports_payload(256)
    with pytest.raises(ValueError):
        channel.airtime_s(256)
