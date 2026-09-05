"""Graphical edits preserve the controller contract and PSCAD parameter maps."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from dashboard_ui.models import (
    remove_command, state_at, update_binding, update_command, update_fault, update_switch,
)
from dashboard_ui.figures import feeder_figure, timeline_figure
from seian_power_pipeline.control_plane import control_commands_from_payload
from seian_power_pipeline.pipeline import run_control_pipeline

HERE = Path(__file__).resolve().parents[1]


@pytest.fixture
def topology():
    return json.loads((HERE / "examples/lv_power_plane_microgrid.json").read_text())


@pytest.fixture
def scenario():
    return json.loads((HERE / "examples/scenarios/06_physical_fault_restoration.json").read_text())


@pytest.fixture
def mapping():
    return json.loads((HERE / "pscad_workspace/seian_pscad_timed_component_map.generated.json").read_text())


def test_edit_command_preserves_unknown_fields_and_experiment_metadata(scenario):
    scenario["commands"][1]["colleague_extension"] = {"version": 4}
    before = deepcopy(scenario)
    updated = update_command(scenario, 1, {"timestamp": 6.5})
    assert scenario == before
    expected = deepcopy(before)
    expected["commands"][1]["timestamp"] = 6.5
    assert updated == expected


def test_switching_action_clears_old_behavior_but_keeps_metadata(scenario):
    updated = update_command(scenario, 1, {"action": "open_line", "target_line_id": "SW_G01_N02"})
    row = updated["commands"][1]
    assert "path" not in row and "close_lines" not in row and "blocked_nodes" not in row
    assert row["metadata"] == scenario["commands"][1]["metadata"]


def test_add_remove_and_edit_preserve_bare_command_list(scenario):
    rows = scenario["commands"]
    changed = update_command(rows, None, {"command_id": "extra", "action": "open_line", "target_line_id": "SW_G01_N02"})
    assert isinstance(changed, list) and len(changed) == 3
    assert remove_command(changed, 2) == rows


@pytest.mark.parametrize("changes", [{"timestamp": -1}, {"command_id": ""}, {"command_id": "physical-fault-isolate-n03"}])
def test_invalid_command_edits_are_rejected(scenario, changes):
    with pytest.raises(ValueError):
        update_command(scenario, 1, changes)


def test_fault_enable_disable_preserves_commands_and_other_fault_fields(scenario):
    scenario["physical_faults"][0]["calibration"] = "pending"
    changed = update_fault(scenario, "FAULT_N03", {"start_s": 4.7})
    assert changed["physical_faults"][0]["calibration"] == "pending"
    assert changed["commands"] == scenario["commands"]
    disabled = update_fault(changed, "FAULT_N03", None)
    assert disabled["physical_faults"] == []
    assert disabled["scenario"] == scenario["scenario"]
    with pytest.raises(ValueError):
        update_fault(scenario, "FAULT_N03", {"duration_s": 0})


def test_initial_switch_edit_preserves_wiring_and_other_parameters(topology):
    changed = update_switch(topology, "SW_N02_N03", closed=False, normally_closed=True)
    expected = deepcopy(topology)
    expected["power_lines"][1]["closed"] = False
    assert changed == expected and topology["power_lines"][1]["closed"] is True


def test_mapping_edits_preserve_native_timing_contract(mapping):
    changed = update_binding(mapping, "line_bindings", "SW_G01_N02", {"component_id": 123})
    expected = deepcopy(mapping)
    expected["line_bindings"][0]["component_id"] = 123
    assert changed == expected
    with pytest.raises(ValueError):
        update_binding(mapping, "line_bindings", "SW_G01_N02", {"component_id": 0})


def test_preview_reuses_accepted_timeline_and_physical_fault_window(topology, scenario):
    preview = run_control_pipeline(
        topology_payload=topology, commands=control_commands_from_payload(scenario),
        simulation_mode="transient", physical_fault_payload=scenario,
    ).to_dict()
    assert preview["pscad_execution"] is None
    initial = state_at(topology, preview, None)
    assert len(initial["connected"]) == 6 and not initial["faults"]
    during = state_at(topology, preview, 4.9)
    assert during["faults"] == {"N03"}
    isolated = state_at(topology, preview, 5.1)
    assert isolated["connected"] == {"G01", "N02"}
    restored = state_at(topology, preview, 6.1)
    assert restored["connected"] == {"G01", "N02", "N04", "N05", "N06"}
    assert not restored["faults"]
    assert len(feeder_figure(topology, restored).data) >= 20
    assert timeline_figure(topology, preview).layout.xaxis.range == (0, 7)


def test_preview_does_not_apply_rejected_loop_closure(topology):
    preview = run_control_pipeline(
        topology_payload=topology, commands=control_commands_from_payload([
            {"action": "close_line", "target_line_id": "SW_N02_N05_TIE", "timestamp": 1}
        ]), simulation_mode="transient",
    ).to_dict()
    assert not preview["plans"][0]["accepted"]
    assert not state_at(topology, preview, 2)["closed"]["SW_N02_N05_TIE"]
