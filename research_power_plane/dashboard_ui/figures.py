"""Plotly feeder and switching-timeline diagrams."""

from __future__ import annotations

from html import escape
from typing import Any

import plotly.graph_objects as go

from .models import endpoints, line_label

CONNECTED = "#168f80"
OPEN = "#8b96a3"
FAULT = "#e45b67"
SOURCE = "#d7a43e"


def feeder_figure(topology: dict[str, Any], state: dict[str, Any]) -> go.Figure:
    nodes = {row["node_id"]: row for row in topology["nodes"]}
    positions = {name: (float(row.get("x", index * 100)), float(row.get("y", 0))) for index, (name, row) in enumerate(nodes.items())}
    middle_y = sum(y for _, y in positions.values()) / len(positions)
    figure = go.Figure()
    for line in topology["power_lines"]:
        a, b = endpoints(line)
        ax, ay = positions[a]
        bx, by = positions[b]
        closed = state["closed"][line["line_id"]]
        color = CONNECTED if closed and a in state["connected"] else OPEN
        hover = f"{escape(line['line_id'])}<br>{'Closed' if closed else 'Open'}<br>Rating: {escape(str(line.get('capacity_kw', 'Unspecified')))} kW"
        figure.add_trace(go.Scatter(
            x=[ax, bx], y=[ay, by], mode="lines", hoverinfo="skip", showlegend=False,
            line={"color": color, "width": 3, "dash": "solid" if closed else "dash"},
        ))
        figure.add_trace(go.Scatter(
            x=[(ax + bx) / 2], y=[(ay + by) / 2], mode="markers",
            marker={"size": 12, "symbol": "square" if closed else "square-open", "color": color, "line": {"width": 2}},
            customdata=[["line", line["line_id"]]], hovertemplate=hover + "<extra></extra>", showlegend=False,
        ))
    for node_id in nodes:
        x, y = positions[node_id]
        fault = node_id in state["faults"]
        source = node_id in state["sources"]
        connected = node_id in state["connected"]
        color = FAULT if fault else SOURCE if source else CONNECTED if connected else OPEN
        label = "Fault applied" if fault else "Source" if source else "Source-connected" if connected else "Isolated"
        figure.add_trace(go.Scatter(
            x=[x], y=[y], mode="markers+text", text=[escape(node_id)], textposition="bottom center" if y > middle_y else "top center",
            textfont={"size": 14}, marker={"size": 23, "color": color, "symbol": "diamond" if source else "circle", "line": {"color": color, "width": 3}},
            customdata=[["node", node_id]], hovertemplate=f"{escape(node_id)}<br>{label}<extra></extra>", showlegend=False,
        ))
    for name, color, symbol in [("Source", SOURCE, "diamond"), ("Connected", CONNECTED, "circle"), ("Open / isolated", OPEN, "square-open"), ("Fault", FAULT, "circle")]:
        figure.add_trace(go.Scatter(x=[None], y=[None], mode="markers", marker={"size": 9, "color": color, "symbol": symbol}, name=name, hoverinfo="skip"))
    xs, ys = zip(*positions.values())
    figure.update_layout(
        height=370, margin={"l": 18, "r": 18, "t": 35, "b": 45},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"size": 12}, clickmode="event+select", dragmode=False,
        xaxis={"visible": False, "range": [min(xs) - 45, max(xs) + 45]},
        yaxis={"visible": False, "range": [max(ys) + 50, min(ys) - 50]},
        legend={"orientation": "h", "y": -0.12, "x": 0, "font": {"size": 11}},
    )
    return figure


def timeline_figure(topology: dict[str, Any], preview: dict[str, Any]) -> go.Figure:
    figure = go.Figure()
    labels = {row["line_id"]: line_label(row) for row in topology["power_lines"]}
    duration = preview["switching_timeline"]["duration_s"]
    for schedule in preview["switching_timeline"]["line_schedules"]:
        y = labels[schedule["line_id"]]
        times = [0.0] + [event["timestamp"] for event in schedule["events"]] + [duration]
        states = [schedule["initial_closed"]] + [event["closed"] for event in schedule["events"]]
        for start, end, closed in zip(times, times[1:], states):
            figure.add_trace(go.Scatter(
                x=[start, end], y=[y, y], mode="lines", showlegend=False,
                line={"color": CONNECTED if closed else OPEN, "width": 5 if closed else 2, "dash": "solid" if closed else "dot"},
                hovertemplate=f"{escape(y)}<br>{'Closed' if closed else 'Open'}<br>%{{x:g}} s<extra></extra>",
            ))
    for fault in preview["physical_faults"]:
        label = f"Fault {fault['node_id']}"
        figure.add_trace(go.Scatter(
            x=[fault["start_s"], fault["end_s"]], y=[label, label], mode="lines+markers",
            line={"color": FAULT, "width": 9}, marker={"size": 9}, showlegend=False,
            hovertemplate=f"{escape(fault['fault_id'])}<br>%{{x:g}} s<extra></extra>",
        ))
    figure.update_layout(
        height=300, margin={"l": 0, "r": 16, "t": 8, "b": 35},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis={"title": "Simulation time (s)", "range": [0, duration], "zeroline": False},
        yaxis={"autorange": "reversed", "type": "category", "tickfont": {"size": 11}},
        font={"size": 12},
    )
    return figure
