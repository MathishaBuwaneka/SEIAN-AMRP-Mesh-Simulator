from seian_sim.config import SimulationConfig
from seian_sim.network_builder import (
    DELETE_NODE,
    MOVE_NODE,
    PLACE_GATEWAY,
    PLACE_STANDARD,
    SELECT_NODE,
    CanvasClick,
    apply_canvas_action,
    next_available_node_id,
    parse_plotly_canvas_event,
)
from seian_sim.scenarios import build_empty_topology


def test_next_available_node_id_reuses_first_gap():
    assert next_available_node_id(["N01", "N03", "GATEWAY"]) == "N02"


def test_parse_plotly_canvas_event_handles_canvas_and_node_points():
    canvas = {"selection": {"points": [{"x": 20, "y": 30, "customdata": ["canvas", ""]}]}}
    node = {"selection": {"points": [{"x": 40, "y": 50, "customdata": ["node", "N01"]}]}}

    assert parse_plotly_canvas_event(canvas) == CanvasClick(20.0, 30.0, None)
    assert parse_plotly_canvas_event(node) == CanvasClick(40.0, 50.0, "N01")


def test_place_move_select_and_delete_nodes_from_canvas():
    config = SimulationConfig(area_width_m=200, area_height_m=100)
    config.lora.max_range_m = 90
    sim = build_empty_topology(config)

    first = apply_canvas_action(sim, PLACE_GATEWAY, CanvasClick(10, 20))
    assert first.changed
    assert first.added_node_id == "N01"
    assert sim.nodes["N01"].gateway_online

    second = apply_canvas_action(sim, PLACE_STANDARD, CanvasClick(70, 20))
    assert second.added_node_id == "N02"
    assert "N02" in sim.nodes["N01"].neighbor_table

    selected = apply_canvas_action(
        sim,
        SELECT_NODE,
        CanvasClick(70, 20, "N02"),
        selected_node_id="N01",
    )
    assert selected.selected_node_id == "N02"

    moved = apply_canvas_action(
        sim,
        MOVE_NODE,
        CanvasClick(190, 90),
        selected_node_id="N02",
    )
    assert moved.changed
    assert sim.nodes["N02"].position == (190.0, 90.0)
    assert "N02" not in sim.nodes["N01"].neighbor_table

    deleted = apply_canvas_action(
        sim,
        DELETE_NODE,
        CanvasClick(190, 90, "N02"),
        selected_node_id="N02",
    )
    assert deleted.changed
    assert deleted.selected_node_id is None
    assert "N02" not in sim.nodes


def test_custom_duplicate_id_is_rejected():
    sim = build_empty_topology()
    apply_canvas_action(sim, PLACE_STANDARD, CanvasClick(10, 10), requested_node_id="INV-A")
    duplicate = apply_canvas_action(
        sim,
        PLACE_STANDARD,
        CanvasClick(20, 20),
        requested_node_id="INV-A",
    )
    assert not duplicate.changed
    assert len(sim.nodes) == 1
