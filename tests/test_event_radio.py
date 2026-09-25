from dataclasses import replace
import random

import pytest

from seian_sim.config import LoraConfig, RadioConfig
from seian_sim.event_radio import EventRadio
from seian_sim.lora_airtime import calculate_airtime


def setup(settings=None, positions=None, profile=None):
    cfg = profile or LoraConfig(airtime_mode="lora", shadow_fading_std_db=0,
        packet_loss_probability=0, interference_probability=0, transmission_delay_s=0,
        max_range_m=1000)
    pos = positions or {"A": (-100, 0), "B": (100, 0), "R": (0, 0)}
    active = set(pos)
    radio = EventRadio(settings or RadioConfig(mode="event", carrier_sense=False, max_retries=0),
                       random.Random(4), pos.__getitem__, active.__contains__)
    results = []
    def send(sender, receiver="R", at=0, selected=None, **kwargs):
        return radio.schedule(sender, [receiver], 20, selected or cfg, at=at,
                              on_result=lambda req, observations: results.append((req.sender, observations)), **kwargs)
    return radio, cfg, send, results, active


def test_equal_power_simultaneous_packets_collide():
    radio, _, send, results, _ = setup()
    send("A"); send("B"); radio.drain()
    assert len(results) == 2
    assert all(row[1]["R"].drop_reason == "collision" for row in results)
    assert radio.stats["physical_transmissions"] == 2


def test_nonoverlap_and_touching_boundaries_succeed():
    radio, cfg, send, results, _ = setup()
    send("A"); send("B", at=calculate_airtime(20, cfg).total_s)
    radio.drain()
    assert all(row[1]["R"].delivered for row in results)


def test_near_far_capture_keeps_only_stronger_packet():
    radio, _, send, results, _ = setup(positions={"A": (1, 0), "B": (100, 0), "R": (0, 0)})
    send("A"); send("B"); radio.drain()
    assert dict(results)["A"]["R"].delivered
    assert dict(results)["B"]["R"].drop_reason == "collision"


def test_hidden_nodes_do_not_sense_each_other_but_collide_at_receiver():
    settings = RadioConfig(mode="event", carrier_sense=True, carrier_sense_threshold_dbm=-92, max_retries=0)
    radio, _, send, results, _ = setup(settings)
    send("A"); send("B", at=0.001); radio.drain()
    assert radio.stats["carrier_sense_busy"] == 0
    assert all(row[1]["R"].drop_reason == "collision" for row in results)


def test_visible_busy_channel_backs_off_then_delivers():
    radio, _, send, results, _ = setup(RadioConfig(mode="event", max_retries=0, max_backoffs=20))
    send("A"); send("B", at=0.001); radio.drain()
    assert radio.stats["carrier_sense_busy"] > 0
    assert radio.stats["physical_transmissions"] == 2
    assert all(row[1]["R"].delivered for row in results)


def test_same_time_sensing_has_no_submission_order_advantage():
    for order in [("A", "B"), ("B", "A")]:
        radio, _, send, results, _ = setup(RadioConfig(mode="event", max_retries=0))
        for sender in order: send(sender)
        radio.drain()
        assert radio.stats["carrier_sense_busy"] == 0
        assert all(row[1]["R"].drop_reason == "collision" for row in results)


@pytest.mark.parametrize("different_sf,cross_sf,delivered", [(True, False, True), (True, True, False), (False, False, True)])
def test_frequency_and_spreading_factor_separation(different_sf, cross_sf, delivered):
    radio, cfg, send, results, _ = setup(RadioConfig(mode="event", carrier_sense=False, max_retries=0, cross_sf_interference=cross_sf))
    other = replace(cfg, spreading_factor=8) if different_sf else replace(cfg, frequency_hz=869_000_000)
    send("A"); send("B", selected=other); radio.drain()
    assert all(row[1]["R"].delivered == delivered for row in results)


def test_half_duplex_receiver_cannot_receive_while_transmitting():
    radio, _, send, results, _ = setup()
    send("A", "B"); send("B", "R"); radio.drain()
    assert dict(results)["A"]["B"].drop_reason == "half_duplex"


def test_retries_stop_and_count_real_attempts():
    cfg = LoraConfig(airtime_mode="lora", packet_loss_probability=1, shadow_fading_std_db=0)
    radio, _, send, results, _ = setup(RadioConfig(mode="event", max_retries=2), profile=cfg)
    send("A"); radio.drain()
    assert len(results) == 3
    assert radio.stats["physical_transmissions"] == 3
    assert radio.stats["retries"] == 2
    assert radio.stats["retry_exhausted"] == 1


def test_bounded_backoff_without_a_physical_attempt():
    radio, _, send, results, _ = setup(RadioConfig(mode="event", max_backoffs=0, max_retries=0))
    send("A"); send("B", at=0.001); radio.drain()
    assert radio.stats["physical_transmissions"] == 1
    assert dict(results)["B"]["R"].drop_reason == "backoff_exhausted"


def test_broadcast_is_one_emission_with_multiple_receptions():
    radio, cfg, _, results, _ = setup()
    radio.schedule("A", ["B", "R"], 20, cfg, at=0, retry=False,
                   on_result=lambda req, obs: results.append(obs))
    radio.drain()
    assert radio.stats["physical_transmissions"] == 1
    assert radio.stats["receptions"] == 2
    assert set(results[0]) == {"B", "R"}


def test_transmitter_serialization_priority_and_duty_cycle():
    radio, cfg, send, _, _ = setup(RadioConfig(mode="event", carrier_sense=False, duty_cycle=0.1))
    low = send("A", priority=1)
    high = send("A", priority=4)
    radio.drain()
    starts = [row for row in radio.records if row["event"] == "tx_start"]
    assert [row["transmission_id"] for row in starts] == [high, low]
    assert starts[1]["timestamp"] == pytest.approx(calculate_airtime(20, cfg).total_s / 0.1)


def test_receiver_disappears_during_transmission():
    radio, _, send, results, active = setup()
    send("A"); radio.step(); active.remove("R"); radio.drain()
    assert results[0][1]["R"].drop_reason == "receiver_inactive"


def test_late_interference_damages_in_progress_packet_permanently():
    radio, _, send, results, _ = setup()
    send("A"); send("B", at=0.03); radio.drain()
    assert all(row[1]["R"].drop_reason == "collision" for row in results)


def test_aggregate_interference_can_defeat_individual_capture():
    positions = {"A": (10, 0), "B": (20, 0), "C": (-20, 0), "R": (0, 0)}
    radio, _, send, results, _ = setup(positions=positions)
    send("A"); send("B"); send("C"); radio.drain()
    assert dict(results)["A"]["R"].drop_reason == "collision"


@pytest.mark.parametrize("changes", [{"duty_cycle": 0}, {"max_retries": -1}, {"max_backoffs": True},
                                     {"backoff_slot_s": 0}, {"capture_threshold_db": float("nan")}])
def test_invalid_radio_settings(changes):
    with pytest.raises(ValueError):
        replace(RadioConfig(), **changes).validate()
