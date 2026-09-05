from __future__ import annotations

import pytest

from seian_power_pipeline.faults import physical_faults_from_payload
from seian_power_pipeline.pipeline import run_control_pipeline


def test_physical_fault_parses_aliases_and_phase_flags():
    faults = physical_faults_from_payload(
        {
            "physical_faults": [
                {
                    "fault_id": "FAULT_N03",
                    "origin_node": "N03",
                    "start_time": 4.8,
                    "duration": 0.3,
                    "fault_type": "ABCG",
                    "fault_resistance_ohm": 0.05,
                }
            ]
        },
        known_nodes={"G01", "N03"},
    )

    fault = faults[0]
    assert fault.node_id == "N03"
    assert fault.fault_type == "abc_ground"
    assert fault.end_s == pytest.approx(5.1)
    assert fault.phase_flags == {"A": 1, "B": 1, "C": 1, "G": 1}
    assert fault.to_dict()["end_s"] == pytest.approx(5.1)


def test_physical_faults_are_sorted_by_start_time():
    faults = physical_faults_from_payload(
        [
            {"fault_id": "F2", "node_id": "N03", "start_s": 2, "duration_s": 0.1},
            {"fault_id": "F1", "node_id": "N02", "start_s": 1, "duration_s": 0.1},
        ]
    )
    assert [fault.fault_id for fault in faults] == ["F1", "F2"]


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ({"node_id": "N03", "start_s": 1, "duration_s": 1}, "fault_id"),
        ({"fault_id": "F", "node_id": "BAD", "start_s": 1, "duration_s": 1}, "unknown"),
        ({"fault_id": "F", "node_id": "N03", "start_s": -1, "duration_s": 1}, "non-negative"),
        ({"fault_id": "F", "node_id": "N03", "start_s": 1, "duration_s": 0}, "greater than zero"),
        (
            {"fault_id": "F", "node_id": "N03", "start_s": 1, "duration_s": 1, "fault_type": "magic"},
            "unsupported fault_type",
        ),
    ],
)
def test_invalid_physical_fault_is_rejected(row: dict, message: str):
    with pytest.raises(ValueError, match=message):
        physical_faults_from_payload([row], known_nodes={"N03"})


def test_duplicate_fault_ids_are_rejected():
    row = {"fault_id": "F", "node_id": "N03", "start_s": 1, "duration_s": 0.1}
    with pytest.raises(ValueError, match="Duplicate"):
        physical_faults_from_payload([row, row])


def _topology() -> dict:
    return {
        "network_id": "FAULT-TEST",
        "area_width_m": 100,
        "area_height_m": 100,
        "lora_range_m": 200,
        "nodes": [
            {
                "node_id": "G01",
                "x": 0,
                "y": 0,
                "gateway_capable": True,
                "gateway_online": True,
            },
            {"node_id": "N03", "x": 50, "y": 0},
        ],
        "power_lines": [
            {
                "line_id": "SW_G01_N03",
                "endpoints": ["G01", "N03"],
                "closed": True,
            }
        ],
    }


def _mapping(*, include_fault: bool = True, fault_node: str = "N03") -> dict:
    payload = {
        "project_name": "FaultCase",
        "line_bindings": [
            {
                "line_id": "SW_G01_N03",
                "component_id": 10,
                "timed_control": {
                    "operation_time_parameters": ["TO1", "TO2"],
                    "closed_value": 0,
                    "open_value": 1,
                },
            }
        ],
    }
    if include_fault:
        payload["fault_bindings"] = [
            {
                "fault_id": "FAULT_N03",
                "node_id": fault_node,
                "logic_component_id": 20,
                "fault_component_id": 21,
            }
        ]
    return payload


def _fault_payload() -> dict:
    return {
        "physical_faults": [
            {
                "fault_id": "FAULT_N03",
                "node_id": "N03",
                "start_s": 1.0,
                "duration_s": 1.0,
                "fault_type": "ag",
                "resistance_ohm": 0.02,
            }
        ]
    }


def test_transient_pipeline_schedules_native_fault_and_extends_duration():
    result = run_control_pipeline(
        topology_payload=_topology(),
        commands=[],
        pscad_mapping_payload=_mapping(),
        physical_fault_payload=_fault_payload(),
        simulation_mode="transient",
    ).to_dict()

    assert result["switching_timeline"]["duration_s"] == pytest.approx(3.0)
    assert result["physical_faults"][0]["fault_type"] == "a_ground"
    manifest = result["pscad_manifest"]
    assert manifest["physical_fault_event_count"] == 1
    fault_calls = [
        call for call in manifest["calls"] if call["metadata"].get("domain") == "physical_fault"
    ]
    assert fault_calls[0]["arguments"] == {
        "project_name": "FaultCase",
        "component_id": 20,
        "parameters": {"TF": 1.0, "DF": 1.0},
    }
    assert fault_calls[1]["arguments"]["parameters"] == {
        "RON": 0.02,
        "A": 1,
        "B": 0,
        "C": 0,
        "G": 1,
    }


def test_no_fault_explicitly_disables_mapped_pscad_fault_logic():
    result = run_control_pipeline(
        topology_payload=_topology(),
        commands=[],
        pscad_mapping_payload=_mapping(),
        simulation_mode="transient",
    ).to_dict()

    fault_calls = [
        call
        for call in result["pscad_manifest"]["calls"]
        if call["metadata"].get("domain") == "physical_fault"
    ]
    assert fault_calls[0]["metadata"]["requested_action"] == "disable_fault"
    assert fault_calls[0]["arguments"]["parameters"] == {"TF": 2.0, "DF": 0.05}
    assert fault_calls[1]["arguments"]["parameters"] == {
        "RON": 0.05,
        "A": 1,
        "B": 1,
        "C": 1,
        "G": 1,
    }


def test_physical_fault_requires_transient_mode_and_a_matching_binding():
    with pytest.raises(ValueError, match="require.*transient"):
        run_control_pipeline(
            topology_payload=_topology(),
            commands=[],
            physical_fault_payload=_fault_payload(),
            simulation_mode="steady_state",
        )

    with pytest.raises(ValueError, match="no PSCAD component binding"):
        run_control_pipeline(
            topology_payload=_topology(),
            commands=[],
            pscad_mapping_payload=_mapping(include_fault=False),
            physical_fault_payload=_fault_payload(),
            simulation_mode="transient",
        )


def test_physical_fault_node_must_match_the_wired_pscad_element():
    with pytest.raises(ValueError, match="connected at G01"):
        run_control_pipeline(
            topology_payload=_topology(),
            commands=[],
            pscad_mapping_payload=_mapping(fault_node="G01"),
            physical_fault_payload=_fault_payload(),
            simulation_mode="transient",
        )


def test_duration_override_must_cover_fault_clearance_window():
    with pytest.raises(ValueError, match="too short"):
        run_control_pipeline(
            topology_payload=_topology(),
            commands=[],
            physical_fault_payload=_fault_payload(),
            simulation_mode="transient",
            duration_override_s=2.5,
        )
