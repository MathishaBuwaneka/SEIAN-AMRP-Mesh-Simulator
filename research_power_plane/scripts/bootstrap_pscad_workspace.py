"""Create a SEIAN-specific PSCAD workspace/case for dashboard integration.

This uses the official ``mhi.pscad`` automation API because the installed MCP
server can operate existing projects but does not expose project/canvas creation
tools.
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

import mhi.pscad


ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_DIR = ROOT / "research_power_plane" / "pscad_workspace"
WORKSPACE_FILE = WORKSPACE_DIR / "SEIAN_PSCAD_Workspace.pswx"
CASE_FILE = WORKSPACE_DIR / "SEIAN_LV_Switching.pscx"
CASE_NAME = "SEIAN_LV_Switching"
REPORT_FILE = WORKSPACE_DIR / "bootstrap_report.json"
ERROR_FILE = WORKSPACE_DIR / "bootstrap_error.txt"
GENERATED_MAP_FILE = WORKSPACE_DIR / "seian_pscad_component_map.generated.json"


def main() -> int:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        report = bootstrap_workspace()
    except Exception:
        ERROR_FILE.write_text(traceback.format_exc(), encoding="utf-8")
        print(f"PSCAD bootstrap failed. See {ERROR_FILE}")
        return 1

    REPORT_FILE.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "workspace_file": report["workspace_file"],
                "case_file": report["case_file"],
                "case_name": report["case_name"],
                "mapping_file": report["mapping_file"],
                "switch_count": len(report["switch_components"]),
            },
            indent=2,
        )
    )
    return 0


def bootstrap_workspace() -> dict[str, Any]:
    """Create/open the SEIAN PSCAD scaffold and return a machine-readable report."""

    pscad = _connect_visible_pscad()
    previous_workspace = _preserve_current_workspace(pscad)
    pscad.new_workspace(str(WORKSPACE_FILE))
    case = pscad.create_case(str(CASE_FILE))
    _set_case_parameters(case)

    main_canvas = case.canvas("Main")
    notes = [
        _create_note(main_canvas, 10, 8, "SEIAN PSCAD switching case"),
        _create_note(main_canvas, 10, 18, "Dashboard writes switch states, then runs this case."),
        _create_note(main_canvas, 10, 28, "Replace this generated scaffold with the detailed LV PSCAD feeder as the research model matures."),
    ]

    switch_names = [
        "SW_G01_N02",
        "SW_N02_N03",
        "SW_N03_N04",
        "SW_N03_N05",
        "SW_N05_N06",
        "SW_N02_N05_TIE",
        "SW_N04_N06_TIE",
    ]
    switch_components = []
    pscad_switches = []
    for index, name in enumerate(switch_names):
        y = 45 + index * 10
        component = main_canvas.create_component("master:var_switch", 18, y)
        component.parameters(Name=name, Value=_initial_switch_value(name))
        params = component.parameters() or {}
        pscad_switches.append(component)
        switch_components.append(
            {
                "line_id": name,
                "component_id": _component_id(component),
                "definition": _definition_name(component),
                "parameters": params,
            }
        )
        _create_note(main_canvas, 45, y, f"{name} command input")

    controls = []
    try:
        control_frame, created_controls = main_canvas.create_control_frame(72, 45, *pscad_switches)
        controls.append(
            {
                "component_id": _component_id(control_frame),
                "definition": _definition_name(control_frame),
                "control_count": len(created_controls),
            }
        )
    except Exception as exc:
        controls.append({"error": str(exc)})

    case.save()
    pscad.save_workspace(str(WORKSPACE_FILE))

    mapping = {
        "project_name": CASE_NAME,
        "line_bindings": [
            _binding_from_component(row)
            for row in switch_components
        ],
    }
    GENERATED_MAP_FILE.write_text(json.dumps(mapping, indent=2), encoding="utf-8")

    return {
        "previous_workspace_saved": previous_workspace,
        "workspace_file": str(WORKSPACE_FILE),
        "case_file": str(CASE_FILE),
        "case_name": CASE_NAME,
        "mapping_file": str(GENERATED_MAP_FILE),
        "notes": notes,
        "switch_components": switch_components,
        "controls": controls,
    }


def _connect_visible_pscad() -> Any:
    try:
        return mhi.pscad.application()
    except Exception:
        return mhi.pscad.launch(silence=False, minimize=False, splash=False, timeout=30)


def _preserve_current_workspace(pscad: Any) -> dict[str, Any]:
    """Save the currently open PSCAD workspace before replacing it in the GUI."""

    info = {
        "workspace_path": _safe_call(lambda: pscad.workspace_path, ""),
        "workspace_dir": _safe_call(lambda: pscad.workspace_dir, ""),
        "workspace_name": _safe_call(lambda: pscad.workspace_name, ""),
        "saved": False,
        "error": "",
    }
    try:
        pscad.save_workspace(save_projects=True)
    except Exception as exc:
        info["error"] = str(exc)
    else:
        info["saved"] = True
    return info


def _safe_call(callback: Any, default: Any) -> Any:
    try:
        return callback()
    except Exception:
        return default


def _set_case_parameters(case: Any) -> None:
    try:
        case.parameters(
            time_duration=0.25,
            time_step=25.0,
            sample_step=25.0,
            PlotType="PSOUT",
        )
    except Exception:
        case.parameters(time_duration=0.25)


def _create_note(canvas: Any, x: int, y: int, text: str) -> dict[str, Any]:
    note = canvas.create_sticky_note(x, y, text=text)
    return {
        "component_id": note.iid,
        "definition": _definition_name(note),
        "text": text,
    }


def _definition_name(component: Any) -> str:
    value = getattr(component, "defn_name", "")
    if isinstance(value, tuple):
        return ":".join(str(part) for part in value)
    return str(value)


def _component_id(component: Any) -> int:
    return int(getattr(component, "iid"))


def _binding_from_component(row: dict[str, Any]) -> dict[str, Any]:
    params = row.get("parameters", {})
    closed_parameter = "Value"
    for candidate in ("Value", "State", "STATE", "On", "ON"):
        if candidate in params:
            closed_parameter = candidate
            break
    return {
        "line_id": row["line_id"],
        "component_id": row["component_id"],
        "closed_parameter": closed_parameter,
        "closed_value": "ON",
        "open_value": "OFF",
    }


def _initial_switch_value(line_id: str) -> str:
    return "OFF" if line_id.endswith("_TIE") else "ON"


if __name__ == "__main__":
    raise SystemExit(main())
