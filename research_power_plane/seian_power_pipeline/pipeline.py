"""End-to-end SEIAN control-plane to PSCAD simulation pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from seian_sim.scenarios import build_from_topology

from seian_power_pipeline.control_plane import NetworkControlCommand, chronological_commands
from seian_power_pipeline.power_plane import PowerPlaneState, SwitchingPlan
from seian_power_pipeline.pscad_adapter import PscadSwitchingAdapter
from seian_power_pipeline.pscad_mcp_client import (
    PscadExecutionResult,
    PscadRuntimeConfig,
    execute_pscad_manifest,
)
from seian_power_pipeline.timeline import SwitchingTimeline, build_switching_timeline


@dataclass(slots=True)
class PipelineResult:
    """Complete artifact from one co-simulation pipeline replay."""

    topology: dict[str, Any]
    plans: list[SwitchingPlan]
    final_power_plane: dict[str, Any]
    switching_timeline: SwitchingTimeline | None = None
    pscad_manifest: dict[str, Any] | None = None
    pscad_execution: PscadExecutionResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "topology": self.topology,
            "plans": [plan.to_dict() for plan in self.plans],
            "final_power_plane": self.final_power_plane,
            "switching_timeline": self.switching_timeline.to_dict() if self.switching_timeline else None,
            "pscad_manifest": self.pscad_manifest,
            "pscad_execution": self.pscad_execution.to_dict() if self.pscad_execution else None,
        }


def run_control_pipeline(
    *,
    topology_payload: dict[str, Any],
    commands: list[NetworkControlCommand],
    preserve_radial: bool = True,
    pscad_mapping_payload: dict[str, Any] | None = None,
    pscad_project_name: str | None = None,
    execute_in_pscad: bool = False,
    pscad_workspace_files: list[str] | None = None,
    pscad_allowed_roots: list[str] | None = None,
    pscad_poll_s: float = 120.0,
    pscad_read_outputs: bool = False,
    simulation_mode: str = "steady_state",
    post_event_window_s: float = 1.0,
    duration_override_s: float | None = None,
) -> PipelineResult:
    """Replay controller commands and optionally run the PSCAD case."""

    simulator = build_from_topology(topology_payload)
    power_plane = PowerPlaneState.from_topology_payload(
        topology_payload,
        simulator,
        preserve_radial=preserve_radial,
    )
    ordered_commands = chronological_commands(commands)
    plans = [power_plane.apply_command(command) for command in ordered_commands]
    final_power_plane = power_plane.to_dict()
    topology = {
        "network_id": topology_payload.get("network_id", simulator.config.network_id),
        "node_count": len(simulator.nodes),
        "power_line_count": len(power_plane.lines),
        "source_nodes": final_power_plane["source_nodes"],
    }

    normalized_mode = simulation_mode.strip().lower().replace("-", "_")
    if normalized_mode not in {"steady_state", "transient"}:
        raise ValueError("simulation_mode must be 'steady_state' or 'transient'.")

    timeline = None
    if normalized_mode == "transient":
        timeline = build_switching_timeline(
            topology_payload,
            plans,
            post_event_window_s=post_event_window_s,
            duration_override_s=duration_override_s,
        )

    manifest = None
    execution = None
    if pscad_mapping_payload:
        adapter = PscadSwitchingAdapter.from_mapping_payload(
            pscad_mapping_payload,
            project_name=pscad_project_name,
        )
        manifest = (
            adapter.manifest_for_timeline(timeline)
            if timeline is not None
            else adapter.manifest_for_state(power_plane, plans)
        )

    if execute_in_pscad:
        if manifest is None:
            raise ValueError("PSCAD execution requires a component mapping payload.")
        project_name = pscad_project_name or str(manifest.get("project_name", ""))
        execution = execute_pscad_manifest(
            manifest,
            PscadRuntimeConfig(
                project_name=project_name,
                workspace_files=pscad_workspace_files or [],
                allowed_roots=pscad_allowed_roots or [],
                max_poll_s=pscad_poll_s,
                read_outputs=pscad_read_outputs,
            ),
        )

    return PipelineResult(
        topology=topology,
        plans=plans,
        final_power_plane=final_power_plane,
        switching_timeline=timeline,
        pscad_manifest=manifest,
        pscad_execution=execution,
    )


def pipeline_summary(result: PipelineResult | dict[str, Any]) -> str:
    """Human-readable summary for CLI and dashboard status."""

    payload = result.to_dict() if isinstance(result, PipelineResult) else result
    plans = payload["plans"]
    accepted = sum(1 for plan in plans if plan["accepted"])
    operations = sum(len(plan["operations"]) for plan in plans)
    analysis = payload["final_power_plane"]["analysis"]
    lines = [
        f"commands: {len(plans)} ({accepted} accepted)",
        f"switch operations: {operations}",
        f"energized nodes: {len(analysis['energized_nodes'])}",
        f"deenergized nodes: {len(analysis['deenergized_nodes'])}",
        f"closed/open lines: {analysis['closed_line_count']}/{analysis['open_line_count']}",
        f"cycles: {len(analysis['cycles'])}",
    ]
    manifest = payload.get("pscad_manifest")
    if manifest:
        mode = manifest.get("mode")
        changed_count = manifest.get("changed_operation_count")
        if mode == "timed_event_sequence" and changed_count is not None:
            duration = manifest.get("timeline", {}).get("duration_s")
            lines.append(f"PSCAD timed state writes: {manifest['operation_count']} ({changed_count} events)")
            if duration is not None:
                lines.append(f"PSCAD transient duration: {duration:g} s")
        elif mode == "final_state_snapshot" and changed_count is not None:
            lines.append(f"PSCAD state writes: {manifest['operation_count']} ({changed_count} changed by commands)")
        else:
            lines.append(f"PSCAD MCP calls: {manifest['operation_count']}")
        if manifest["missing_line_bindings"]:
            lines.append(f"unmapped PSCAD lines: {', '.join(manifest['missing_line_bindings'])}")
    execution = payload.get("pscad_execution")
    if execution:
        lines.append(f"PSCAD applied operations: {execution['applied_operation_count']}")
        lines.append(f"PSCAD connected: {execution['connected']}")
        if execution["errors"]:
            lines.append(f"PSCAD errors: {'; '.join(execution['errors'])}")
    return "\n".join(lines)


def dict_without_none(value: dict[str, Any]) -> dict[str, Any]:
    """Small helper for compact exported artifacts."""

    return {key: item for key, item in value.items() if item is not None}
