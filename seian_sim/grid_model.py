"""Simplified grid-state time-series model."""

from __future__ import annotations

import random

from seian_sim.config import GridConfig
from seian_sim.enums import FaultStatus


class GridModel:
    """Generates deterministic but noisy inverter measurements."""

    def __init__(self, config: GridConfig, rng: random.Random) -> None:
        self.config = config
        self.rng = rng

    def update_node(self, node: "SeianNode", timestamp: float) -> None:
        """Advance one node's simulated electrical measurements."""

        load_delta = self.rng.uniform(-2.5, 2.8)
        node.load_percent = max(5.0, min(115.0, node.load_percent + load_delta))
        load_effect = (node.load_percent - 50.0) / 100.0
        node.voltage_rms = self.config.nominal_voltage_v - 9.0 * load_effect + self.rng.gauss(0, 1.2)
        node.frequency_hz = self.config.nominal_frequency_hz - 0.08 * load_effect + self.rng.gauss(0, 0.015)
        node.phase_angle_deg = self.config.nominal_phase_deg + self.rng.gauss(0, 1.4) + load_effect * 2.0
        node.current_a = max(0.5, node.load_percent / 100.0 * 28.0 + self.rng.gauss(0, 0.7))
        node.active_power_kw = node.voltage_rms * node.current_a * node.power_factor / 1000.0
        node.reactive_power_kvar = max(0.0, node.active_power_kw * (1.0 - node.power_factor))
        node.thd_percent = max(1.0, 2.0 + 0.03 * node.load_percent + self.rng.gauss(0, 0.2))
        node.temperature_c = max(20.0, 26.0 + 0.38 * node.load_percent + self.rng.gauss(0, 0.8))

        if node.temperature_c > 74.0 or node.load_percent > 105.0:
            node.fault_status = FaultStatus.FAULT
            node.health_score = max(0.25, node.health_score - 0.04)
        elif node.temperature_c > 64.0 or node.load_percent > 92.0:
            node.fault_status = FaultStatus.WARNING
            node.health_score = max(0.45, node.health_score - 0.015)
        elif node.active:
            node.fault_status = FaultStatus.NORMAL
            node.health_score = min(1.0, node.health_score + 0.005)
