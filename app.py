"""Streamlit dashboard for the SEIAN Adaptive LoRa Mesh Topology Simulator."""

from __future__ import annotations

import json
from dataclasses import asdict

import pandas as pd
import streamlit as st

from seian_sim.config import SimulationConfig
from seian_sim.enums import EventCategory, FaultType, PacketType
from seian_sim.manual_simulation import ManualPacketSession
from seian_sim.network_builder import (
    BUILDER_TOOLS,
    DELETE_NODE,
    MOVE_NODE,
    PLACE_GATEWAY,
    PLACE_STANDARD,
    SELECT_NODE,
    apply_canvas_action,
    next_available_node_id,
    parse_plotly_canvas_event,
)
from seian_sim.packets import (
    PRIORITY_BACKGROUND,
    PRIORITY_CONTROL,
    PRIORITY_EMERGENCY,
    PRIORITY_FAULT,
    PRIORITY_TELEMETRY,
)
from seian_sim.scenarios import (
    SCENARIO_NAMES,
    build_empty_topology,
    build_from_topology,
    build_random_topology,
    build_scenario,
    export_topology,
)
from seian_sim.simulator import SeianMeshSimulator
from seian_sim.topology import analyze_topology, link_table, node_failure_impact, trace_route
from seian_sim.visualization import (
    drop_reason_figure,
    network_builder_figure,
    packet_trace_figure,
    time_series_figure,
    topology_figure,
)


st.set_page_config(page_title="SEIAN Mesh Topology Simulator", layout="wide")


def default_sim() -> SeianMeshSimulator:
    """Create the default dashboard simulator."""

    return build_scenario("Basic five-node mesh", SimulationConfig())


def make_config(
    *,
    seed: int,
    duration: float,
    area_width: float,
    area_height: float,
    lora_range: float,
    packet_loss: float,
    path_loss: float,
    heartbeat_min: float,
    neighbor_timeout: float,
) -> SimulationConfig:
    """Build validated simulation settings from sidebar controls."""

    config = SimulationConfig(
        random_seed=int(seed),
        duration_s=float(duration),
        area_width_m=float(area_width),
        area_height_m=float(area_height),
        heartbeat_min_s=float(heartbeat_min),
        neighbor_timeout_s=float(neighbor_timeout),
    )
    config.lora.max_range_m = float(lora_range)
    config.lora.packet_loss_probability = float(packet_loss)
    config.lora.path_loss_exponent = float(path_loss)
    config.validate()
    return config


def reset_builder_state() -> None:
    """Reset interactive-canvas state after replacing the network."""

    st.session_state.builder_selected_node = None
    st.session_state.builder_placed_order = []
    st.session_state.builder_canvas_version = st.session_state.get("builder_canvas_version", 0) + 1
    st.session_state.packet_trace = None


def set_builder_notice(level: str, message: str) -> None:
    st.session_state.builder_notice = (level, message)


def show_builder_notice() -> None:
    notice = st.session_state.pop("builder_notice", None)
    if not notice:
        return
    level, message = notice
    if level == "success":
        st.success(message)
    elif level == "error":
        st.error(message)
    elif level == "warning":
        st.warning(message)
    else:
        st.info(message)


if "sim" not in st.session_state:
    st.session_state.sim = default_sim()
if "builder_selected_node" not in st.session_state:
    st.session_state.builder_selected_node = None
if "builder_placed_order" not in st.session_state:
    st.session_state.builder_placed_order = []
if "builder_canvas_version" not in st.session_state:
    st.session_state.builder_canvas_version = 0
if "packet_trace" not in st.session_state:
    st.session_state.packet_trace = None

st.title("SEIAN Adaptive LoRa Mesh Topology Simulator")
st.caption(
    "Create a custom network by clicking on a canvas, then check physical connectivity, "
    "SEIAN-AMRP routes, gateway reachability, fault propagation, and rerouting. "
    "This simulator does not control real electrical equipment."
)

with st.sidebar:
    st.header("Network Setup")
    scenario_options = ["Create own network", "Random topology", *SCENARIO_NAMES]
    scenario = st.selectbox("Scenario", scenario_options, index=2)
    node_count = st.slider("Random node count", 1, 60, max(5, len(st.session_state.sim.nodes)))
    gateway_count = st.slider("Random gateway count", 0, 4, 1)
    duration = st.slider("Simulation duration (s)", 10, 900, 120, step=10)
    seed = st.number_input("Random seed", value=42, step=1)
    area_width = st.number_input("Area width (m)", value=600.0, min_value=50.0)
    area_height = st.number_input("Area height (m)", value=360.0, min_value=50.0)
    lora_range = st.number_input("Approximate LoRa range (m)", value=260.0, min_value=20.0)
    packet_loss = st.slider("Packet-loss probability", 0.0, 0.6, 0.03, step=0.01)
    path_loss = st.slider("Path-loss exponent", 1.2, 4.5, 2.1, step=0.1)
    heartbeat_min = st.number_input("Heartbeat minimum (s)", value=10.0, min_value=1.0)
    neighbor_timeout = st.number_input("Neighbor timeout (s)", value=60.0, min_value=5.0)
    simulation_step = st.slider("Batch step size (s)", 1, 60, 10)

    config = make_config(
        seed=int(seed),
        duration=float(duration),
        area_width=float(area_width),
        area_height=float(area_height),
        lora_range=float(lora_range),
        packet_loss=float(packet_loss),
        path_loss=float(path_loss),
        heartbeat_min=float(heartbeat_min),
        neighbor_timeout=float(neighbor_timeout),
    )

    if st.button("Create / Reset Network", type="primary", use_container_width=True):
        if scenario == "Create own network":
            st.session_state.sim = build_empty_topology(config)
            set_builder_notice(
                "success",
                "Empty network created. Open Network Builder and click the canvas to place nodes.",
            )
        elif scenario == "Random topology":
            st.session_state.sim = build_random_topology(
                int(node_count), config, gateway_count=int(gateway_count)
            )
        else:
            st.session_state.sim = build_scenario(scenario, config)
        reset_builder_state()
        st.rerun()

    uploaded_topology = st.file_uploader("Load topology JSON", type=["json"])
    if st.button(
        "Load Uploaded Topology",
        use_container_width=True,
        disabled=uploaded_topology is None,
    ):
        try:
            data = json.loads(uploaded_topology.getvalue().decode("utf-8"))
            st.session_state.sim = build_from_topology(data, config)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            st.error(f"Could not load topology: {exc}")
        else:
            reset_builder_state()
            st.rerun()

    st.divider()
    st.header("Exact Coordinate Editor")
    current_ids = sorted(st.session_state.sim.nodes)
    sidebar_selected_node = st.selectbox("Selected node", current_ids or [""], index=0)
    sidebar_selected = st.session_state.sim.nodes.get(sidebar_selected_node)

    suggested_id = next_available_node_id(current_ids)
    manual_id = st.text_input("New node ID", value=suggested_id)
    manual_x = st.number_input(
        "Node X (m)",
        value=float(sidebar_selected.position_x if sidebar_selected else 100.0),
        min_value=0.0,
        max_value=float(area_width),
    )
    manual_y = st.number_input(
        "Node Y (m)",
        value=float(sidebar_selected.position_y if sidebar_selected else 100.0),
        min_value=0.0,
        max_value=float(area_height),
    )
    manual_gateway = st.checkbox("New node is an online gateway")

    if st.button("Add Node by Coordinates", use_container_width=True):
        sim_for_edit = st.session_state.sim
        if not manual_id.strip():
            st.error("Node ID cannot be empty.")
        elif manual_id.strip() in sim_for_edit.nodes:
            st.error("That Node ID already exists.")
        else:
            sim_for_edit.add_node(
                manual_id.strip(),
                float(manual_x),
                float(manual_y),
                gateway_capable=manual_gateway,
                gateway_online=manual_gateway,
            )
            sim_for_edit.discover_neighbors()
            st.session_state.builder_selected_node = manual_id.strip()
            st.session_state.builder_placed_order.append(manual_id.strip())
            st.rerun()

    edit_cols = st.columns(2)
    if sidebar_selected_node and edit_cols[0].button("Move Node", use_container_width=True):
        st.session_state.sim.move_node(sidebar_selected_node, float(manual_x), float(manual_y))
        st.session_state.builder_selected_node = sidebar_selected_node
        st.rerun()
    if sidebar_selected_node and edit_cols[1].button("Remove Node", use_container_width=True):
        st.session_state.sim.remove_node(sidebar_selected_node)
        if st.session_state.builder_selected_node == sidebar_selected_node:
            st.session_state.builder_selected_node = None
        st.rerun()

    if st.button("Discover Neighbors / Rebuild Routes", use_container_width=True):
        st.session_state.sim.discover_neighbors()
        st.rerun()

    st.divider()
    st.header("Simulation Actions")
    if st.button("Run Batch", use_container_width=True):
        st.session_state.sim.run(float(duration), float(simulation_step))
        st.rerun()
    if st.button("Advance One Step", use_container_width=True):
        st.session_state.sim.run(float(simulation_step), float(simulation_step))
        st.rerun()

    fault_type = st.selectbox("Fault type", [fault.value for fault in FaultType])
    severity = st.selectbox(
        "Fault severity", ["minor", "moderate", "severe", "emergency"], index=2
    )
    if sidebar_selected_node and st.button("Inject Fault", use_container_width=True):
        st.session_state.sim.inject_fault(
            sidebar_selected_node, FaultType(fault_type), severity=severity
        )
        st.session_state.sim.process_queues()
        st.rerun()

    action_cols = st.columns(2)
    if sidebar_selected_node and action_cols[0].button("Fail Node", use_container_width=True):
        st.session_state.sim.fail_node(sidebar_selected_node)
        st.rerun()
    if sidebar_selected_node and action_cols[1].button("Recover Node", use_container_width=True):
        st.session_state.sim.recover_node(sidebar_selected_node)
        st.rerun()

    gateway_cols = st.columns(2)
    if sidebar_selected_node and gateway_cols[0].button("Gateway Off", use_container_width=True):
        st.session_state.sim.set_gateway(sidebar_selected_node, False)
        st.rerun()
    if sidebar_selected_node and gateway_cols[1].button("Gateway On", use_container_width=True):
        st.session_state.sim.set_gateway(sidebar_selected_node, True)
        st.rerun()

sim: SeianMeshSimulator = st.session_state.sim
node_ids = sorted(sim.nodes)
builder_selected = st.session_state.builder_selected_node
if builder_selected not in sim.nodes:
    builder_selected = None
    st.session_state.builder_selected_node = None
selected_node = builder_selected or (
    sidebar_selected_node if sidebar_selected_node in sim.nodes else (node_ids[0] if node_ids else "")
)
summary = sim.metrics.summary()
topology_report = analyze_topology(sim)

headline = st.columns(6)
headline[0].metric("Active nodes", topology_report["active_node_count"])
headline[1].metric("Physical links", topology_report["link_count"])
headline[2].metric("Components", topology_report["component_count"])
headline[3].metric("Critical relays", len(topology_report["articulation_points"]))
headline[4].metric("Gateway-unreachable", len(topology_report["gateway_unreachable_nodes"]))
headline[5].metric("Packet delivery", f"{summary['packet_delivery_ratio']:.1%}")

(
    tab_builder,
    tab_packet,
    tab_topology,
    tab_node,
    tab_metrics,
    tab_charts,
    tab_events,
    tab_exports,
) = st.tabs(
    [
        "Network Builder",
        "Packet Simulation",
        "Topology Check",
        "Node Details",
        "Protocol Metrics",
        "Grid Charts",
        "Event Log",
        "Export Results",
    ]
)

with tab_builder:
    st.subheader("Create Your Own SEIAN Mesh")
    show_builder_notice()
    st.write(
        "Choose a tool and click the canvas. Standard nodes are circular; online gateways are "
        "blue diamonds. Links are rebuilt automatically using the configured LoRa range."
    )

    control_col, canvas_col = st.columns([1, 3])
    with control_col:
        builder_tool = st.radio("Canvas tool", BUILDER_TOOLS, index=0)
        snap_m = st.select_slider(
            "Placement snap (m)",
            options=[5.0, 10.0, 20.0, 25.0, 50.0],
            value=10.0,
        )
        show_radio_range = st.checkbox("Show LoRa coverage circles", value=False)
        use_custom_id = st.checkbox("Use a custom ID for next node", value=False)
        custom_node_id = st.text_input(
            "Next node ID",
            value=next_available_node_id(sim.nodes),
            disabled=not use_custom_id,
            help="Used only by the two placement tools.",
        )
        selected_builder_node = st.session_state.builder_selected_node
        st.metric("Selected node", selected_builder_node or "None")

        if builder_tool == PLACE_STANDARD:
            st.info("Every canvas click places one standard inverter node.")
        elif builder_tool == PLACE_GATEWAY:
            st.info("Every canvas click places one online gateway-capable node.")
        elif builder_tool == SELECT_NODE:
            st.info("Click directly on a node to select it.")
        elif builder_tool == MOVE_NODE:
            st.info("Select a node first, then click its new canvas position.")
        elif builder_tool == DELETE_NODE:
            st.warning("Click directly on the node that should be deleted.")

        button_left, button_right = st.columns(2)
        if button_left.button("Undo Place", use_container_width=True):
            placed_order = st.session_state.builder_placed_order
            while placed_order and placed_order[-1] not in sim.nodes:
                placed_order.pop()
            if not placed_order:
                set_builder_notice("warning", "There is no canvas-placed node to undo.")
            else:
                node_to_remove = placed_order.pop()
                sim.remove_node(node_to_remove)
                if st.session_state.builder_selected_node == node_to_remove:
                    st.session_state.builder_selected_node = None
                set_builder_notice("success", f"Removed the last placed node: {node_to_remove}.")
                st.session_state.builder_canvas_version += 1
            st.rerun()

        if button_right.button("Clear All", use_container_width=True):
            st.session_state.sim = build_empty_topology(sim.config)
            reset_builder_state()
            set_builder_notice("success", "Canvas cleared. Click to place a new network.")
            st.rerun()

        if st.button("Rebuild Links and Routes", use_container_width=True):
            sim.discover_neighbors()
            set_builder_notice("success", "Neighbor discovery and route calculation completed.")
            st.session_state.builder_canvas_version += 1
            st.rerun()

        st.caption(
            f"Canvas: {sim.config.area_width_m:.0f} × {sim.config.area_height_m:.0f} m | "
            f"LoRa range: {sim.config.lora.max_range_m:.0f} m | Nodes: {len(sim.nodes)}"
        )

    with canvas_col:
        canvas_event = st.plotly_chart(
            network_builder_figure(
                sim,
                selected_node=st.session_state.builder_selected_node,
                snap_m=float(snap_m),
                show_radio_range=show_radio_range,
            ),
            use_container_width=True,
            key=f"builder_canvas_{st.session_state.builder_canvas_version}",
            on_select="rerun",
            selection_mode="points",
            config={
                "displaylogo": False,
                "scrollZoom": True,
                "modeBarButtonsToRemove": ["lasso2d", "select2d"],
            },
        )

    click = parse_plotly_canvas_event(canvas_event)
    if click is not None:
        requested_id = custom_node_id.strip() if use_custom_id else None
        result = apply_canvas_action(
            sim,
            builder_tool,
            click,
            selected_node_id=st.session_state.builder_selected_node,
            requested_node_id=requested_id,
        )
        if result.added_node_id:
            st.session_state.builder_placed_order.append(result.added_node_id)
        if result.removed_node_id:
            st.session_state.builder_placed_order = [
                node_id
                for node_id in st.session_state.builder_placed_order
                if node_id != result.removed_node_id
            ]
        st.session_state.builder_selected_node = result.selected_node_id
        set_builder_notice("success" if result.changed else "warning", result.message)
        # Recreate the Plotly component so the same selected point is not processed twice.
        st.session_state.builder_canvas_version += 1
        st.rerun()

    if sim.nodes:
        builder_table = [
            {
                "node_id": node.node_id,
                "type": "Gateway" if node.gateway_online else "Standard",
                "x_m": round(node.position_x, 2),
                "y_m": round(node.position_y, 2),
                "neighbors": len(node.neighbor_table),
                "active": node.active,
            }
            for node in sim.nodes.values()
        ]
        st.dataframe(pd.DataFrame(builder_table), use_container_width=True, hide_index=True)
    else:
        st.info("The canvas is empty. Select Place standard node or Place gateway node and click.")


with tab_packet:
    st.subheader("Packet Tracer-Style Simulation Mode")
    st.write(
        "Create one SEIAN-AMRP packet, then press **Forward** to execute exactly one "
        "physical link transmission. The simulator does not automatically continue to the next hop."
    )

    if len(node_ids) < 2:
        st.warning("Create at least two connected nodes before starting a packet trace.")
    else:
        control_left, control_middle, control_right = st.columns(3)
        with control_left:
            trace_source = st.selectbox("Packet source", node_ids, key="trace_source")
            destination_options = ["BROADCAST", *[node_id for node_id in node_ids if node_id != trace_source]]
            trace_destination_label = st.selectbox(
                "Packet destination",
                destination_options,
                key="trace_destination",
            )
            trace_destination = None if trace_destination_label == "BROADCAST" else trace_destination_label
        with control_middle:
            packet_type_value = st.selectbox(
                "Packet type",
                [packet_type.value for packet_type in PacketType],
                index=[packet_type.value for packet_type in PacketType].index(PacketType.GRID_STATE_UPDATE.value),
                key="trace_packet_type",
            )
            trace_ttl = st.slider("TTL", 1, int(sim.config.max_hops), min(6, int(sim.config.max_hops)))
            fault_acks = st.checkbox(
                "Generate FAULT_ACK packets",
                value=True,
                disabled=packet_type_value != PacketType.FAULT_ALERT.value,
            )
        with control_right:
            priority_options = {
                "Background (0)": PRIORITY_BACKGROUND,
                "Telemetry (1)": PRIORITY_TELEMETRY,
                "Control (2)": PRIORITY_CONTROL,
                "Fault (3)": PRIORITY_FAULT,
                "Emergency (4)": PRIORITY_EMERGENCY,
            }
            default_priority_index = 3 if packet_type_value == PacketType.FAULT_ALERT.value else 1
            priority_label = st.selectbox(
                "Priority",
                list(priority_options),
                index=default_priority_index,
                key="trace_priority",
            )
            payload_text = st.text_area(
                "Payload (JSON)",
                value='{"voltage": 230.0, "frequency": 50.0}',
                height=105,
                key="trace_payload",
            )

        start_col, forward_col, reset_col = st.columns(3)
        if start_col.button("Create Packet", type="primary", use_container_width=True):
            try:
                payload = json.loads(payload_text) if payload_text.strip() else {}
                if not isinstance(payload, dict):
                    raise ValueError("Payload JSON must be an object, for example {\"voltage\": 230}.")
                st.session_state.packet_trace = ManualPacketSession.create(
                    sim,
                    source_id=trace_source,
                    destination_id=trace_destination,
                    packet_type=PacketType(packet_type_value),
                    priority=priority_options[priority_label],
                    ttl=int(trace_ttl),
                    payload=payload,
                    generate_fault_acks=bool(fault_acks),
                )
            except (ValueError, json.JSONDecodeError) as exc:
                st.error(f"Could not create packet: {exc}")
            else:
                st.rerun()

        trace: ManualPacketSession | None = st.session_state.packet_trace
        if forward_col.button(
            "Forward ▶",
            use_container_width=True,
            disabled=trace is None or trace.pending_count == 0,
            help="Executes exactly one waiting transmission event.",
        ):
            trace.forward_one(sim)
            st.rerun()

        if reset_col.button("Reset Trace", use_container_width=True, disabled=trace is None):
            st.session_state.packet_trace = None
            st.rerun()

        trace = st.session_state.packet_trace
        if trace is None:
            st.info("Configure a packet and press Create Packet. Nothing will move until Forward is pressed.")
        else:
            packet = trace.packet
            header_cols = st.columns(6)
            header_cols[0].metric("Sequence", packet.sequence_number)
            header_cols[1].metric("Priority", packet.priority)
            header_cols[2].metric("TTL", packet.ttl)
            header_cols[3].metric("Completed events", len(trace.history))
            header_cols[4].metric("Waiting events", trace.pending_count)
            header_cols[5].metric("Receivers", len(trace.delivered_nodes))

            if trace.complete:
                if trace.destination_id is None or trace.destination_id in trace.delivered_nodes:
                    st.success(trace.completion_message)
                else:
                    st.error(trace.completion_message)
            else:
                st.info(trace.completion_message)

            st.plotly_chart(
                packet_trace_figure(sim, trace),
                use_container_width=True,
                key=f"packet_trace_{len(trace.history)}_{trace.pending_count}",
                config={"displaylogo": False, "scrollZoom": True},
            )

            if trace.last_step:
                last = trace.last_step
                if last.status == "DROPPED":
                    st.error(f"Step {last.step}: {last.sender_id} → {last.receiver_id}: {last.message}")
                elif last.status in {"DELIVERED", "RECEIVED", "FORWARDED"}:
                    st.success(f"Step {last.step}: {last.sender_id} → {last.receiver_id}: {last.message}")
                else:
                    st.warning(f"Step {last.step}: {last.message}")

            table_left, table_right = st.columns(2)
            with table_left:
                st.write("Waiting event queue")
                pending_rows = trace.pending_rows()
                if pending_rows:
                    st.dataframe(pd.DataFrame(pending_rows), use_container_width=True, hide_index=True)
                else:
                    st.caption("No waiting transmissions.")
            with table_right:
                st.write("Packet header")
                st.json(
                    {
                        "version": packet.version,
                        "packet_type": packet.packet_type.value,
                        "source_id": packet.source_id,
                        "origin_id": packet.origin_id,
                        "destination_id": packet.destination_id or "BROADCAST",
                        "sequence_number": packet.sequence_number,
                        "priority": packet.priority,
                        "hop_count": packet.hop_count,
                        "ttl": packet.ttl,
                        "network_id": packet.network_id,
                        "payload_length": packet.payload_length,
                        "payload": packet.payload,
                    }
                )

            st.write("Event history")
            history_rows = trace.history_rows()
            if history_rows:
                st.dataframe(pd.DataFrame(history_rows), use_container_width=True, hide_index=True)
            else:
                st.caption("Packet created. Press Forward to produce the first event.")

with tab_topology:
    route_path: list[str] = []
    if node_ids:
        route_cols = st.columns(3)
        source_index = node_ids.index(selected_node) if selected_node in node_ids else 0
        route_source = route_cols[0].selectbox(
            "Route source", node_ids, index=source_index, key="route_source"
        )
        online_gateways = topology_report["online_gateways"]
        default_destination = online_gateways[0] if online_gateways else node_ids[-1]
        route_destination = route_cols[1].selectbox(
            "Route destination",
            node_ids,
            index=node_ids.index(default_destination),
            key="route_destination",
        )
        show_packets = route_cols[2].checkbox("Show recent packets", value=True)
        route_path = trace_route(sim, route_source, route_destination)
        if route_source == route_destination:
            st.info("Source and destination are the same node.")
        elif route_path:
            first_entry = sim.nodes[route_source].routing_table.get(route_destination)
            route_cost_value = first_entry.route_cost if first_entry else 0.0
            st.success(
                f"Selected route: {' → '.join(route_path)} | "
                f"{len(route_path) - 1} hop(s) | route cost {route_cost_value:.3f}"
            )
        else:
            st.error(f"No valid route from {route_source} to {route_destination}.")
    else:
        show_packets = False
        st.warning("Create or load nodes to begin topology checking.")

    st.plotly_chart(
        topology_figure(
            sim,
            selected_node,
            show_packets=show_packets,
            packet_window_s=45.0,
            highlight_path=route_path,
            critical_nodes=set(topology_report["articulation_points"]),
        ),
        use_container_width=True,
    )

    health_cols = st.columns(4)
    health_cols[0].metric("Connected mesh", "Yes" if topology_report["connected"] else "No")
    health_cols[1].metric("Average degree", topology_report["average_degree"])
    health_cols[2].metric("Mesh density", topology_report["density"])
    health_cols[3].metric(
        "Largest diameter",
        f"{topology_report['largest_component_diameter_hops']} hops",
    )

    st.subheader("Topology Findings")
    if not topology_report["issues"]:
        st.success("No structural topology issue was detected in the current active mesh.")
    for issue in topology_report["issues"]:
        node_text = f" Nodes: {', '.join(issue['nodes'])}." if issue["nodes"] else ""
        message = f"{issue['code']}: {issue['message']}{node_text}"
        if issue["severity"] == "error":
            st.error(message)
        elif issue["severity"] == "warning":
            st.warning(message)
        else:
            st.info(message)

    detail_left, detail_right = st.columns(2)
    with detail_left:
        st.subheader("Physical Link Table")
        st.dataframe(pd.DataFrame(link_table(sim)), use_container_width=True, hide_index=True)
    with detail_right:
        st.subheader("Single-Node Failure Impact")
        st.dataframe(
            pd.DataFrame(node_failure_impact(sim)),
            use_container_width=True,
            hide_index=True,
        )

with tab_node:
    node = sim.nodes.get(selected_node) if selected_node else None
    if node:
        st.subheader(node.node_id)
        st.json(
            {
                "role": node.role.value,
                "active": node.active,
                "gateway_capable": node.gateway_capable,
                "gateway_online": node.gateway_online,
                "position_x_m": round(node.position_x, 2),
                "position_y_m": round(node.position_y, 2),
                "voltage_rms": round(node.voltage_rms, 2),
                "frequency_hz": round(node.frequency_hz, 3),
                "load_percent": round(node.load_percent, 2),
                "temperature_c": round(node.temperature_c, 2),
                "fault_state": node.fault_status.value,
                "health_score": round(node.health_score, 3),
                "gateway_distance": node.gateway_distance,
                "cached_gateway_telemetry": len(node.cached_gateway_telemetry),
            }
        )
        st.write("Neighbor table")
        st.dataframe(
            pd.DataFrame([asdict(entry) for entry in node.neighbor_table.values()]),
            use_container_width=True,
            hide_index=True,
        )
        st.write("Routing table")
        st.dataframe(
            pd.DataFrame([asdict(entry) for entry in node.routing_table.values()]),
            use_container_width=True,
            hide_index=True,
        )
        st.write("Recent packets")
        st.dataframe(
            pd.DataFrame(
                node.recent_received_packets[-25:] + node.recent_transmitted_packets[-25:]
            ),
            use_container_width=True,
            hide_index=True,
        )
        st.write("Packet-drop reasons")
        st.json(node.packet_drop_reasons)
    else:
        st.info("Select or create a node to view its details.")

with tab_metrics:
    st.json(summary)

with tab_charts:
    frames = sim.export_dataframes()
    measurements = frames["measurements"]
    chart_left, chart_right = st.columns(2)
    chart_left.plotly_chart(
        time_series_figure(measurements, "voltage_rms", "Voltage over time"),
        use_container_width=True,
    )
    chart_right.plotly_chart(
        time_series_figure(measurements, "frequency_hz", "Frequency over time"),
        use_container_width=True,
    )
    chart_left.plotly_chart(
        time_series_figure(measurements, "load_percent", "Node load over time"),
        use_container_width=True,
    )
    chart_right.plotly_chart(
        time_series_figure(measurements, "temperature_c", "Temperature over time"),
        use_container_width=True,
    )
    st.plotly_chart(drop_reason_figure(sim), use_container_width=True)

with tab_events:
    categories = ["all", *[category.value for category in EventCategory]]
    category_filter = st.selectbox("Event category", categories)
    events_df = sim.export_dataframes()["events"]
    if not events_df.empty and category_filter != "all":
        events_df = events_df[events_df["category"] == category_filter]
    st.dataframe(events_df.tail(500), use_container_width=True, hide_index=True)

with tab_exports:
    frames = sim.export_dataframes()
    tables = sim.export_tables_json()
    st.download_button(
        "Topology JSON",
        json.dumps(export_topology(sim), indent=2),
        "seian_topology.json",
        mime="application/json",
    )
    st.download_button(
        "Topology analysis JSON",
        json.dumps(topology_report, indent=2),
        "topology_analysis.json",
        mime="application/json",
    )
    st.download_button(
        "Physical links CSV",
        pd.DataFrame(link_table(sim)).to_csv(index=False),
        "physical_links.csv",
        mime="text/csv",
    )
    st.download_button(
        "Node failure impact CSV",
        pd.DataFrame(node_failure_impact(sim)).to_csv(index=False),
        "node_failure_impact.csv",
        mime="text/csv",
    )
    st.download_button(
        "Node measurements CSV",
        frames["measurements"].to_csv(index=False),
        "node_measurements.csv",
        mime="text/csv",
    )
    st.download_button(
        "Packet events CSV",
        frames["packet_events"].to_csv(index=False),
        "packet_events.csv",
        mime="text/csv",
    )
    st.download_button(
        "Route history CSV",
        frames["route_history"].to_csv(index=False),
        "route_history.csv",
        mime="text/csv",
    )
    st.download_button(
        "Fault events CSV",
        frames["fault_events"].to_csv(index=False),
        "fault_events.csv",
        mime="text/csv",
    )
    st.download_button(
        "Neighbor tables JSON",
        json.dumps(tables["neighbor_tables"], indent=2),
        "neighbor_tables.json",
        mime="application/json",
    )
    st.download_button(
        "Routing tables JSON",
        json.dumps(tables["routing_tables"], indent=2),
        "routing_tables.json",
        mime="application/json",
    )
