from seian_power_pipeline.control_plane import NetworkControlCommand
from seian_power_pipeline.pipeline import run_control_pipeline
from seian_power_pipeline.power_plane import PowerPlaneState
from seian_power_pipeline.pscad_adapter import PscadSwitchingAdapter
from seian_sim.scenarios import build_from_topology


def _topology_payload():
    return {
        "network_id": "TEST",
        "area_width_m": 300,
        "area_height_m": 200,
        "lora_range_m": 260,
        "nodes": [
            {"node_id": "G01", "x": 0, "y": 0, "gateway_capable": True, "gateway_online": True},
            {"node_id": "N02", "x": 50, "y": 0},
            {"node_id": "N03", "x": 100, "y": 0},
            {"node_id": "N04", "x": 150, "y": 0},
            {"node_id": "N05", "x": 75, "y": 75},
            {"node_id": "N06", "x": 150, "y": 75},
        ],
        "power_lines": [
            {"line_id": "SW_G01_N02", "endpoints": ["G01", "N02"], "closed": True},
            {"line_id": "SW_N02_N03", "endpoints": ["N02", "N03"], "closed": True},
            {"line_id": "SW_N03_N04", "endpoints": ["N03", "N04"], "closed": True},
            {"line_id": "SW_N03_N05", "endpoints": ["N03", "N05"], "closed": True},
            {"line_id": "SW_N05_N06", "endpoints": ["N05", "N06"], "closed": True},
            {"line_id": "SW_N02_N05_TIE", "endpoints": ["N02", "N05"], "closed": False, "normally_closed": False},
            {"line_id": "SW_N04_N06_TIE", "endpoints": ["N04", "N06"], "closed": False, "normally_closed": False},
        ],
    }


def _power_plane() -> PowerPlaneState:
    payload = _topology_payload()
    sim = build_from_topology(payload)
    return PowerPlaneState.from_topology_payload(payload, sim)


def test_isolate_fault_and_reroute_restores_energization():
    plane = _power_plane()
    isolate = NetworkControlCommand.from_dict(
        {"command_id": "isolate-n03", "action": "isolate_node", "target_node_id": "N03"}
    )
    reroute = NetworkControlCommand.from_dict(
        {
            "command_id": "reroute-n04",
            "action": "reroute_power_path",
            "source_node_id": "G01",
            "destination_node_id": "N04",
            "blocked_nodes": ["N03"],
            "path": ["G01", "N02", "N05", "N06", "N04"],
        }
    )

    assert plane.apply_command(isolate).accepted
    assert not plane.lines["SW_N02_N03"].closed
    assert not plane.lines["SW_N03_N04"].closed

    assert plane.apply_command(reroute).accepted
    assert plane.lines["SW_N02_N05_TIE"].closed
    assert plane.lines["SW_N04_N06_TIE"].closed
    assert plane.analyze().energized_nodes == ["G01", "N02", "N04", "N05", "N06"]


def test_radial_mode_rejects_closing_a_cycle():
    plane = _power_plane()
    command = NetworkControlCommand.from_dict(
        {"command_id": "close-cycle", "action": "close_line", "target_line_id": "SW_N02_N05_TIE"}
    )

    plan = plane.apply_command(command)

    assert not plan.accepted
    assert plan.operations[0].reason.startswith("rejected")
    assert not plane.lines["SW_N02_N05_TIE"].closed


def test_pscad_manifest_contains_only_accepted_state_changes():
    plane = _power_plane()
    plan = plane.apply_command(
        NetworkControlCommand.from_dict(
            {"command_id": "open-one", "action": "open_line", "target_line_id": "SW_N02_N03"}
        )
    )
    adapter = PscadSwitchingAdapter.from_mapping_payload(
        {
            "project_name": "ResearchCase",
            "line_bindings": [{"line_id": "SW_N02_N03", "component_id": 202, "closed_parameter": "STATE"}],
        }
    )

    manifest = adapter.manifest_for_plans([plan])

    assert manifest["operation_count"] == 1
    assert manifest["calls"][0]["tool"] == "set_component_parameters"
    assert manifest["calls"][0]["arguments"]["component_id"] == 202
    assert manifest["calls"][0]["arguments"]["parameters"] == {"STATE": 0}


def test_pscad_state_snapshot_contains_all_mapped_final_switches():
    plane = _power_plane()
    plans = [
        plane.apply_command(
            NetworkControlCommand.from_dict(
                {"command_id": "open-one", "action": "open_line", "target_line_id": "SW_N02_N03"}
            )
        )
    ]
    adapter = PscadSwitchingAdapter.from_mapping_payload(
        {
            "project_name": "ResearchCase",
            "line_bindings": [
                {"line_id": "SW_G01_N02", "component_id": 101},
                {"line_id": "SW_N02_N03", "component_id": 202},
            ],
        }
    )

    manifest = adapter.manifest_for_state(plane, plans)

    calls_by_component = {call["arguments"]["component_id"]: call for call in manifest["calls"]}
    assert manifest["mode"] == "final_state_snapshot"
    assert manifest["operation_count"] == 2
    assert manifest["changed_operation_count"] == 1
    assert calls_by_component[101]["arguments"]["parameters"] == {"Closed": 1}
    assert calls_by_component[202]["arguments"]["parameters"] == {"Closed": 0}


def test_full_pipeline_builds_manifest_without_running_pscad():
    commands = [
        NetworkControlCommand.from_dict(
            {"command_id": "open-one", "action": "open_line", "target_line_id": "SW_N02_N03"}
        )
    ]
    result = run_control_pipeline(
        topology_payload=_topology_payload(),
        commands=commands,
        pscad_mapping_payload={
            "project_name": "ResearchCase",
            "line_bindings": [{"line_id": "SW_N02_N03", "component_id": 202}],
        },
    )

    payload = result.to_dict()
    assert payload["pscad_manifest"]["operation_count"] == 1
    assert payload["pscad_manifest"]["changed_operation_count"] == 1
    assert payload["pscad_execution"] is None
