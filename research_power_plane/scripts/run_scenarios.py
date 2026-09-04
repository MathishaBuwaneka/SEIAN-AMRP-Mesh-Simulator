"""Run every experiment scenario through PSCAD and collect transient results.

For each scenario in ``examples/scenarios/``: replay the controller commands
through the control/power-plane model, schedule accepted switch changes at their
controller timestamps, build, run, and read the recorded ``.psout`` channels.

Everything happens in this one process against a single PSCAD instance --
deliberately *not* through ``cli.py --execute-pscad``, because that launches
its own PSCAD subprocess, and two PSCAD processes saving the same ``.pscx``
concurrently duplicate the canvas (see AI_CONTEXT.md, Known Limitations).

Usage:
    py research_power_plane/scripts/run_scenarios.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import mhi.pscad
import mhi.psout

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research_power_plane"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(RESEARCH) not in sys.path:
    sys.path.insert(0, str(RESEARCH))

from seian_power_pipeline.control_plane import control_commands_from_payload
from seian_power_pipeline.pipeline import run_control_pipeline
from seian_power_pipeline.project_config import (
    TIMED_CASE_NAME,
    TIMED_MAP_FILE,
    TIMED_RESULTS_FILE,
    WORKSPACE_DIR,
    WORKSPACE_FILE,
)
from seian_power_pipeline.pscad_adapter import PscadSwitchingAdapter
from seian_power_pipeline.transient_analysis import analyze_trace

CASE_NAME = TIMED_CASE_NAME
TOPOLOGY_FILE = RESEARCH / "examples" / "lv_power_plane_microgrid.json"
SCENARIO_DIR = RESEARCH / "examples" / "scenarios"
MAP_FILE = TIMED_MAP_FILE
RESULTS_FILE = TIMED_RESULTS_FILE


def main() -> int:
    parser = argparse.ArgumentParser(description="Run timed SEIAN switching scenarios in PSCAD.")
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Scenario filename stem or glob; repeat to select several (default: all).",
    )
    parser.add_argument("--output", type=Path, default=RESULTS_FILE, help="JSON result path.")
    args = parser.parse_args()

    topology = json.loads(TOPOLOGY_FILE.read_text(encoding="utf-8"))
    mapping = json.loads(MAP_FILE.read_text(encoding="utf-8"))
    adapter = PscadSwitchingAdapter.from_mapping_payload(mapping, project_name=CASE_NAME)

    # PSCAD 5.0.1 generates a batch that invokes its case executable by bare
    # name after pushd. This machine-wide hardening flag prevents cmd.exe from
    # searching that current directory, so remove it only for this child tree.
    os.environ.pop("NoDefaultCurrentDirectoryInExePath", None)
    pscad = mhi.pscad.application()
    try:
        project = pscad.project(CASE_NAME)
    except ValueError:
        pscad.load(str(WORKSPACE_FILE))
        project = pscad.project(CASE_NAME)
    canvas = project.canvas("Main")

    results: dict[str, Any] = {}
    scenario_files = _select_scenario_files(args.scenario)
    for scenario_file in scenario_files:
        name = scenario_file.stem
        print(f"\n=== {name} ===", flush=True)
        try:
            results[name] = _run_scenario(
                pscad, project, canvas, adapter, topology, scenario_file
            )
        except Exception:
            print(traceback.format_exc(), flush=True)
            results[name] = {"error": traceback.format_exc()}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {args.output}")
    _print_summary(results)
    return 1 if any("error" in row for row in results.values()) else 0


def _select_scenario_files(patterns: list[str]) -> list[Path]:
    if not patterns:
        return sorted(SCENARIO_DIR.glob("*.json"))
    selected: set[Path] = set()
    for pattern in patterns:
        candidate_pattern = pattern if any(char in pattern for char in "*?[]") else f"{pattern}.json"
        selected.update(SCENARIO_DIR.glob(candidate_pattern))
    if not selected:
        raise SystemExit(f"No scenario files matched: {', '.join(patterns)}")
    return sorted(selected)


def _run_scenario(
    pscad: Any,
    project: Any,
    canvas: Any,
    adapter: PscadSwitchingAdapter,
    topology: dict[str, Any],
    scenario_file: Path,
) -> dict[str, Any]:
    payload = json.loads(scenario_file.read_text(encoding="utf-8"))
    commands = control_commands_from_payload(payload)
    result = run_control_pipeline(
        topology_payload=topology,
        commands=commands,
        preserve_radial=True,
        pscad_mapping_payload=None,
        execute_in_pscad=False,
        simulation_mode="transient",
    )
    final = result.final_power_plane
    analysis = final["analysis"]
    manifest = adapter.manifest_for_timeline(result.switching_timeline)

    applied: dict[str, Any] = {}
    for call in manifest["calls"]:
        arguments = call["arguments"]
        metadata = call["metadata"]
        canvas.component(arguments["component_id"]).parameters(**arguments["parameters"])
        applied[metadata["line_id"]] = {
            "initial_closed": metadata["initial_closed"],
            "final_closed": metadata["final_closed"],
            "events": metadata["events"],
            "parameters": arguments["parameters"],
        }

    project.parameters(**manifest["project_settings"])

    project.save()
    project.build()
    build_messages = _build_messages(project)
    if build_messages["errors"]:
        first_errors = "; ".join(row["text"] for row in build_messages["errors"][:5])
        raise RuntimeError(f"PSCAD build failed: {first_errors}")
    run_started = time.time()
    project.run()

    command_times = sorted(set(result.switching_timeline.command_timestamps))
    channels = _read_channels(project, command_times, not_before=run_started)
    measured_metrics = _measured_metrics(channels, command_times)
    print(
        f"  energized={len(analysis['energized_nodes'])} "
        f"deenergized={len(analysis['deenergized_nodes'])} "
        f"closed/open={analysis['closed_line_count']}/{analysis['open_line_count']} "
        f"channels={len(channels)}",
        flush=True,
    )
    return {
        "scenario": payload.get("scenario", {}),
        "commands": len(commands),
        "accepted_commands": sum(1 for plan in result.plans if plan.accepted),
        "analysis": analysis,
        "timeline": result.switching_timeline.to_dict(),
        "applied_switch_schedule": applied,
        "build_messages": build_messages,
        "measured_metrics": measured_metrics,
        "channels": channels,
    }


def _read_channels(
    project: Any,
    event_times_s: list[float],
    *,
    not_before: float,
) -> dict[str, dict[str, Any]]:
    """Summaries, event samples, and previews for every recorded pgb channel."""

    psout = _newest_psout(project, not_before=not_before)
    if psout is None:
        output = project.output().strip()
        detail = f" Runtime output: {output}" if output else ""
        raise RuntimeError(f"PSCAD run produced no fresh .psout file.{detail}")
    out: dict[str, dict[str, Any]] = {}
    with mhi.psout.File(str(psout)) as handle:
        run = handle.run(0)
        for call, trace, _path in _iter_traces(handle, run):
            name = call.get("Name") if call is not None else None
            if not name:
                continue
            values = trace.data
            times = trace.domain.data
            if not values or not times:
                continue
            out[str(name)] = analyze_trace(
                str(name),
                times,
                values,
                event_times_s=event_times_s,
            )
    return out


def _measured_metrics(
    channels: dict[str, dict[str, Any]],
    command_times_s: list[float],
) -> dict[str, Any]:
    voltage_interruptions = {
        name.removeprefix("Vrms_"): row.get("interruptions", [])
        for name, row in channels.items()
        if name.startswith("Vrms_") and row.get("interruptions")
    }
    event_evidence = []
    for event_time in command_times_s:
        evidence: dict[str, Any] = {
            "command_time_s": event_time,
            "bus_voltage_kv": {},
            "breaker_state": {},
        }
        for name, row in channels.items():
            event = next(
                (item for item in row.get("events", []) if item["command_time_s"] == event_time),
                None,
            )
            if event is None:
                continue
            compact = {key: event[key] for key in ("before", "at", "after", "delta")}
            if name.startswith("Vrms_"):
                evidence["bus_voltage_kv"][name.removeprefix("Vrms_")] = compact
            elif name.startswith("State_"):
                evidence["breaker_state"][name.removeprefix("State_")] = compact
        event_evidence.append(evidence)

    return {
        "voltage_threshold_kv": 0.2,
        "voltage_interruptions": voltage_interruptions,
        "event_evidence": event_evidence,
    }


def _newest_psout(project: Any, *, not_before: float = 0.0) -> Path | None:
    candidates = sorted(
        (WORKSPACE_DIR / f"{CASE_NAME}.gf46").glob("*.psout"),
        key=lambda p: p.stat().st_mtime,
    )
    if not candidates or candidates[-1].stat().st_mtime < not_before - 1.0:
        return None
    return candidates[-1]


def _build_messages(project: Any) -> dict[str, Any]:
    rows = [
        {
            "text": message.text,
            "status": message.status,
            "component": message.name,
            "component_id": message.link,
        }
        for message in project.messages()
    ]
    return {
        "errors": [row for row in rows if str(row["status"]).lower() == "error"],
        "warnings": [row for row in rows if str(row["status"]).lower() == "warning"],
        "info_count": sum(
            1 for row in rows if str(row["status"]).lower() not in {"error", "warning"}
        ),
    }


def _iter_traces(handle: Any, run: Any):
    """Yield (pgb_call, trace, path) for each data trace -- mirrors pscad_mcp."""

    sep = getattr(handle, "_sep", "/")
    pgb_by_path: dict[str, Any] = {}
    trace_calls: list[tuple[Any, str]] = []
    for call, path in handle.call_paths("**"):
        source = call.get("Source")
        if source == "PGB":
            pgb_by_path[path] = call
        elif source == "Trace":
            trace_calls.append((call, path))
    for call, path in trace_calls:
        parts = path.split(sep)
        # trace path is <PGB path>/<record>/<trace#>; drop the last two.
        parent = sep.join(parts[:-2]) if len(parts) > 2 else path
        yield pgb_by_path.get(parent), run.trace(call), path


def _print_summary(results: dict[str, Any]) -> None:
    print("\n--- Transient summary (measured PSCAD values) ---")
    for name, row in results.items():
        if "error" in row:
            print(f"{name}: ERROR")
            continue
        channels = row.get("channels", {})
        volts = {k: v["final"] for k, v in channels.items() if k.startswith("Vrms_")}
        amps = {k: v["final"] for k, v in channels.items() if k.startswith("Irms_")}
        analysis = row["analysis"]
        print(f"\n{name}: energized={analysis['energized_nodes']}")
        print(f"  de-energized={analysis['deenergized_nodes']}")
        for key in sorted(volts):
            print(f"    {key:24s} {volts[key] * 1000:8.1f} V")
        for key in sorted(amps):
            print(f"    {key:24s} {amps[key] * 1000:8.2f} A")
        for node, intervals in row["measured_metrics"]["voltage_interruptions"].items():
            for interval in intervals:
                suffix = " (ongoing at end)" if interval["ongoing_at_end"] else ""
                print(
                    f"    outage {node:18s} {interval['start_s']:.4f}-"
                    f"{interval['end_s']:.4f} s, {interval['duration_s']:.4f} s{suffix}"
                )


if __name__ == "__main__":
    raise SystemExit(main())
