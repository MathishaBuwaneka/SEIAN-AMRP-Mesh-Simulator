"""Convert SEIAN switch plans into PSCAD MCP operation manifests."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from seian_power_pipeline.power_plane import PowerPlaneState, SwitchingPlan
from seian_power_pipeline.timeline import LineSwitchSchedule, SwitchingTimeline


@dataclass(slots=True)
class PscadTimedControlBinding:
    """Parameter contract for PSCAD's native ``tbreakn`` control component."""

    initial_state_parameter: str = "INIT"
    operation_count_parameter: str = "NUMS"
    operation_time_parameters: tuple[str, ...] = ("TO1", "TO2")
    closed_value: Any = 0
    open_value: Any = 1

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "PscadTimedControlBinding":
        raw_times = row.get("operation_time_parameters", ["TO1", "TO2"])
        if not isinstance(raw_times, list) or not raw_times:
            raise ValueError("timed_control.operation_time_parameters must be a non-empty list.")
        return cls(
            initial_state_parameter=str(row.get("initial_state_parameter", "INIT")),
            operation_count_parameter=str(row.get("operation_count_parameter", "NUMS")),
            operation_time_parameters=tuple(str(value) for value in raw_times),
            closed_value=row.get("closed_value", 0),
            open_value=row.get("open_value", 1),
        )

    def parameters_for(self, schedule: LineSwitchSchedule, *, duration_s: float) -> dict[str, Any]:
        events = schedule.events
        if len(events) > len(self.operation_time_parameters):
            raise ValueError(
                f"{schedule.line_id} has {len(events)} physical transitions, but its PSCAD "
                f"timed control supports only {len(self.operation_time_parameters)}."
            )

        expected = schedule.initial_closed
        for event in events:
            expected = not expected
            if event.closed != expected:
                raise ValueError(
                    f"{schedule.line_id} event at {event.timestamp:g}s cannot be represented "
                    "by toggle-based PSCAD Timed Breaker Logic."
                )

        inactive_time = max(float(duration_s) + 1.0, 1.0)
        parameters: dict[str, Any] = {
            self.initial_state_parameter: self.closed_value if schedule.initial_closed else self.open_value,
            # tbreakn has no zero-operation setting. One transition after the
            # run window is the native, deterministic idle representation.
            self.operation_count_parameter: max(1, len(events)),
        }
        for index, parameter in enumerate(self.operation_time_parameters):
            parameters[parameter] = events[index].timestamp if index < len(events) else inactive_time + index
        return parameters


@dataclass(slots=True)
class PscadLineBinding:
    """Mapping from a logical line ID to a PSCAD breaker/switch component.

    Most bindings only ever need to flip one parameter (``closed_parameter``),
    but a PSCAD breaker3 in single-line view exposes its open/close state as
    three separate per-phase parameters (BOpen1/2/3) that all need setting
    together for a balanced 3-phase switch -- ``closed_parameters``/
    ``open_parameters`` cover that case without disturbing the single-param
    shape everything else (examples, tests) already relies on.
    """

    line_id: str
    component_id: int
    closed_parameter: str = "Closed"
    closed_value: Any = 1
    open_value: Any = 0
    closed_parameters: dict[str, Any] | None = None
    open_parameters: dict[str, Any] | None = None
    timed_control: PscadTimedControlBinding | None = None

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "PscadLineBinding":
        closed_parameters = row.get("closed_parameters")
        open_parameters = row.get("open_parameters")
        timed_control = row.get("timed_control")
        return cls(
            line_id=str(row["line_id"]),
            component_id=int(row.get("component_id", row.get("pscad_component_id"))),
            closed_parameter=str(row.get("closed_parameter", row.get("pscad_closed_parameter", "Closed"))),
            closed_value=row.get("closed_value", 1),
            open_value=row.get("open_value", 0),
            closed_parameters=dict(closed_parameters) if isinstance(closed_parameters, dict) else None,
            open_parameters=dict(open_parameters) if isinstance(open_parameters, dict) else None,
            timed_control=(
                PscadTimedControlBinding.from_dict(timed_control)
                if isinstance(timed_control, dict)
                else None
            ),
        )

    def parameters_for(self, closed: bool) -> dict[str, Any]:
        """The full {parameter: value} set to write for the given switch state."""

        if closed and self.closed_parameters is not None:
            return dict(self.closed_parameters)
        if not closed and self.open_parameters is not None:
            return dict(self.open_parameters)
        return {self.closed_parameter: self.closed_value if closed else self.open_value}

    def parameters_for_timeline(
        self,
        schedule: LineSwitchSchedule,
        *,
        duration_s: float,
    ) -> dict[str, Any]:
        if self.timed_control is None:
            raise ValueError(f"{self.line_id}: PSCAD mapping has no timed_control definition.")
        return self.timed_control.parameters_for(schedule, duration_s=duration_s)


@dataclass(slots=True)
class PscadParameterOperation:
    """One MCP-ready PSCAD component parameter update."""

    operation_id: str
    project_name: str
    component_id: int
    parameters: dict[str, Any]
    command_id: str
    line_id: str
    requested_action: str

    def to_mcp_call(self) -> dict[str, Any]:
        return {
            "tool": "set_component_parameters",
            "arguments": {
                "project_name": self.project_name,
                "component_id": self.component_id,
                "parameters": self.parameters,
            },
            "metadata": {
                "operation_id": self.operation_id,
                "command_id": self.command_id,
                "line_id": self.line_id,
                "requested_action": self.requested_action,
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PscadSwitchingAdapter:
    """Build PSCAD operations from accepted SEIAN switching plans."""

    def __init__(self, project_name: str, bindings: dict[str, PscadLineBinding]) -> None:
        self.project_name = project_name
        self.bindings = dict(bindings)

    @classmethod
    def from_mapping_payload(cls, payload: dict[str, Any], *, project_name: str | None = None) -> "PscadSwitchingAdapter":
        rows = payload.get("line_bindings", payload.get("bindings", []))
        if not isinstance(rows, list):
            raise ValueError("PSCAD mapping must include a 'line_bindings' list.")
        selected_project = project_name or str(payload.get("project_name", ""))
        if not selected_project:
            raise ValueError("PSCAD project_name is required.")
        bindings = [PscadLineBinding.from_dict(row) for row in rows]
        return cls(selected_project, {binding.line_id: binding for binding in bindings})

    @classmethod
    def from_mapping_file(cls, path: str | Path, *, project_name: str | None = None) -> "PscadSwitchingAdapter":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("PSCAD mapping JSON must be an object.")
        return cls.from_mapping_payload(payload, project_name=project_name)

    def operations_for_plan(self, plan: SwitchingPlan) -> list[PscadParameterOperation]:
        operations: list[PscadParameterOperation] = []
        for operation in plan.operations:
            if not operation.accepted or operation.action == "noop":
                continue
            binding = self.bindings.get(operation.line_id)
            if binding is None:
                continue
            operations.append(
                PscadParameterOperation(
                    operation_id=operation.operation_id,
                    project_name=self.project_name,
                    component_id=binding.component_id,
                    parameters=binding.parameters_for(operation.after_closed),
                    command_id=operation.command_id,
                    line_id=operation.line_id,
                    requested_action=operation.action,
                )
            )
        return operations

    def manifest_for_plans(self, plans: list[SwitchingPlan]) -> dict[str, Any]:
        operations = [operation for plan in plans for operation in self.operations_for_plan(plan)]
        missing_bindings = sorted(
            {
                operation.line_id
                for plan in plans
                for operation in plan.operations
                if operation.accepted and operation.action != "noop" and operation.line_id not in self.bindings
            }
        )
        return {
            "project_name": self.project_name,
            "mcp_server": "powermcp_pscad",
            "operation_count": len(operations),
            "missing_line_bindings": missing_bindings,
            "calls": [operation.to_mcp_call() for operation in operations],
        }

    def manifest_for_state(self, power_plane: PowerPlaneState, plans: list[SwitchingPlan]) -> dict[str, Any]:
        """Build a full final-state PSCAD snapshot plus command replay metadata."""

        operations: list[PscadParameterOperation] = []
        for line_id in sorted(power_plane.lines):
            binding = self.bindings.get(line_id)
            if binding is None:
                continue
            line = power_plane.lines[line_id]
            operations.append(
                PscadParameterOperation(
                    operation_id=f"final-state-{line_id}",
                    project_name=self.project_name,
                    component_id=binding.component_id,
                    parameters=binding.parameters_for(line.closed),
                    command_id="final-state-snapshot",
                    line_id=line_id,
                    requested_action="close" if line.closed else "open",
                )
            )

        changed_manifest = self.manifest_for_plans(plans)
        missing_bindings = sorted(line_id for line_id in power_plane.lines if line_id not in self.bindings)
        return {
            "project_name": self.project_name,
            "mcp_server": "powermcp_pscad",
            "mode": "final_state_snapshot",
            "operation_count": len(operations),
            "missing_line_bindings": missing_bindings,
            "changed_operation_count": changed_manifest["operation_count"],
            "changed_calls": changed_manifest["calls"],
            "calls": [operation.to_mcp_call() for operation in operations],
        }

    def manifest_for_timeline(self, timeline: SwitchingTimeline) -> dict[str, Any]:
        """Build full native timed-breaker schedules for every mapped line."""

        calls: list[dict[str, Any]] = []
        missing_bindings: list[str] = []
        unsupported_bindings: list[str] = []
        for line_id, schedule in sorted(timeline.line_schedules.items()):
            binding = self.bindings.get(line_id)
            if binding is None:
                missing_bindings.append(line_id)
                continue
            if binding.timed_control is None:
                unsupported_bindings.append(line_id)
                continue
            parameters = binding.parameters_for_timeline(schedule, duration_s=timeline.duration_s)
            call = PscadParameterOperation(
                operation_id=f"timeline-{line_id}",
                project_name=self.project_name,
                component_id=binding.component_id,
                parameters=parameters,
                command_id="controller-timeline",
                line_id=line_id,
                requested_action="schedule",
            ).to_mcp_call()
            call["metadata"].update(
                {
                    "initial_closed": schedule.initial_closed,
                    "final_closed": schedule.final_closed,
                    "events": [event.to_dict() for event in schedule.events],
                }
            )
            calls.append(call)

        if unsupported_bindings:
            raise ValueError(
                "Timed PSCAD simulation requested, but these mapped lines have no timed_control "
                f"definition: {', '.join(unsupported_bindings)}. Rebuild the PSCAD feeder."
            )

        return {
            "project_name": self.project_name,
            "mcp_server": "powermcp_pscad",
            "mode": "timed_event_sequence",
            "operation_count": len(calls),
            "changed_operation_count": len(timeline.events),
            "missing_line_bindings": missing_bindings,
            "project_settings": {
                "time_duration": timeline.duration_s,
                "PlotType": "PSOUT",
            },
            "timeline": timeline.to_dict(),
            "calls": calls,
        }
