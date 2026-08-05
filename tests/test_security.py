from seian_sim.scenarios import build_scenario
from tests.test_discovery import reliable_config


def test_replayed_packets_are_rejected():
    sim = build_scenario("Basic five-node mesh", reliable_config())
    sim.simulate_attack("N02", "replay")
    sim.simulate_attack("N02", "replay")
    assert sim.metrics.duplicate_drops >= 1


def test_invalid_authentication_is_rejected():
    sim = build_scenario("Basic five-node mesh", reliable_config())
    sim.simulate_attack("N02", "invalid_authentication")
    assert sim.metrics.drop_reasons["invalid_authentication"] >= 1
