from __future__ import annotations

import pytest

from seian_power_pipeline.control_plane import NetworkControlCommand
from seian_power_pipeline.pipeline import run_control_pipeline


def _topology() -> dict:
    return {
        "network_id": "TIMELINE-TEST",
        "area_width_m": 200,
        "area_height_m": 100,
        "lora_range_m": 300,
        "nodes": [
            {"node_id": "G01", "x": 0, "y": 0, "gateway_capable": True, "gateway_online": True},
            {"node_id": "N02", "x": 50, "y": 0},
            {"node_id": "N03", "x": 100, "y": 0},
            {"node_id": "N05", "x": 75, "y": 50},
        ],
        "power_lines": [
            {"line_id": "SW_G01_N02", "endpoints": ["G01", "N02"], "closed": True},
            {"line_id": "SW_N02_N03", "endpoints": ["N02", "N03"], "closed": True},
            {"line_id": "SW_N03_N05", "endpoints": ["N03", "N05"], "closed": True},
            {
                "line_id": "SW_N02_N05_TIE",
                "endpoints": ["N02", "N05"],
                "closed": False,
                "normally_closed": False,
            },
        ],
    }


def _mapping(line_id: str = "SW_N02_N03") -> dict:
    return {
        "project_name": "TimelineCase",
        "line_bindings": [
            {
                "line_id": line_id,
                "component_id": 42,
                "timed_control": {
                    "initial_state_parameter": "INIT",
                    "operation_count_parameter": "NUMS",
                    "operation_time_parameters": ["TO1", "TO2"],
                    "closed_value": 0,
                    "open_value": 1,
                },
            }
        ],
    }


def _command(command_id: str, action: str, timestamp: float, line_id: str) -> NetworkControlCommand:
    return NetworkControlCommand.from_dict(
        {
            "command_id": command_id,
            "action": action,
            "timestamp": timestamp,
            "target_line_id": line_id,
        }
    )


def test_transient_pipeline_sorts_commands_and_emits_two_native_operations():
    result = run_control_pipeline(
        topology_payload=_topology(),
        # Deliberately out of order: physical replay must follow timestamps.
        commands=[
            _command("reclose", "close_line", 6.0, "SW_N02_N03"),
            _command("trip", "open_line", 5.0, "SW_N02_N03"),
        ],
        pscad_mapping_payload=_mapping(),
        simulation_mode="transient",
    )

    payload = result.to_dict()
    assert [plan["command"]["command_id"] for plan in payload["plans"]] == ["trip", "reclose"]
    assert payload["switching_timeline"]["event_timestamps"] == [5.0, 6.0]
    assert payload["switching_timeline"]["duration_s"] == 7.0

    manifest = payload["pscad_manifest"]
    assert manifest["mode"] == "timed_event_sequence"
    assert manifest["changed_operation_count"] == 2
    assert manifest["project_settings"]["time_duration"] == 7.0
    assert manifest["calls"][0]["arguments"]["parameters"] == {
        "INIT": 0,
        "NUMS": 2,
        "TO1": 5.0,
        "TO2": 6.0,
    }


def test_no_event_uses_an_idle_transition_after_the_run_window():
    result = run_control_pipeline(
        topology_payload=_topology(),
        commands=[],
        pscad_mapping_payload=_mapping(),
        simulation_mode="transient",
    ).to_dict()

    params = result["pscad_manifest"]["calls"][0]["arguments"]["parameters"]
    assert result["switching_timeline"]["duration_s"] == 1.0
    assert result["switching_timeline"]["event_count"] == 0
    assert params == {"INIT": 0, "NUMS": 1, "TO1": 2.0, "TO2": 3.0}


def test_rejected_command_extends_observation_window_but_never_switches():
    result = run_control_pipeline(
        topology_payload=_topology(),
        commands=[_command("bad-close", "close_line", 5.0, "SW_N02_N05_TIE")],
        pscad_mapping_payload=_mapping("SW_N02_N05_TIE"),
        simulation_mode="transient",
    ).to_dict()

    assert not result["plans"][0]["accepted"]
    assert result["switching_timeline"]["event_count"] == 0
    assert result["switching_timeline"]["duration_s"] == 6.0
    params = result["pscad_manifest"]["calls"][0]["arguments"]["parameters"]
    assert params == {"INIT": 1, "NUMS": 1, "TO1": 7.0, "TO2": 8.0}


def test_native_timed_control_rejects_more_than_two_transitions_per_line():
    commands = [
        _command("trip-1", "open_line", 1.0, "SW_N02_N03"),
        _command("close-1", "close_line", 2.0, "SW_N02_N03"),
        _command("trip-2", "open_line", 3.0, "SW_N02_N03"),
    ]
    with pytest.raises(ValueError, match="supports only 2"):
        run_control_pipeline(
            topology_payload=_topology(),
            commands=commands,
            pscad_mapping_payload=_mapping(),
            simulation_mode="transient",
        )


def test_duration_override_must_cover_the_last_command():
    with pytest.raises(ValueError, match="too short"):
        run_control_pipeline(
            topology_payload=_topology(),
            commands=[_command("trip", "open_line", 5.0, "SW_N02_N03")],
            simulation_mode="transient",
            duration_override_s=5.5,
        )


@pytest.mark.parametrize("timestamp", [-1, float("nan"), float("inf")])
def test_invalid_command_timestamp_is_rejected(timestamp: float):
    with pytest.raises(ValueError, match="finite, non-negative"):
        NetworkControlCommand.from_dict(
            {"command_id": "bad-time", "action": "open_line", "timestamp": timestamp}
        )
