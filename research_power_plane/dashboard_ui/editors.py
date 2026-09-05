"""Streamlit forms over canonical topology, command, and binding JSON."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd
import streamlit as st

from seian_power_pipeline.control_plane import NetworkControlCommand, control_commands_from_payload
from seian_power_pipeline.faults import physical_faults_from_payload
from seian_power_pipeline.pipeline import run_control_pipeline

from .figures import feeder_figure, timeline_figure
from .models import (
    ACTION_LABELS, FAULT_LABELS, command_rows, endpoints, line_label,
    remove_command, state_at, update_binding, update_command, update_fault, update_switch,
)


def _version(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:12]


def _commit(target: str, payload: Any) -> None:
    st.session_state[target] = json.dumps(payload, indent=2)
    st.rerun()


def _options(options: list[str], values: list[str]) -> list[str]:
    return list(dict.fromkeys([*options, *values]))


def _command_title(row: dict[str, Any], index: int) -> str:
    command = NetworkControlCommand.from_dict(row, index=index)
    target = command.target_node_id or command.target_line_id or command.destination_node_id or ""
    return f"{command.timestamp:g} s | {ACTION_LABELS[command.action.value]} | {target}".rstrip(" |")


def _command_editor(payload: Any, topology: dict[str, Any]) -> None:
    rows = command_rows(payload)
    version = _version(payload)
    choices = [*range(len(rows)), -1]
    previous = st.session_state.get("editor_command_index", 0)
    choice = st.selectbox(
        "Command", choices, index=choices.index(previous) if previous in choices else 0, key=f"command_choice_{version}",
        format_func=lambda index: "New command" if index == -1 else _command_title(rows[index], index),
    )
    st.session_state.editor_command_index = choice
    index = None if choice == -1 else choice
    known_ids = {command.command_id for command in control_commands_from_payload(payload)}
    new_id = f"cmd-{len(rows) + 1:03d}"
    while new_id in known_ids:
        new_id += "-new"
    row = rows[index] if index is not None else {"action": "open_line", "command_id": new_id, "timestamp": 1.0}
    command = NetworkControlCommand.from_dict(row)
    prefix = f"command_{version}_{choice}"
    action = st.selectbox(
        "Action", list(ACTION_LABELS), index=list(ACTION_LABELS).index(command.action.value),
        format_func=ACTION_LABELS.get, key=f"{prefix}_action",
    )
    current = command if action == command.action.value else NetworkControlCommand.from_dict({"action": action})
    nodes = [node["node_id"] for node in topology["nodes"]]
    lines = {line["line_id"]: line for line in topology["power_lines"]}
    edge_ids = {tuple(sorted(endpoints(line))): name for name, line in lines.items()}
    with st.form(f"{prefix}_{action}", border=False):
        first, second = st.columns(2)
        timestamp = first.number_input("At time (s)", min_value=0.0, value=float(command.timestamp), step=0.1, format="%.3f")
        identifier = second.text_input("Command ID", value=command.command_id)
        changes: dict[str, Any] = {"command_id": identifier, "timestamp": timestamp, "action": action}
        if action in {"isolate_node", "restore_node"}:
            choices = _options(nodes, [current.target_node_id] if current.target_node_id else [])
            changes["target_node_id"] = st.selectbox("Target bus", choices, index=choices.index(current.target_node_id) if current.target_node_id else 0)
        if action in {"open_line", "close_line"}:
            choices = _options(list(lines), [current.target_line_id] if current.target_line_id else [])
            changes["target_line_id"] = st.selectbox(
                "Target breaker", choices, index=choices.index(current.target_line_id) if current.target_line_id else 0,
                format_func=lambda value: line_label(lines[value]) if value in lines else value,
            )
        if action == "reroute_power_path":
            route = st.multiselect("Ordered route", _options(nodes, current.path), default=current.path)
            changes.update(path=route, source_node_id=route[0] if route else None, destination_node_id=route[-1] if route else None)
        if action in {"reroute_power_path", "isolate_node"}:
            changes["blocked_nodes"] = st.multiselect("Blocked buses", _options(nodes, current.blocked_nodes), default=current.blocked_nodes)
        if action in {"reroute_power_path", "apply_switch_set", "open_line", "close_line"}:
            for field, label in [("open_lines", "Open breakers"), ("close_lines", "Close breakers")]:
                edges = getattr(current, field)
                unknown = [edge for edge in edges if tuple(sorted(edge)) not in edge_ids]
                if unknown:
                    st.warning(f"Unmapped endpoints: {unknown}. These remain available in Advanced JSON.")
                defaults = [edge_ids[tuple(sorted(edge))] for edge in edges if tuple(sorted(edge)) in edge_ids]
                chosen = st.multiselect(label, list(lines), default=defaults, format_func=lambda value: line_label(lines[value]))
                changes[field] = [list(endpoints(lines[value])) for value in chosen] + [list(edge) for edge in unknown]
        with st.expander("Command details"):
            changes["controller_id"] = st.text_input("Controller", value=command.controller_id)
            changes["priority"] = int(st.number_input("Priority", value=command.priority, step=1))
            changes["reason"] = st.text_area("Reason", value=command.reason, height=90)
        save, delete = st.columns([3, 1])
        applied = save.form_submit_button("Apply command", icon=":material/check:", type="primary", width="stretch")
        removed = delete.form_submit_button("Delete", icon=":material/delete:", disabled=index is None, width="stretch")
    if applied:
        try:
            st.session_state.editor_command_index = len(rows) if index is None else index
            _commit("command_text", update_command(payload, index, changes))
        except ValueError as exc:
            st.error(str(exc))
    if removed and index is not None:
        _commit("command_text", remove_command(payload, index))


def _fault_editor(payload: Any, mapping: dict[str, Any]) -> None:
    faults = {fault.fault_id: fault for fault in physical_faults_from_payload(payload if isinstance(payload, dict) else None)}
    bindings = {row["fault_id"]: row for row in mapping.get("fault_bindings", [])}
    choices = list(dict.fromkeys([*bindings, *faults]))
    if not choices:
        st.info("No physical fault component is bound to this PSCAD case.")
        return
    fault_id = st.selectbox("Fault location", choices, format_func=lambda value: f"{bindings[value]['node_id']} | {value}" if value in bindings else value)
    event = faults.get(fault_id)
    binding = bindings.get(fault_id)
    if binding is None:
        st.warning("This fault has no PSCAD component binding.")
    node_id = binding["node_id"] if binding else event.node_id
    with st.form(f"fault_{_version(payload)}_{_version(mapping)}_{fault_id}", border=False):
        enabled = st.checkbox("Fault enabled", value=event is not None)
        fault_type = event.fault_type if event else "abc_ground"
        kind = st.selectbox("Fault type", list(FAULT_LABELS), index=list(FAULT_LABELS).index(fault_type), format_func=FAULT_LABELS.get)
        first, second = st.columns(2)
        start = first.number_input("Fault starts (s)", min_value=0.0, value=event.start_s if event else 4.8, step=0.1, format="%.3f")
        duration = second.number_input("Fault duration (s)", min_value=0.0, value=event.duration_s if event else 0.4, step=0.05, format="%.5f")
        resistance = st.number_input("Fault resistance (ohm)", min_value=0.0, value=event.resistance_ohm if event else 0.05, step=0.01, format="%.4f")
        applied = st.form_submit_button("Apply fault", icon=":material/check:", type="primary", width="stretch")
    if applied:
        changes = {"node_id": node_id, "start_s": start, "duration_s": duration, "fault_type": kind, "resistance_ohm": resistance} if enabled else None
        try:
            _commit("command_text", update_fault(payload, fault_id, changes))
        except ValueError as exc:
            st.error(str(exc))


def _switch_editor(topology: dict[str, Any], mapping: dict[str, Any], preserve_radial: bool) -> None:
    lines = {row["line_id"]: row for row in topology["power_lines"]}
    choice = st.selectbox("Breaker", list(lines), format_func=lambda value: line_label(lines[value]), key=f"breaker_choice_{_version(topology)}")
    row = lines[choice]
    binding = next((row for row in mapping.get("line_bindings", []) if row["line_id"] == choice), None)
    st.caption(choice)
    with st.form(f"switch_{_version(topology)}_{choice}", border=False):
        closed = st.toggle("Initially closed", value=bool(row.get("closed", True)))
        normally_closed = st.toggle("Normally closed", value=bool(row.get("normally_closed", row.get("closed", True))))
        applied = st.form_submit_button("Apply breaker state", icon=":material/check:", type="primary", width="stretch")
    if applied:
        updated = update_switch(topology, choice, closed=closed, normally_closed=normally_closed)
        check = run_control_pipeline(topology_payload=updated, commands=[], preserve_radial=preserve_radial)
        if preserve_radial and check.final_power_plane["analysis"]["cycles"]:
            st.error("Initial state would form a closed loop. Open another breaker first.")
        else:
            _commit("topology_text", updated)
    first, second = st.columns(2)
    first.metric("Rating (kW)", row.get("capacity_kw", "-"))
    second.caption("Timed controller")
    second.write(str(binding["component_id"]) if binding else "Unmapped")


def _mapping_editor(mapping: dict[str, Any], topology: dict[str, Any]) -> None:
    lines = {row["line_id"]: row for row in topology["power_lines"]}
    bindings = mapping.get("line_bindings", [])
    bound = {row["line_id"]: row for row in bindings}
    st.caption(str(mapping.get("project_name", "PSCAD case")))
    st.dataframe(pd.DataFrame([
        {"Breaker": line_label(line), "Controller ID": str(bound[name]["component_id"]) if name in bound else "Unmapped", "Control": "Timed" if bound.get(name, {}).get("timed_control") else "Static"}
        for name, line in lines.items()
    ]), hide_index=True, width="stretch")
    if not bindings:
        st.warning("No breakers are mapped to PSCAD.")
        return
    with st.expander("Edit component binding"):
        choice = st.selectbox("Mapped breaker", list(bound), format_func=lambda value: line_label(lines[value]) if value in lines else value)
        with st.form(f"mapping_{_version(mapping)}_{choice}", border=False):
            identifier = st.number_input("PSCAD controller ID", min_value=1, value=int(bound[choice]["component_id"]), step=1)
            applied = st.form_submit_button("Apply binding", icon=":material/check:")
        if applied:
            _commit("mapping_text", update_binding(mapping, "line_bindings", choice, {"component_id": int(identifier)}))
    faults = mapping.get("fault_bindings", [])
    if faults:
        st.dataframe(pd.DataFrame([
            {"Bus": row["node_id"], "Fault ID": row["fault_id"], "Timing ID": str(row["logic_component_id"]), "Element ID": str(row["fault_component_id"])} for row in faults
        ]), hide_index=True, width="stretch")


def render_graphical_inputs(*, preserve_radial: bool, post_event_seconds: float) -> None:
    try:
        topology = json.loads(st.session_state.topology_text)
        commands = json.loads(st.session_state.command_text)
        mapping = json.loads(st.session_state.mapping_text)
        if not isinstance(topology, dict) or not isinstance(mapping, dict):
            raise ValueError("Topology and PSCAD mapping must be JSON objects.")
        if not topology.get("nodes") or not topology.get("power_lines"):
            raise ValueError("The graphical feeder requires buses and power_lines.")
        parsed = control_commands_from_payload(commands)
        preview = run_control_pipeline(
            topology_payload=topology, commands=parsed, preserve_radial=preserve_radial,
            simulation_mode="transient", post_event_window_s=post_event_seconds,
            physical_fault_payload=commands if isinstance(commands, dict) else None,
        ).to_dict()
    except (ValueError, KeyError, TypeError) as exc:
        st.error(f"Graphical inputs unavailable: {exc}")
        return

    left, right = st.columns([1.45, 1], gap="large")
    with left:
        st.subheader("Power Topology")
        view = st.segmented_control("Switch-state preview", ["Initial state", "Scheduled state"], default="Initial state", key="feeder_view")
        moment = None
        if view == "Scheduled state":
            duration = float(preview["switching_timeline"]["duration_s"])
            moment = st.slider("Preview time (s)", min_value=0.0, max_value=duration, value=duration, step=0.05, key=f"preview_time_{duration}")
        state = state_at(topology, preview, moment)
        selection = st.plotly_chart(
            feeder_figure(topology, state), width="stretch", on_select="rerun", selection_mode="points",
            key=f"feeder_{_version(topology)}_{view}_{moment}", config={"displayModeBar": False, "displaylogo": False},
        )
        points = selection.get("selection", {}).get("points", [])
        if points and points[0].get("customdata"):
            kind, identity = points[0]["customdata"]
            marker = (kind, identity, view, moment, _version(topology))
            if st.session_state.get("last_feeder_selection") != marker:
                st.session_state.last_feeder_selection = marker
                prefix = "breaker_choice" if kind == "line" else "bus_choice"
                st.session_state[f"{prefix}_{_version(topology)}"] = identity
        nodes = {row["node_id"]: row for row in topology["nodes"]}
        bus = st.selectbox("Bus", list(nodes), key=f"bus_choice_{_version(topology)}")
        details = st.columns(3)
        for column, label, value in [
            (details[0], "Role", "Source" if bus in state["sources"] else "Load bus"),
            (details[1], "Connectivity", "Connected" if bus in state["connected"] else "Isolated"),
            (details[2], "Incident lines", str(sum(bus in endpoints(line) for line in topology["power_lines"]))),
        ]:
            column.caption(label)
            column.write(value)
    with right:
        st.subheader("Experiment Controls")
        command_tab, fault_tab, switch_tab, map_tab = st.tabs(["Commands", "Faults", "Breakers", "Bindings"])
        with command_tab:
            _command_editor(commands, topology)
        with fault_tab:
            _fault_editor(commands, mapping)
        with switch_tab:
            _switch_editor(topology, mapping, preserve_radial)
        with map_tab:
            _mapping_editor(mapping, topology)

    st.subheader("Switching Schedule")
    st.plotly_chart(timeline_figure(topology, preview), width="stretch", config={"displayModeBar": False, "displaylogo": False})
    schedule = []
    for plan in preview["plans"]:
        command = plan["command"]
        schedule.append({
            "Time (s)": command["timestamp"], "Action": ACTION_LABELS[command["action"]],
            "Target": command.get("target_node_id") or command.get("target_line_id") or " > ".join(command.get("path", [])),
            "Validation": "Accepted" if plan["accepted"] else "Rejected / partial",
            "Details": "; ".join([*plan["warnings"], *(operation["reason"] for operation in plan["operations"] if not operation["accepted"])]) or command.get("reason", ""),
        })
    if schedule:
        st.dataframe(pd.DataFrame(schedule), hide_index=True, width="stretch")
