"""Replay current network-simulator fault events into the LV power plane.

The two injected events exercise merged communication/power fault domains. A
native PSCAD fault is separately preprogrammed for the EMT experiment; its
timing is not inferred from electrical feedback. ``--execute-pscad`` uses the
project-local MCP path after the other PSCAD experiment runner has finished.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research_power_plane"
for folder in (ROOT, RESEARCH):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from seian_sim.enums import FaultType
from seian_sim.scenarios import build_from_topology
from seian_power_pipeline.control_plane import control_commands_from_payload
from seian_power_pipeline.controller_adapter import commands_from_controller_payload
from seian_power_pipeline.pipeline import pipeline_summary, run_control_pipeline
from seian_power_pipeline.project_config import TIMED_CASE_NAME, TIMED_MAP_FILE, WORKSPACE_FILE


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-pscad", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "pscad_refresh_20260925" / "merged_simulator.json")
    args = parser.parse_args()

    topology = json.loads((RESEARCH / "examples" / "lv_power_plane_microgrid.json").read_text(encoding="utf-8"))
    mapping = json.loads(TIMED_MAP_FILE.read_text(encoding="utf-8"))
    simulator = build_from_topology(topology)
    simulator.env.run(until=5.0)
    power_fault = simulator.inject_fault("N03", FaultType.SHORT_CIRCUIT_SUSPECTED, radius_m=1.0)
    radio_fault = simulator.inject_fault("N05", FaultType.COMMUNICATION_LOSS, radius_m=1.0)
    payload = commands_from_controller_payload({"fault_events": simulator.fault_events})
    commands = control_commands_from_payload(payload)
    if len(commands) != 1 or commands[0].target_node_id != "N03":
        raise RuntimeError("Expected only the N03 power-fault isolation command.")

    physical_fault = {
        "physical_faults": [{
            "fault_id": "FAULT_N03",
            "node_id": "N03",
            "start_s": 4.8,
            "duration_s": 0.4,
            "fault_type": "abc_ground",
            "resistance_ohm": 0.05,
        }]
    }
    result = run_control_pipeline(
        topology_payload=topology,
        commands=commands,
        pscad_mapping_payload=mapping,
        pscad_project_name=TIMED_CASE_NAME,
        execute_in_pscad=args.execute_pscad,
        pscad_workspace_files=[str(WORKSPACE_FILE)],
        pscad_allowed_roots=[str(RESEARCH)],
        pscad_read_outputs=args.execute_pscad,
        simulation_mode="transient",
        physical_fault_payload=physical_fault,
    )
    if len(result.switching_timeline.events) != 3:
        raise RuntimeError("N03 isolation did not produce three breaker events.")
    if args.execute_pscad:
        run = result.pscad_execution
        if not run or run.errors or not run.fresh_output_files:
            raise RuntimeError("PSCAD did not return a successful fresh raw output.")
        archived_output = args.output.parent / "raw" / "merged_simulator.psout"
        archived_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(run.fresh_output_files[0], archived_output)

    artifact = {
        "source": "merged seian_sim.inject_fault events, not a network transport latency measurement",
        "communication_fault": {"fault_id": radio_fault.fault_id, "node_id": radio_fault.origin_node,
                                "domain": radio_fault.fault_domain.value},
        "power_fault": {"fault_id": power_fault.fault_id, "node_id": power_fault.origin_node,
                        "domain": power_fault.fault_domain.value},
        "controller_commands": payload["commands"],
        "preprogrammed_pscad_fault": physical_fault["physical_faults"],
        "archived_psout": str(archived_output) if args.execute_pscad else None,
        "pipeline": result.to_dict(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(pipeline_summary(result))
    print(f"Wrote {args.output}")
    return 1 if result.pscad_execution and result.pscad_execution.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
