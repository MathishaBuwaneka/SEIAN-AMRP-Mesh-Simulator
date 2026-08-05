"""Helpers for the interactive Streamlit network-construction canvas."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from seian_sim.simulator import SeianMeshSimulator

PLACE_STANDARD = "Place standard node"
PLACE_GATEWAY = "Place gateway node"
SELECT_NODE = "Select node"
MOVE_NODE = "Move selected node"
DELETE_NODE = "Delete clicked node"

BUILDER_TOOLS = [
    PLACE_STANDARD,
    PLACE_GATEWAY,
    SELECT_NODE,
    MOVE_NODE,
    DELETE_NODE,
]


@dataclass(frozen=True, slots=True)
class CanvasClick:
    """One click returned by the Plotly placement canvas."""

    x: float
    y: float
    node_id: str | None = None


@dataclass(frozen=True, slots=True)
class BuilderActionResult:
    """Result of applying one canvas action to the simulator."""

    changed: bool
    selected_node_id: str | None
    message: str
    added_node_id: str | None = None
    removed_node_id: str | None = None


def next_available_node_id(existing_ids: object, prefix: str = "N") -> str:
    """Return the first unused sequential identifier such as ``N01``."""

    ids = {str(value) for value in existing_ids}
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$", re.IGNORECASE)
    used_numbers = {
        int(match.group(1))
        for value in ids
        if (match := pattern.match(value)) is not None
    }
    candidate = 1
    while candidate in used_numbers or f"{prefix}{candidate:02d}" in ids:
        candidate += 1
    return f"{prefix}{candidate:02d}"


def parse_plotly_canvas_event(event: Any) -> CanvasClick | None:
    """Extract a canvas click from Streamlit's Plotly selection-state object.

    The function accepts both dictionary-like objects and Streamlit's attribute-style
    state object so it can be tested without importing Streamlit.
    """

    selection = _read(event, "selection")
    points = _read(selection, "points")
    if not points:
        return None

    point = points[-1]
    try:
        x = float(_read(point, "x"))
        y = float(_read(point, "y"))
    except (TypeError, ValueError):
        return None

    customdata = _read(point, "customdata")
    node_id: str | None = None
    if isinstance(customdata, (list, tuple)) and len(customdata) >= 2:
        if str(customdata[0]) == "node":
            node_id = str(customdata[1])
    elif isinstance(customdata, str) and customdata.startswith("node:"):
        node_id = customdata.split(":", 1)[1]

    return CanvasClick(x=x, y=y, node_id=node_id)


def apply_canvas_action(
    sim: SeianMeshSimulator,
    tool: str,
    click: CanvasClick,
    *,
    selected_node_id: str | None = None,
    requested_node_id: str | None = None,
) -> BuilderActionResult:
    """Apply an add/select/move/delete operation from the visual builder."""

    x = min(max(float(click.x), 0.0), float(sim.config.area_width_m))
    y = min(max(float(click.y), 0.0), float(sim.config.area_height_m))

    if tool in {PLACE_STANDARD, PLACE_GATEWAY}:
        node_id = (requested_node_id or "").strip() or next_available_node_id(sim.nodes)
        if node_id in sim.nodes:
            return BuilderActionResult(
                changed=False,
                selected_node_id=selected_node_id,
                message=f"Node ID {node_id} already exists. Choose another ID or use automatic IDs.",
            )
        is_gateway = tool == PLACE_GATEWAY
        sim.add_node(
            node_id,
            x,
            y,
            gateway_capable=is_gateway,
            gateway_online=is_gateway,
        )
        sim.discover_neighbors()
        role = "gateway" if is_gateway else "standard"
        return BuilderActionResult(
            changed=True,
            selected_node_id=node_id,
            added_node_id=node_id,
            message=f"Placed {role} node {node_id} at ({x:.1f}, {y:.1f}) m.",
        )

    if tool == SELECT_NODE:
        if click.node_id is None or click.node_id not in sim.nodes:
            return BuilderActionResult(
                changed=False,
                selected_node_id=selected_node_id,
                message="Click directly on a node to select it.",
            )
        return BuilderActionResult(
            changed=True,
            selected_node_id=click.node_id,
            message=f"Selected node {click.node_id}.",
        )

    if tool == MOVE_NODE:
        if selected_node_id is None or selected_node_id not in sim.nodes:
            return BuilderActionResult(
                changed=False,
                selected_node_id=None,
                message="Select a node first, then choose Move selected node and click its new position.",
            )
        sim.move_node(selected_node_id, x, y)
        return BuilderActionResult(
            changed=True,
            selected_node_id=selected_node_id,
            message=f"Moved {selected_node_id} to ({x:.1f}, {y:.1f}) m.",
        )

    if tool == DELETE_NODE:
        target = click.node_id
        if target is None or target not in sim.nodes:
            return BuilderActionResult(
                changed=False,
                selected_node_id=selected_node_id,
                message="Click directly on the node that should be deleted.",
            )
        sim.remove_node(target)
        next_selected = selected_node_id if selected_node_id != target else None
        return BuilderActionResult(
            changed=True,
            selected_node_id=next_selected,
            removed_node_id=target,
            message=f"Deleted node {target}.",
        )

    return BuilderActionResult(
        changed=False,
        selected_node_id=selected_node_id,
        message=f"Unknown builder tool: {tool}",
    )


def _read(value: Any, key: str) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)
