"""Plotly visualization helpers for the Streamlit dashboard."""

from __future__ import annotations

import networkx as nx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from seian_sim.enums import FaultStatus
from seian_sim.simulator import SeianMeshSimulator


def topology_figure(
    sim: SeianMeshSimulator,
    selected_node: str | None = None,
    show_packets: bool = True,
    packet_window_s: float = 30.0,
    packet_type_filter: list[str] | None = None,
    highlight_path: list[str] | None = None,
    critical_nodes: set[str] | None = None,
) -> go.Figure:
    """Build a network topology figure with links, node status, and tooltips."""

    graph = nx.Graph()
    for node in sim.nodes.values():
        graph.add_node(node.node_id)
        for neighbor_id in node.neighbor_table:
            if neighbor_id in sim.nodes:
                graph.add_edge(node.node_id, neighbor_id)
    edge_x: list[float] = []
    edge_y: list[float] = []
    for a, b in graph.edges:
        na, nb = sim.nodes[a], sim.nodes[b]
        edge_x.extend([na.position_x, nb.position_x, None])
        edge_y.extend([na.position_y, nb.position_y, None])
    node_x = [n.position_x for n in sim.nodes.values()]
    node_y = [n.position_y for n in sim.nodes.values()]
    colors = [_color_for_node(n) for n in sim.nodes.values()]
    critical_nodes = critical_nodes or set()
    sizes = [
        22 if n.node_id == selected_node else 18 if n.node_id in critical_nodes else 15 if n.gateway_online else 11
        for n in sim.nodes.values()
    ]
    text = [
        (
            f"{n.node_id}<br>{n.role.value}<br>Health {n.health_score:.2f}<br>"
            f"V {n.voltage_rms:.1f} V<br>F {n.frequency_hz:.2f} Hz<br>"
            f"Load {n.load_percent:.1f}%<br>Temp {n.temperature_c:.1f} C<br>"
            f"Fault {n.fault_status.value}<br>Gateway hops {n.gateway_distance}<br>"
            f"Queue {len(n.packet_queue)}"
        )
        for n in sim.nodes.values()
    ]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines", line=dict(width=1, color="#9aa4b2"), hoverinfo="skip"))

    if highlight_path and len(highlight_path) > 1:
        route_x: list[float | None] = []
        route_y: list[float | None] = []
        for node_a, node_b in zip(highlight_path, highlight_path[1:]):
            if node_a not in sim.nodes or node_b not in sim.nodes:
                continue
            route_x.extend([sim.nodes[node_a].position_x, sim.nodes[node_b].position_x, None])
            route_y.extend([sim.nodes[node_a].position_y, sim.nodes[node_b].position_y, None])
        fig.add_trace(go.Scatter(
            x=route_x,
            y=route_y,
            mode="lines",
            line=dict(width=5, color="#7c3aed"),
            hoverinfo="skip",
            name="Selected route",
        ))

    fig.add_trace(go.Scatter(
        x=node_x,
        y=node_y,
        mode="markers+text",
        text=[n.node_id for n in sim.nodes.values()],
        textposition="top center",
        marker=dict(size=sizes, color=colors, line=dict(width=1, color="#1f2937")),
        hovertext=text,
        hoverinfo="text",
    ))

    if show_packets and sim.packet_events:
        min_time = sim.now - packet_window_s
        packet_rows = [
            row for row in sim.packet_events
            if row.get("delivered")
            and row.get("source_x") is not None
            and row.get("timestamp", 0) >= min_time
            and (not packet_type_filter or row.get("packet_type") in packet_type_filter)
        ]

        colors = {
            "HELLO": "#64748b",
            "HELLO_REPLY": "#94a3b8",
            "HEARTBEAT": "#2563eb",
            "GRID_STATE_UPDATE": "#16a34a",
            "ROUTE_ADVERTISEMENT": "#0f766e",
            "FAULT_ALERT": "#dc2626",
            "FAULT_ACK": "#f59e0b",
            "CONTROL_COORDINATION": "#7c3aed",
            "GATEWAY_ANNOUNCE": "#0284c7",
            "ROUTE_ERROR": "#111827",
        }

        for row in packet_rows[-80:]:
            packet_type = row["packet_type"]
            fig.add_trace(go.Scatter(
                x=[row["source_x"], row["receiver_x"]],
                y=[row["source_y"], row["receiver_y"]],
                mode="lines+markers",
                line=dict(
                    width=1.5 + float(row.get("priority") or 0),
                    color=colors.get(packet_type, "#334155"),
                    dash="solid",
                ),
                marker=dict(size=[5, 9], symbol=["circle", "triangle-right"]),
                hovertext=(
                    f"{packet_type}<br>"
                    f"{row['source_id']} -> {row['receiver_id']}<br>"
                    f"Priority {row.get('priority')}<br>"
                    f"t={row['timestamp']:.1f}s"
                ),
                hoverinfo="text",
                showlegend=False,
            ))

    fig.update_layout(
        margin=dict(l=10, r=10, t=25, b=10),
        xaxis=dict(range=[0, sim.config.area_width_m], showgrid=True, zeroline=False),
        yaxis=dict(range=[0, sim.config.area_height_m], showgrid=True, zeroline=False, scaleanchor="x", scaleratio=1),
        height=520,
    )
    return fig


def network_builder_figure(
    sim: SeianMeshSimulator,
    *,
    selected_node: str | None = None,
    snap_m: float = 10.0,
    show_radio_range: bool = False,
) -> go.Figure:
    """Build a clickable placement canvas for constructing a custom mesh.

    A lightly visible point grid is placed behind the topology. Streamlit's Plotly
    ``on_select`` event returns the nearest grid coordinate when the user clicks.
    Existing nodes carry custom data so select/delete tools can identify them.
    """

    width = float(sim.config.area_width_m)
    height = float(sim.config.area_height_m)
    effective_snap = max(1.0, float(snap_m))

    # Keep the invisible click-target grid responsive even for very large areas.
    estimated_points = (int(width / effective_snap) + 1) * (int(height / effective_snap) + 1)
    if estimated_points > 6000:
        scale = (estimated_points / 6000.0) ** 0.5
        effective_snap *= scale

    x_values = _axis_values(width, effective_snap)
    y_values = _axis_values(height, effective_snap)
    grid_x = [x for y in y_values for x in x_values]
    grid_y = [y for y in y_values for x in x_values]
    grid_customdata = [["canvas", ""] for _ in grid_x]

    fig = go.Figure()
    fig.add_trace(
        go.Scattergl(
            x=grid_x,
            y=grid_y,
            mode="markers",
            marker=dict(size=18, opacity=0.015, color="#64748b"),
            customdata=grid_customdata,
            hovertemplate="Canvas (%{x:.1f}, %{y:.1f}) m<extra></extra>",
            name="Placement canvas",
            showlegend=False,
        )
    )

    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    seen_edges: set[tuple[str, str]] = set()
    for node in sim.nodes.values():
        for neighbor_id in node.neighbor_table:
            if neighbor_id not in sim.nodes:
                continue
            edge = tuple(sorted((node.node_id, neighbor_id)))
            if edge in seen_edges:
                continue
            seen_edges.add(edge)
            neighbor = sim.nodes[neighbor_id]
            edge_x.extend([node.position_x, neighbor.position_x, None])
            edge_y.extend([node.position_y, neighbor.position_y, None])

    fig.add_trace(
        go.Scatter(
            x=edge_x,
            y=edge_y,
            mode="lines",
            line=dict(width=2, color="#94a3b8"),
            hoverinfo="skip",
            name="Discovered LoRa link",
        )
    )

    nodes = list(sim.nodes.values())
    node_hover = [
        (
            f"{node.node_id}<br>{node.role.value}<br>"
            f"Position ({node.position_x:.1f}, {node.position_y:.1f}) m<br>"
            f"Neighbors {len(node.neighbor_table)}<br>"
            f"Gateway {'online' if node.gateway_online else 'no'}"
        )
        for node in nodes
    ]
    node_sizes = [25 if node.node_id == selected_node else 20 if node.gateway_online else 17 for node in nodes]
    node_symbols = ["diamond" if node.gateway_online else "circle" for node in nodes]
    fig.add_trace(
        go.Scatter(
            x=[node.position_x for node in nodes],
            y=[node.position_y for node in nodes],
            mode="markers+text",
            text=[node.node_id for node in nodes],
            textposition="top center",
            marker=dict(
                size=node_sizes,
                symbol=node_symbols,
                color=[_color_for_node(node) for node in nodes],
                line=dict(width=2, color="#0f172a"),
            ),
            customdata=[["node", node.node_id] for node in nodes],
            hovertext=node_hover,
            hoverinfo="text",
            name="SEIAN nodes",
        )
    )

    if selected_node in sim.nodes:
        node = sim.nodes[selected_node]
        fig.add_trace(
            go.Scatter(
                x=[node.position_x],
                y=[node.position_y],
                mode="markers",
                marker=dict(
                    size=36,
                    symbol="circle-open",
                    color="#7c3aed",
                    line=dict(width=4, color="#7c3aed"),
                ),
                hoverinfo="skip",
                showlegend=False,
            )
        )

    if show_radio_range:
        radius = float(sim.config.lora.max_range_m)
        for node in nodes:
            if not node.active:
                continue
            fig.add_shape(
                type="circle",
                x0=node.position_x - radius,
                x1=node.position_x + radius,
                y0=node.position_y - radius,
                y1=node.position_y + radius,
                line=dict(width=1, dash="dot", color="#60a5fa"),
                fillcolor="rgba(96, 165, 250, 0.03)",
                layer="below",
            )

    fig.update_layout(
        title=(
            "Click the canvas to place or move nodes. Click an existing node for select/delete tools."
        ),
        margin=dict(l=10, r=10, t=55, b=10),
        xaxis=dict(
            title="X position (m)",
            range=[0, width],
            showgrid=True,
            zeroline=False,
            fixedrange=False,
        ),
        yaxis=dict(
            title="Y position (m)",
            range=[0, height],
            showgrid=True,
            zeroline=False,
            scaleanchor="x",
            scaleratio=1,
            fixedrange=False,
        ),
        height=610,
        clickmode="event+select",
        dragmode="pan",
        hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
        selectionrevision=0,
    )
    return fig


def _axis_values(limit: float, step: float) -> list[float]:
    values: list[float] = []
    current = 0.0
    while current < limit:
        values.append(round(current, 6))
        current += step
    if not values or values[-1] != limit:
        values.append(limit)
    return values


def time_series_figure(df: pd.DataFrame, y: str, title: str) -> go.Figure:
    """Build a node-colored time-series chart."""

    if df.empty or y not in df:
        return go.Figure().update_layout(title=title, height=280)
    return px.line(df, x="timestamp", y=y, color="node_id", title=title, height=280)


def drop_reason_figure(sim: SeianMeshSimulator) -> go.Figure:
    """Build packet-drop reason bar chart."""

    data = [{"reason": k, "count": v} for k, v in sim.metrics.drop_reasons.items()]
    if not data:
        data = [{"reason": "none", "count": 0}]
    return px.bar(pd.DataFrame(data), x="reason", y="count", title="Packet-drop reasons", height=280)


def _color_for_node(node) -> str:
    if not node.active:
        return "#6b7280"
    if node.gateway_online:
        return "#2563eb"
    if node.fault_classification == "BOUNDARY_NODE":
        return "#f59e0b"
    if node.fault_status == FaultStatus.FAULT:
        return "#dc2626"
    if node.fault_status == FaultStatus.WARNING:
        return "#eab308"
    return "#16a34a"


def packet_trace_figure(sim: SeianMeshSimulator, session) -> go.Figure:
    """Draw a Packet Tracer-style view of one manual packet session.

    Completed physical transmissions remain visible as a trace.  The latest
    successful hop is highlighted in green, a dropped hop in red, and the next
    waiting transmission is shown as an amber dotted link.  No movement occurs
    here; movement only changes after ``ManualPacketSession.forward_one``.
    """

    fig = topology_figure(sim, show_packets=False)

    status_colors = {
        "DELIVERED": "#16a34a",
        "FORWARDED": "#2563eb",
        "RECEIVED": "#0f766e",
        "DROPPED": "#dc2626",
        "DUPLICATE": "#f59e0b",
    }

    physical_records = [
        row
        for row in session.history
        if row.sender_id in sim.nodes
        and row.receiver_id in sim.nodes
        and row.sender_id != row.receiver_id
        and row.action != "Routing decision"
    ]

    for row in physical_records[:-1]:
        source = sim.nodes[row.sender_id]
        receiver = sim.nodes[row.receiver_id]
        fig.add_trace(
            go.Scatter(
                x=[source.position_x, receiver.position_x],
                y=[source.position_y, receiver.position_y],
                mode="lines",
                line=dict(
                    width=3,
                    color=status_colors.get(row.status, "#64748b"),
                    dash="dot" if row.status in {"DROPPED", "DUPLICATE"} else "solid",
                ),
                hovertext=(
                    f"Step {row.step}: {row.packet_type}<br>"
                    f"{row.sender_id} → {row.receiver_id}<br>"
                    f"{row.status}<br>{row.message}"
                ),
                hoverinfo="text",
                showlegend=False,
            )
        )

    last = session.last_step
    if last and last.sender_id in sim.nodes and last.receiver_id in sim.nodes and last.sender_id != last.receiver_id:
        source = sim.nodes[last.sender_id]
        receiver = sim.nodes[last.receiver_id]
        color = status_colors.get(last.status, "#7c3aed")
        fig.add_trace(
            go.Scatter(
                x=[source.position_x, receiver.position_x],
                y=[source.position_y, receiver.position_y],
                mode="lines+markers",
                line=dict(width=7, color=color, dash="dot" if last.status == "DROPPED" else "solid"),
                marker=dict(size=[8, 16], symbol=["circle", "triangle-right"], color=color),
                hovertext=(
                    f"Current step {last.step}<br>{last.packet_type}<br>"
                    f"{last.sender_id} → {last.receiver_id}<br>{last.status}<br>{last.message}"
                ),
                hoverinfo="text",
                name="Last event",
            )
        )
        fig.add_annotation(
            x=receiver.position_x,
            y=receiver.position_y,
            text=f"Step {last.step}: {last.status}",
            showarrow=True,
            arrowhead=2,
            ax=35,
            ay=-40,
            bgcolor="rgba(255,255,255,0.92)",
            bordercolor=color,
        )

    if session.pending:
        next_item = session.pending[0]
        if next_item.sender_id in sim.nodes and next_item.receiver_id in sim.nodes:
            source = sim.nodes[next_item.sender_id]
            receiver = sim.nodes[next_item.receiver_id]
            fig.add_trace(
                go.Scatter(
                    x=[source.position_x, receiver.position_x],
                    y=[source.position_y, receiver.position_y],
                    mode="lines+markers",
                    line=dict(width=3, color="#f59e0b", dash="dash"),
                    marker=dict(size=[13, 7], symbol=["square", "circle"], color="#f59e0b"),
                    hovertext=(
                        f"Next waiting event<br>{next_item.packet.packet_type.value}<br>"
                        f"{next_item.sender_id} → {next_item.receiver_id}<br>"
                        "Press Forward to execute"
                    ),
                    hoverinfo="text",
                    name="Next event",
                )
            )

    fig.update_layout(
        title=(
            f"Manual packet trace: {session.packet_type.value} | "
            f"pending {session.pending_count} | completed steps {len(session.history)}"
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return fig
