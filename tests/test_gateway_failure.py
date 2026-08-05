from seian_sim.enums import FaultType
from seian_sim.scenarios import build_scenario
from tests.test_discovery import reliable_config


def test_mesh_remains_local_after_gateway_failure():
    sim = build_scenario("Basic five-node mesh", reliable_config())
    sim.set_gateway("N01", False)
    sim.inject_fault("N03", FaultType.VOLTAGE_SAG, severity="moderate")
    sim.process_queues()
    assert any(e.category.value == "fault" for e in sim.events)
    assert any(node.cached_gateway_telemetry == [] for node in sim.nodes.values())
    assert any(node.neighbor_table for node in sim.nodes.values() if node.node_id != "N01")
