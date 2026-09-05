"""Streamlit dashboard for the SEIAN power-plane PSCAD pipeline."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from seian_power_pipeline.control_plane import control_commands_from_payload
from seian_power_pipeline.pipeline import pipeline_summary, run_control_pipeline
from seian_power_pipeline.project_config import (
    DEFAULT_CASE_NAME,
    DEFAULT_MAP_FILE,
    WORKSPACE_FILE,
)
from seian_power_pipeline.pscad_mcp_client import PscadRuntimeConfig, execute_pscad_manifest
from seian_power_pipeline.psout_channels import extract_channel_series, group_channels
from research_power_plane.scripts.bootstrap_pscad_workspace import (
    bootstrap_workspace,
)
from research_power_plane.dashboard_ui.editors import render_graphical_inputs


HERE = Path(__file__).resolve().parent
EXAMPLES = HERE / "examples"
DEFAULT_WORKSPACE_FILE = WORKSPACE_FILE
DEFAULT_PSCAD_PROJECT = DEFAULT_CASE_NAME
GENERATED_MAP_FILE = DEFAULT_MAP_FILE
EXPERIMENTS = {
    "Baseline": "01_no_fault_baseline.json",
    "Fault isolation": "02_single_fault_isolation.json",
    "Tie restoration": "03_tie_switch_restoration.json",
    "Loop rejection": "04_loop_rejection.json",
    "Degraded control": "05_degraded_control_plane.json",
    "Physical fault and restoration": "06_physical_fault_restoration.json",
}


st.set_page_config(page_title="SEIAN PSCAD Co-Simulation", layout="wide")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_json_text(path: Path) -> tuple[str, dict[str, Any]]:
    text = read_text(path)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object.")
    return text, payload


def apply_uploaded_text(upload: Any, target: str) -> None:
    marker = f"upload_digest_{target}"
    if upload is None:
        st.session_state.pop(marker, None)
        return
    content = upload.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    if st.session_state.get(marker) != digest:
        st.session_state[target] = content.decode("utf-8-sig")
        st.session_state[marker] = digest


def load_default_state() -> None:
    topology_text, topology_payload = read_json_text(EXAMPLES / "lv_power_plane_microgrid.json")
    commands_text, _ = read_json_text(
        EXAMPLES / "scenarios" / "06_physical_fault_restoration.json"
    )
    mapping_path = GENERATED_MAP_FILE if GENERATED_MAP_FILE.exists() else EXAMPLES / "pscad_component_map.example.json"
    mapping_text, _ = read_json_text(mapping_path)
    st.session_state.topology_text = topology_text
    st.session_state.command_text = commands_text
    st.session_state.mapping_text = mapping_text
    st.session_state.topology_payload = topology_payload
    st.session_state.pscad_project_name = DEFAULT_PSCAD_PROJECT
    st.session_state.workspace_file = str(DEFAULT_WORKSPACE_FILE) if DEFAULT_WORKSPACE_FILE.exists() else ""
    st.session_state.pipeline_result = None
    st.session_state.pscad_status = None
    st.session_state.observed_inputs = None
    st.session_state.pipeline_error = None
    st.session_state.experiment_choice = "Physical fault and restoration"
    st.session_state.editor_command_index = 0


def load_experiment() -> None:
    path = EXAMPLES / "scenarios" / EXPERIMENTS[st.session_state.experiment_choice]
    st.session_state.command_text = read_text(path)
    st.session_state.editor_command_index = 0


def apply_raw_edit(target: str) -> None:
    st.session_state[target] = st.session_state[f"raw_{target}"]


if "topology_text" not in st.session_state:
    load_default_state()


st.html("<style>.stMain h1 {font-size: 1.75rem; line-height: 1.3; letter-spacing: 0;}</style>")
st.title("SEIAN AMRP to PSCAD Co-Simulation")

with st.sidebar:
    st.header("Experiment")
    st.selectbox("Scenario preset", list(EXPERIMENTS), key="experiment_choice", on_change=load_experiment)
    if st.button("Reload example files", icon=":material/refresh:", width="stretch"):
        load_default_state()
        st.rerun()

    with st.expander("Import JSON"):
        topology_file = st.file_uploader("Topology JSON", type=["json"])
        apply_uploaded_text(topology_file, "topology_text")
        command_file = st.file_uploader("Control commands JSON", type=["json"])
        apply_uploaded_text(command_file, "command_text")
        mapping_file = st.file_uploader("PSCAD component map JSON", type=["json"])
        apply_uploaded_text(mapping_file, "mapping_text")

    st.divider()
    st.header("PSCAD")
    execute_pscad = st.toggle("Auto-run PSCAD after replay", value=GENERATED_MAP_FILE.exists())
    simulate_changes = st.toggle("Simulate input changes", value=True)
    mode_label = st.segmented_control(
        "Simulation mode",
        options=("Controller timeline", "Final steady state"),
        default="Controller timeline",
        help=(
            "Controller timeline operates PSCAD breakers at command timestamps. "
            "Final steady state starts directly in the resulting topology."
        ),
    )
    simulation_mode = "transient" if mode_label == "Controller timeline" else "steady_state"
    post_event_seconds = st.number_input(
        "Recording after last command (s)",
        value=1.0,
        min_value=0.1,
        max_value=30.0,
        disabled=simulation_mode != "transient",
    )
    pscad_project_name = st.text_input(
        "PSCAD project/case name",
        value=st.session_state.get("pscad_project_name", DEFAULT_PSCAD_PROJECT),
    )
    workspace_file = st.text_input(
        "PSCAD workspace/project file",
        value=st.session_state.get("workspace_file", str(DEFAULT_WORKSPACE_FILE) if DEFAULT_WORKSPACE_FILE.exists() else ""),
    )
    poll_seconds = st.number_input("Run polling limit (s)", value=120.0, min_value=5.0, max_value=1800.0)
    read_outputs = st.toggle("Read and chart PSCAD outputs", value=True)
    preserve_radial = st.toggle("Reject loop-forming closures", value=True)

    st.divider()
    if st.button("Open SEIAN PSCAD Workspace", use_container_width=True):
        try:
            if not DEFAULT_WORKSPACE_FILE.exists():
                report = bootstrap_workspace()
                st.session_state.mapping_text = read_text(Path(report["mapping_file"]))
                st.session_state.workspace_file = report["workspace_file"]
                st.session_state.pscad_project_name = report["case_name"]
            result = execute_pscad_manifest(
                {"calls": []},
                PscadRuntimeConfig(
                    project_name=pscad_project_name.strip() or DEFAULT_PSCAD_PROJECT,
                    workspace_files=[str(DEFAULT_WORKSPACE_FILE)],
                    allowed_roots=[str(ROOT)],
                    run_after_apply=False,
                ),
            )
            st.session_state.pscad_status = result.to_dict()
        except Exception as exc:
            st.session_state.pscad_status = {"errors": [str(exc)]}
        st.rerun()

    if st.button("Check PSCAD connection", use_container_width=True):
        result = execute_pscad_manifest(
            {"calls": []},
            PscadRuntimeConfig(
                project_name=pscad_project_name.strip() or DEFAULT_PSCAD_PROJECT,
                workspace_files=[workspace_file.strip()] if workspace_file.strip() else [],
                allowed_roots=[str(ROOT)],
                run_after_apply=False,
            ),
        )
        st.session_state.pscad_status = result.to_dict()
        st.rerun()


run_col, clear_col = st.columns([3, 1])
requested_run = run_col.button("Replay and Simulate", icon=":material/play_arrow:", type="primary", width="stretch")
if clear_col.button("Clear result", icon=":material/clear:", width="stretch"):
    st.session_state.pipeline_result = None
    st.session_state.pipeline_error = None
    st.rerun()

render_graphical_inputs(preserve_radial=preserve_radial, post_event_seconds=float(post_event_seconds))

with st.expander("Advanced JSON"):
    # Canonical documents outlive widgets that are skipped during a form rerun.
    for target, label, height in [
        ("topology_text", "Topology JSON", 260),
        ("command_text", "Command JSON", 300),
        ("mapping_text", "Map logical switch IDs to PSCAD component IDs", 260),
    ]:
        st.session_state[f"raw_{target}"] = st.session_state[target]
        st.text_area(label, key=f"raw_{target}", height=height, on_change=apply_raw_edit, args=(target,))
    topology_text = st.session_state.topology_text
    command_text = st.session_state.command_text
    mapping_text = st.session_state.mapping_text
    downloads = st.columns(3)
    for column, label, content, filename in [
        (downloads[0], "Topology", topology_text, "topology.json"),
        (downloads[1], "Commands", command_text, "commands.json"),
        (downloads[2], "Bindings", mapping_text, "pscad_mapping.json"),
    ]:
        column.download_button(label, content, filename, mime="application/json", icon=":material/download:", width="stretch")
input_signature = hashlib.sha256(json.dumps([
    topology_text, command_text, mapping_text, pscad_project_name, workspace_file,
    simulation_mode, float(post_event_seconds), preserve_radial,
]).encode("utf-8")).hexdigest()
previous_signature = st.session_state.get("observed_inputs")
inputs_changed = previous_signature is not None and previous_signature != input_signature
st.session_state.observed_inputs = input_signature
if requested_run or (simulate_changes and inputs_changed):
    st.session_state.pipeline_error = None
    st.session_state.pipeline_result = None
    try:
        topology_payload = json.loads(topology_text)
        command_payload = json.loads(command_text)
        mapping_payload = json.loads(mapping_text)
        if not isinstance(topology_payload, dict) or not isinstance(mapping_payload, dict):
            raise ValueError("Topology and PSCAD mapping must be JSON objects.")
        commands = control_commands_from_payload(command_payload)
        project_name = pscad_project_name.strip() or DEFAULT_PSCAD_PROJECT
        with st.spinner("Running PSCAD simulation..." if execute_pscad else "Replaying controller commands..."):
            result = run_control_pipeline(
                topology_payload=topology_payload,
                commands=commands,
                preserve_radial=preserve_radial,
                pscad_mapping_payload=mapping_payload,
                pscad_project_name=project_name,
                execute_in_pscad=execute_pscad,
                pscad_workspace_files=[workspace_file.strip()] if workspace_file.strip() else [],
                pscad_allowed_roots=[str(ROOT)],
                pscad_poll_s=float(poll_seconds),
                pscad_read_outputs=read_outputs,
                simulation_mode=simulation_mode,
                post_event_window_s=float(post_event_seconds),
                physical_fault_payload=(command_payload if isinstance(command_payload, dict) else None),
            )
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        st.session_state.pipeline_error = f"Pipeline failed: {exc}"
    else:
        st.session_state.pipeline_result = result.to_dict()
        st.rerun()

if st.session_state.get("pipeline_error"):
    st.error(st.session_state.pipeline_error)

if st.session_state.pscad_status:
    st.subheader("PSCAD Connection")
    st.json(st.session_state.pscad_status)

result = st.session_state.pipeline_result
if isinstance(result, dict):
    st.subheader("Pipeline Result")
    with st.expander("Run summary"):
        st.text(pipeline_summary(result))

    analysis = result["final_power_plane"]["analysis"]
    metrics = st.columns(6)
    metrics[0].metric("Commands", len(result["plans"]))
    metrics[1].metric("Energized", len(analysis["energized_nodes"]))
    metrics[2].metric("Deenergized", len(analysis["deenergized_nodes"]))
    metrics[3].metric("Open lines", analysis["open_line_count"])
    metrics[4].metric("Cycles", len(analysis["cycles"]))
    manifest = result.get("pscad_manifest") or {}
    metrics[5].metric("PSCAD calls", manifest.get("operation_count", 0))

    plans = [
        {
            "command_id": plan["command"]["command_id"],
            "action": plan["command"]["action"],
            "accepted": plan["accepted"],
            "operations": len(plan["operations"]),
            "warnings": "; ".join(plan["warnings"]),
        }
        for plan in result["plans"]
    ]
    st.dataframe(pd.DataFrame(plans), use_container_width=True, hide_index=True)

    operations = [operation for plan in result["plans"] for operation in plan["operations"]]
    with st.expander("Switch operations"):
        st.dataframe(pd.DataFrame(operations), width="stretch", hide_index=True)

    timeline = result.get("switching_timeline")
    if timeline:
        timeline_events = [
            event
            for schedule in timeline.get("line_schedules", [])
            for event in schedule.get("events", [])
        ]
        if timeline_events:
            with st.expander("Accepted breaker events"):
                st.dataframe(pd.DataFrame(timeline_events), width="stretch", hide_index=True)

    physical_faults = result.get("physical_faults", [])
    if physical_faults:
        with st.expander("Physical fault events"):
            st.dataframe(pd.DataFrame(physical_faults), width="stretch", hide_index=True)

    with st.expander("Final power-plane record"):
        st.dataframe(pd.DataFrame(result["final_power_plane"]["lines"]), width="stretch", hide_index=True)
        st.json(analysis)

    if result.get("pscad_manifest"):
        with st.expander("PSCAD MCP manifest"):
            st.json(result["pscad_manifest"])

    if result.get("pscad_execution"):
        st.write("Live PSCAD Execution")
        execution = result["pscad_execution"]
        execution_errors = execution.get("errors", [])
        if execution_errors:
            st.error("PSCAD execution failed: " + "; ".join(execution_errors))
        elif execution.get("fresh_output_files"):
            st.success("PSCAD completed the run and produced fresh output data.")

        execution_metrics = st.columns(4)
        execution_metrics[0].metric("Applied parameter writes", execution.get("applied_operation_count", 0))
        execution_metrics[1].metric(
            "Status polls", len(execution.get("run_status_history", []))
        )
        output_channels = execution.get("output_channels") or {}
        output_payload = output_channels.get("result", output_channels)
        execution_metrics[2].metric(
            "Raw channels", output_payload.get("channel_count", 0)
            if isinstance(output_payload, dict)
            else 0,
        )
        execution_metrics[3].metric(
            "Fresh result files", len(execution.get("fresh_output_files", []))
        )

        with st.expander("Raw PSCAD execution record"):
            st.json(execution)

        series = extract_channel_series(execution.get("channel_data"))
        if series:
            st.write("PSCAD Output Channels (.psout)")
            for title, group in group_channels(series):
                st.caption(title)
                combined = pd.concat(
                    {
                        name: pd.Series(data["values"], index=data["time"], name=name)
                        for name, data in sorted(group.items())
                    },
                    axis=1,
                )
                combined.index.name = "time (s)"
                st.line_chart(combined)
        elif execution.get("channel_data"):
            st.info(
                "PSCAD returned output-channel data that could not be parsed into series. "
                "Raw payload is in the Live PSCAD Execution JSON above."
            )

    st.download_button(
        "Download Full Research Artifact",
        json.dumps(result, indent=2),
        "seian_pscad_pipeline_result.json",
        mime="application/json",
        use_container_width=True,
    )
