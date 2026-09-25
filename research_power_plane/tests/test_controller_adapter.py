"""Tests for controller-output conversion, PSCAD bindings, and channel parsing."""

from __future__ import annotations

import pytest
import json
from pathlib import Path

from seian_sim.enums import FaultDomain, FaultType
from seian_sim.fault_model import create_fault
from seian_sim.node import SeianNode
from seian_sim.scenarios import build_from_topology

from seian_power_pipeline.control_plane import ControlAction, control_commands_from_payload
from seian_power_pipeline.controller_adapter import (
    commands_from_controller_payload,
    commands_from_fault_events,
)
from seian_power_pipeline.pscad_adapter import PscadLineBinding
from seian_power_pipeline.pipeline import run_control_pipeline


class TestControllerAdapter:
    def test_native_command_payload_passes_through_untouched(self):
        payload = {"commands": [{"command_id": "c1", "action": "open_line", "target_line_id": "SW_A_B"}]}
        assert commands_from_controller_payload(payload) is payload

    def test_fault_event_becomes_isolate_command(self):
        payload = {
            "fault_events": [
                {
                    "fault_id": "F-1",
                    "origin_node": "N03",
                    "fault_type": "short_circuit_suspected",
                    "severity": "critical",
                    "start_time": 12.5,
                    "affected_nodes": {"N03", "N04"},
                    "recommended_action": "isolate the node",
                }
            ]
        }
        result = commands_from_controller_payload(payload)
        assert len(result["commands"]) == 1

        command = result["commands"][0]
        assert command["action"] == "isolate_node"
        assert command["target_node_id"] == "N03"
        assert command["timestamp"] == 12.5
        assert command["metadata"]["fault_id"] == "F-1"
        # A set of affected nodes is sorted so the output is deterministic.
        assert command["metadata"]["affected_nodes"] == ["N03", "N04"]

        # The result must be consumable by the existing command contract.
        parsed = control_commands_from_payload(result)
        assert parsed[0].action is ControlAction.ISOLATE_NODE

    def test_reroute_recommendation_with_path_adds_restoration_command(self):
        rows = [
            {
                "fault_id": "F-2",
                "origin_node": "N03",
                "start_time": 5.0,
                "recommended_action": "reroute via tie switches",
                "restoration_path": ["G01", "N02", "N05", "N06", "N04"],
            }
        ]
        commands = commands_from_fault_events(rows, restoration_delay_s=2.0)
        assert [c["action"] for c in commands] == ["isolate_node", "reroute_power_path"]

        restore = commands[1]
        assert restore["timestamp"] == 7.0
        assert restore["source_node_id"] == "G01"
        assert restore["destination_node_id"] == "N04"
        assert restore["blocked_nodes"] == ["N03"]
        assert control_commands_from_payload({"commands": commands})[1].path[-1] == "N04"

    def test_reroute_without_path_yields_isolation_only(self):
        rows = [{"origin_node": "N03", "recommended_action": "reroute", "start_time": 1.0}]
        commands = commands_from_fault_events(rows)
        assert [c["action"] for c in commands] == ["isolate_node"]

    def test_path_accepts_arrow_delimited_string(self):
        rows = [
            {
                "origin_node": "N03",
                "recommended_action": "restore",
                "restoration_path": "G01 -> N02 -> N05",
            }
        ]
        commands = commands_from_fault_events(rows)
        assert commands[1]["path"] == ["G01", "N02", "N05"]

    def test_key_aliases_and_bare_list_input(self):
        # 'node_id'/'time'/'action' are aliases; a bare list is also accepted.
        commands = commands_from_controller_payload(
            [{"node_id": "N05", "time": 3.0, "action": "isolate"}]
        )["commands"]
        assert commands[0]["target_node_id"] == "N05"
        assert commands[0]["timestamp"] == 3.0

    def test_rows_without_an_origin_node_are_skipped(self):
        assert commands_from_fault_events([{"fault_id": "F-3"}]) == []

    def test_fault_event_object_is_accepted(self):
        class FaultEventLike:
            fault_id = "F-4"
            origin_node = "N02"
            severity = "warning"
            start_time = 8.0
            recommended_action = "monitor"

        commands = commands_from_fault_events([FaultEventLike()])
        assert commands[0]["target_node_id"] == "N02"
        assert commands[0]["metadata"]["fault_id"] == "F-4"

    def test_updated_simulator_fault_domains_do_not_open_power_lines(self):
        communication = {
            "fault_id": "radio-loss",
            "origin_node": "N03",
            "fault_type": "communication_loss",
            "fault_domain": "communication",
            "recommended_action": "reroute via healthy neighbors",
            "restoration_path": ["G01", "N02", "N05"],
            "start_time": 5.0,
        }
        device = {**communication, "fault_id": "overheat", "fault_domain": "device"}
        unknown = {**communication, "fault_id": "unexpected", "fault_domain": "future_domain"}
        assert commands_from_fault_events([communication, device, unknown]) == []

    def test_new_power_fault_requires_switching_recommendation(self):
        advisory = {
            "fault_id": "sag",
            "origin_node": "N03",
            "fault_domain": "power",
            "recommended_action": "request voltage support",
        }
        isolation = {
            **advisory,
            "fault_id": "short",
            "recommended_action": "isolate affected region in the model",
        }
        commands = commands_from_fault_events([advisory, isolation])
        assert len(commands) == 1
        assert commands[0]["metadata"]["fault_domain"] == "power"
        assert commands[0]["target_node_id"] == "N03"

    def test_actual_new_simulator_fault_objects_follow_domain_boundary(self):
        node = SeianNode(node_id="N03", local_address=3, network_id="SEIAN-LAB", position_x=0, position_y=0)
        radio = create_fault(node, FaultType.COMMUNICATION_LOSS, "severe", 5.0, 1.0, 0.0)
        short = create_fault(node, FaultType.SHORT_CIRCUIT_SUSPECTED, "severe", 5.0, 1.0, 0.0)
        assert radio.fault_domain is FaultDomain.COMMUNICATION
        assert short.fault_domain is FaultDomain.POWER
        commands = commands_from_fault_events([radio, short])
        assert len(commands) == 1
        assert commands[0]["target_node_id"] == "N03"

    def test_merged_simulator_faults_generate_only_electrical_switch_events(self):
        source = Path(__file__).resolve().parents[1] / "examples" / "lv_power_plane_microgrid.json"
        topology = json.loads(source.read_text(encoding="utf-8"))
        simulator = build_from_topology(topology)
        simulator.env.run(until=5.0)
        simulator.inject_fault("N03", FaultType.SHORT_CIRCUIT_SUSPECTED, radius_m=1.0)
        simulator.inject_fault("N05", FaultType.COMMUNICATION_LOSS, radius_m=1.0)

        payload = commands_from_controller_payload({"fault_events": simulator.fault_events})
        assert len(payload["commands"]) == 1
        commands = control_commands_from_payload(payload)
        result = run_control_pipeline(
            topology_payload=topology,
            commands=commands,
            simulation_mode="transient",
        )
        assert result.plans[0].accepted
        assert len(result.switching_timeline.events) == 3
        assert result.final_power_plane["analysis"]["deenergized_nodes"] == ["N03", "N04", "N05", "N06"]

    def test_unsupported_payload_type_raises(self):
        with pytest.raises(ValueError):
            commands_from_controller_payload("not a payload")


class TestPscadLineBinding:
    def test_single_parameter_binding_still_works(self):
        binding = PscadLineBinding.from_dict(
            {
                "line_id": "SW_A_B",
                "component_id": 42,
                "closed_parameter": "Value",
                "closed_value": 0,
                "open_value": 1,
            }
        )
        assert binding.parameters_for(True) == {"Value": 0}
        assert binding.parameters_for(False) == {"Value": 1}

    def test_multi_parameter_binding_sets_every_parameter(self):
        binding = PscadLineBinding.from_dict(
            {
                "line_id": "SW_A_B",
                "component_id": 42,
                "closed_parameters": {"BOpen1": 0, "BOpen2": 0, "BOpen3": 0},
                "open_parameters": {"BOpen1": 2, "BOpen2": 2, "BOpen3": 2},
            }
        )
        assert binding.parameters_for(True) == {"BOpen1": 0, "BOpen2": 0, "BOpen3": 0}
        assert binding.parameters_for(False) == {"BOpen1": 2, "BOpen2": 2, "BOpen3": 2}

    def test_returned_parameters_are_copies(self):
        binding = PscadLineBinding.from_dict(
            {
                "line_id": "SW_A_B",
                "component_id": 42,
                "closed_parameters": {"BOpen1": 0},
                "open_parameters": {"BOpen1": 2},
            }
        )
        binding.parameters_for(True)["BOpen1"] = 99
        assert binding.parameters_for(True) == {"BOpen1": 0}
