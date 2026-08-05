"""Built-in deterministic scenarios for demonstrations and tests."""

from __future__ import annotations

from seian_sim.config import SimulationConfig
from seian_sim.enums import FaultStatus, FaultType
from seian_sim.simulator import SeianMeshSimulator


SCENARIO_NAMES = [
    "Basic five-node mesh",
    "Healthy route versus short unhealthy route",
    "Hotel microgrid",
    "Gateway failure",
    "Voltage-sag propagation",
    "Congestion during emergency",
    "Replay and invalid packet rejection",
]


def build_scenario(name: str, config: SimulationConfig | None = None) -> SeianMeshSimulator:
    """Create one built-in scenario by display name."""

    sim = SeianMeshSimulator(config or SimulationConfig())
    if name == "Basic five-node mesh":
        _basic_five(sim)
    elif name == "Healthy route versus short unhealthy route":
        _healthy_vs_short(sim)
    elif name == "Hotel microgrid":
        _hotel_microgrid(sim)
    elif name == "Gateway failure":
        _basic_five(sim)
        sim.run(40)
        sim.set_gateway("N01", False)
    elif name == "Voltage-sag propagation":
        _basic_five(sim)
        sim.run(20)
        sim.inject_fault("N03", FaultType.VOLTAGE_SAG, severity="severe", radius_m=180)
    elif name == "Congestion during emergency":
        _hotel_microgrid(sim)
        sim.config.lora.packet_loss_probability = 0.08
        sim.run(30)
        for node in sim.nodes.values():
            node.load_percent = 95.0
        sim.inject_fault("N12", FaultType.SHORT_CIRCUIT_SUSPECTED, severity="emergency", radius_m=180)
    elif name == "Replay and invalid packet rejection":
        _basic_five(sim)
        sim.run(20)
        sim.simulate_attack("N02", "replay")
        sim.simulate_attack("N02", "replay")
        sim.simulate_attack("N03", "invalid_authentication")
        sim.simulate_attack("N04", "wrong_network_id")
    else:
        raise ValueError(f"Unknown scenario: {name}")
    return sim

def build_empty_topology(
    config: SimulationConfig | None = None,
) -> SeianMeshSimulator:
    return SeianMeshSimulator(config or SimulationConfig())


def _basic_five(sim: SeianMeshSimulator) -> None:
    sim.add_node("N01", 60, 160, gateway_capable=True, gateway_online=True)
    sim.add_node("N02", 165, 120)
    sim.add_node("N03", 280, 155)
    sim.add_node("N04", 410, 185)
    sim.add_node("N05", 520, 215)
    sim.discover_neighbors()


def _healthy_vs_short(sim: SeianMeshSimulator) -> None:
    sim.config.lora.max_range_m = 260
    sim.add_node("N01", 0, 0, gateway_capable=True, gateway_online=True)
    sim.add_node("N02", 170, 0, load_percent=99, health_score=0.35)
    sim.add_node("N03", 125, 105, load_percent=35, health_score=1.0)
    sim.add_node("N04", 240, 105, load_percent=36, health_score=1.0)
    sim.nodes["N02"].fault_status = FaultStatus.WARNING
    sim.discover_neighbors()


def _hotel_microgrid(sim: SeianMeshSimulator) -> None:
    positions = {
        "N01": (45, 175), "N02": (95, 80), "N03": (105, 265), "N04": (160, 135),
        "N05": (165, 225), "N06": (220, 175), "N07": (265, 90), "N08": (270, 270),
        "N09": (315, 125), "N10": (335, 185), "N11": (355, 245), "N12": (405, 80),
        "N13": (415, 150), "N14": (420, 285), "N15": (465, 195), "N16": (485, 245),
        "N17": (520, 105), "N18": (555, 195), "N19": (560, 280), "N20": (590, 125),
    }
    for node_id, (x, y) in positions.items():
        sim.add_node(node_id, x, y, gateway_capable=node_id == "N01", gateway_online=node_id == "N01")
    sim.discover_neighbors()


def demonstrate_hotel_reroute() -> SeianMeshSimulator:
    """Return hotel scenario after failing N15 to show automatic recovery."""

    sim = build_scenario("Hotel microgrid")
    sim.fail_node("N15")
    return sim


def build_random_topology(
    node_count: int,
    config: SimulationConfig | None = None,
    *,
    gateway_count: int = 1,
) -> SeianMeshSimulator:
    """Create a repeatable random topology inside the configured area."""

    sim = SeianMeshSimulator(config or SimulationConfig())
    count = max(0, int(node_count))
    gateway_count = max(0, min(int(gateway_count), count))
    margin = min(20.0, sim.config.area_width_m / 4.0, sim.config.area_height_m / 4.0)
    x_min, x_max = margin, max(margin, sim.config.area_width_m - margin)
    y_min, y_max = margin, max(margin, sim.config.area_height_m - margin)
    for index in range(count):
        is_gateway = index < gateway_count
        sim.add_node(
            f"N{index + 1:02d}",
            sim.rng.uniform(x_min, x_max),
            sim.rng.uniform(y_min, y_max),
            gateway_capable=is_gateway,
            gateway_online=is_gateway,
        )
    sim.discover_neighbors()
    return sim


def export_topology(sim: SeianMeshSimulator) -> dict:
    """Export node placement and state in a reloadable JSON structure."""

    return {
        "network_id": sim.config.network_id,
        "area_width_m": sim.config.area_width_m,
        "area_height_m": sim.config.area_height_m,
        "lora_range_m": sim.config.lora.max_range_m,
        "nodes": [
            {
                "node_id": node.node_id,
                "x": node.position_x,
                "y": node.position_y,
                "network_id": node.network_id,
                "gateway_capable": node.gateway_capable,
                "gateway_online": node.gateway_online,
                "active": node.active,
                "health_score": node.health_score,
                "load_percent": node.load_percent,
            }
            for node in sim.nodes.values()
        ],
    }


def build_from_topology(data: dict, config: SimulationConfig | None = None) -> SeianMeshSimulator:
    """Build a simulator from topology JSON exported by :func:`export_topology`."""

    if not isinstance(data, dict):
        raise ValueError("Topology JSON must contain an object.")
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("Topology JSON must include a 'nodes' list.")

    cfg = config or SimulationConfig()
    cfg.network_id = str(data.get("network_id", cfg.network_id))
    cfg.area_width_m = float(data.get("area_width_m", cfg.area_width_m))
    cfg.area_height_m = float(data.get("area_height_m", cfg.area_height_m))
    cfg.lora.max_range_m = float(data.get("lora_range_m", cfg.lora.max_range_m))
    cfg.validate()
    sim = SeianMeshSimulator(cfg)

    for index, row in enumerate(nodes):
        if not isinstance(row, dict):
            raise ValueError(f"Node entry {index} must be an object.")
        node_id = str(row.get("node_id", f"N{index + 1:02d}"))
        if node_id in sim.nodes:
            raise ValueError(f"Duplicate node ID: {node_id}")
        node = sim.add_node(
            node_id,
            float(row.get("x", 0.0)),
            float(row.get("y", 0.0)),
            network_id=str(row.get("network_id", cfg.network_id)),
            gateway_capable=bool(row.get("gateway_capable", False)),
            gateway_online=bool(row.get("gateway_online", False)),
            load_percent=float(row.get("load_percent", 40.0)),
            health_score=float(row.get("health_score", 1.0)),
        )
        node.active = bool(row.get("active", True))
    sim.discover_neighbors()
    return sim
