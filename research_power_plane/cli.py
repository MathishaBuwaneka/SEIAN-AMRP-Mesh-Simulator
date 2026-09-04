"""CLI for SEIAN AMRP-to-PSCAD co-simulation experiments."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seian_power_pipeline.control_plane import control_commands_from_payload
from seian_power_pipeline.pipeline import pipeline_summary, run_control_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay SEIAN control commands into PSCAD-ready LV switching.")
    parser.add_argument("topology", type=Path, help="Topology JSON with nodes and optional power_lines.")
    parser.add_argument("commands", type=Path, help="Control-command JSON file.")
    parser.add_argument("--component-map", type=Path, help="PSCAD line-to-component map JSON.")
    parser.add_argument("--project-name", help="Override PSCAD project/case name.")
    parser.add_argument("--workspace-file", action="append", default=[], help="PSCAD .pswx/.pscx file to load first.")
    parser.add_argument("--execute-pscad", action="store_true", help="Apply switch updates and run PSCAD.")
    parser.add_argument("--read-outputs", action="store_true", help="List output channels after PSCAD run.")
    parser.add_argument(
        "--simulation-mode",
        choices=("transient", "steady-state"),
        default="transient",
        help="Run commands at their timestamps or apply only their final state (default: transient).",
    )
    parser.add_argument(
        "--post-event-seconds",
        type=float,
        default=1.0,
        help="Transient recording window after the last command (default: 1.0).",
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        help="Optional transient duration override; must extend past the last command.",
    )
    parser.add_argument("--allow-loops", action="store_true", help="Allow closed-loop LV switching.")
    parser.add_argument("--poll-seconds", type=float, default=120.0, help="Maximum PSCAD run polling time.")
    parser.add_argument("--output", type=Path, help="Write the full JSON artifact to this file.")
    args = parser.parse_args()

    try:
        topology_payload = _read_json_object(args.topology)
        command_payload = json.loads(args.commands.read_text(encoding="utf-8"))
        commands = control_commands_from_payload(command_payload)
        mapping_payload = _read_json_object(args.component_map) if args.component_map else None
        result = run_control_pipeline(
            topology_payload=topology_payload,
            commands=commands,
            preserve_radial=not args.allow_loops,
            pscad_mapping_payload=mapping_payload,
            pscad_project_name=args.project_name,
            execute_in_pscad=args.execute_pscad,
            pscad_workspace_files=args.workspace_file,
            pscad_allowed_roots=[str(Path.cwd())],
            pscad_poll_s=args.poll_seconds,
            pscad_read_outputs=args.read_outputs,
            simulation_mode=args.simulation_mode,
            post_event_window_s=args.post_event_seconds,
            duration_override_s=args.duration_seconds,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError, KeyError) as exc:
        parser.error(str(exc))

    print(pipeline_summary(result))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        print(f"Full result written to {args.output}")
    return 0


def _read_json_object(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object.")
    return data


if __name__ == "__main__":
    raise SystemExit(main())
