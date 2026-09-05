"""Compile accepted controller operations into a physical switching timeline."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from seian_power_pipeline.power_plane import SwitchingPlan


@dataclass(slots=True, frozen=True)
class SwitchTimelineEvent:
    """One state transition that must occur inside the PSCAD simulation."""

    timestamp: float
    line_id: str
    closed: bool
    command_id: str
    operation_id: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LineSwitchSchedule:
    """Initial state and chronological transitions for one physical line."""

    line_id: str
    initial_closed: bool
    events: list[SwitchTimelineEvent] = field(default_factory=list)

    @property
    def final_closed(self) -> bool:
        return self.events[-1].closed if self.events else self.initial_closed

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "initial_closed": self.initial_closed,
            "final_closed": self.final_closed,
            "event_count": len(self.events),
            "events": [event.to_dict() for event in self.events],
        }


@dataclass(slots=True)
class SwitchingTimeline:
    """A complete event schedule plus the PSCAD run window it requires."""

    duration_s: float
    post_event_window_s: float
    command_timestamps: list[float]
    line_schedules: dict[str, LineSwitchSchedule]

    @property
    def events(self) -> list[SwitchTimelineEvent]:
        return sorted(
            (event for schedule in self.line_schedules.values() for event in schedule.events),
            key=lambda event: (event.timestamp, event.command_id, event.operation_id),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration_s": self.duration_s,
            "post_event_window_s": self.post_event_window_s,
            "command_timestamps": list(self.command_timestamps),
            "event_count": len(self.events),
            "event_timestamps": sorted({event.timestamp for event in self.events}),
            "line_schedules": [
                schedule.to_dict()
                for schedule in sorted(self.line_schedules.values(), key=lambda row: row.line_id)
            ],
        }


def build_switching_timeline(
    topology_payload: dict[str, Any],
    plans: list[SwitchingPlan],
    *,
    minimum_duration_s: float = 1.0,
    post_event_window_s: float = 1.0,
    duration_override_s: float | None = None,
) -> SwitchingTimeline:
    """Build a deterministic timeline from the topology's initial state and plans.

    Rejected operations and no-ops remain in the pipeline artifact but never
    become physical breaker events. Command timestamps still extend the run
    window, so a rejected command can be demonstrated without changing PSCAD.
    """

    minimum_duration_s = _finite_nonnegative(minimum_duration_s, "minimum duration")
    post_event_window_s = _finite_nonnegative(post_event_window_s, "post-event window")
    schedules = _initial_line_schedules(topology_payload)

    command_timestamps: list[float] = []
    previous_timestamp = -math.inf
    for plan in plans:
        timestamp = _finite_nonnegative(plan.command.timestamp, f"{plan.command.command_id} timestamp")
        if timestamp < previous_timestamp:
            raise ValueError(
                "Controller commands must be replayed in non-decreasing timestamp order "
                f"({plan.command.command_id} is at {timestamp:g}s after {previous_timestamp:g}s)."
            )
        previous_timestamp = timestamp
        command_timestamps.append(timestamp)

        for operation in plan.operations:
            if not operation.accepted or operation.action == "noop":
                continue
            schedule = schedules.get(operation.line_id)
            if schedule is None:
                raise ValueError(f"Accepted operation references unknown power line: {operation.line_id}")
            current_closed = schedule.final_closed
            if operation.before_closed != current_closed:
                raise ValueError(
                    f"{operation.operation_id}: timeline state mismatch for {operation.line_id}; "
                    f"expected before_closed={current_closed}."
                )
            if schedule.events and schedule.events[-1].timestamp == timestamp:
                raise ValueError(
                    f"{operation.line_id} has multiple state transitions at {timestamp:g}s; "
                    "use distinct physical switching times."
                )
            schedule.events.append(
                SwitchTimelineEvent(
                    timestamp=timestamp,
                    line_id=operation.line_id,
                    closed=operation.after_closed,
                    command_id=operation.command_id,
                    operation_id=operation.operation_id,
                    reason=operation.reason,
                )
            )

    last_command_s = max(command_timestamps, default=0.0)
    required_duration_s = max(minimum_duration_s, last_command_s + post_event_window_s)
    if duration_override_s is None:
        duration_s = required_duration_s
    else:
        duration_s = _finite_nonnegative(duration_override_s, "duration override")
        if duration_s < required_duration_s:
            raise ValueError(
                f"PSCAD duration {duration_s:g}s is too short; at least "
                f"{required_duration_s:g}s is required for the event timeline."
            )

    return SwitchingTimeline(
        duration_s=duration_s,
        post_event_window_s=post_event_window_s,
        command_timestamps=command_timestamps,
        line_schedules=schedules,
    )


def _initial_line_schedules(topology_payload: dict[str, Any]) -> dict[str, LineSwitchSchedule]:
    rows = topology_payload.get("power_lines")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Timed PSCAD simulation requires a non-empty topology power_lines list.")

    schedules: dict[str, LineSwitchSchedule] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"power_lines[{index}] must be an object.")
        line_id = str(row.get("line_id", "")).strip()
        if not line_id:
            raise ValueError(f"power_lines[{index}] must include line_id for timed simulation.")
        if line_id in schedules:
            raise ValueError(f"Duplicate power line ID in timeline: {line_id}")
        schedules[line_id] = LineSwitchSchedule(
            line_id=line_id,
            initial_closed=bool(row.get("closed", True)),
        )
    return schedules


def _finite_nonnegative(value: float, label: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label} must be a finite, non-negative number.")
    return number
