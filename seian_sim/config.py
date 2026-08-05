"""Configuration values for deterministic simulator runs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RoutingWeights:
    """Weights for grid-aware route cost."""

    hop_count: float = 2.0
    link_loss: float = 1.5
    node_health: float = 3.0
    load: float = 1.0
    fault: float = 10.0
    gateway_bonus: float = -1.0


@dataclass(slots=True)
class LoraConfig:
    """Approximate LoRa channel model settings."""

    max_range_m: float = 260.0
    path_loss_exponent: float = 2.1
    reference_rssi_dbm: float = -48.0
    reference_distance_m: float = 1.0
    shadow_fading_std_db: float = 2.0
    noise_floor_dbm: float = -120.0
    sensitivity_dbm: float = -118.0
    packet_loss_probability: float = 0.03
    channel_busy_probability: float = 0.02
    collision_probability: float = 0.02
    transmission_delay_s: float = 0.25
    airtime_base_s: float = 0.18
    interference_probability: float = 0.0


@dataclass(slots=True)
class GridConfig:
    """Nominal grid and inverter measurement values."""

    nominal_voltage_v: float = 230.0
    nominal_frequency_hz: float = 50.0
    nominal_phase_deg: float = 0.0
    stable_telemetry_min_s: float = 30.0
    stable_telemetry_max_s: float = 60.0
    unstable_telemetry_min_s: float = 5.0
    unstable_telemetry_max_s: float = 10.0


@dataclass(slots=True)
class SimulationConfig:
    """Top-level simulation configuration."""

    network_id: str = "SEIAN-LAB"
    random_seed: int = 42
    duration_s: float = 300.0
    area_width_m: float = 600.0
    area_height_m: float = 360.0
    heartbeat_min_s: float = 10.0
    heartbeat_max_s: float = 30.0
    neighbor_timeout_s: float = 60.0
    route_lifetime_s: float = 120.0
    max_hops: int = 10
    queue_limit: int = 80
    whitelist_enabled: bool = False
    key_id: str = "demo-key"
    lora: LoraConfig = field(default_factory=LoraConfig)
    grid: GridConfig = field(default_factory=GridConfig)
    routing_weights: RoutingWeights = field(default_factory=RoutingWeights)

    def validate(self) -> None:
        """Raise ValueError for invalid user-controlled settings."""

        if self.duration_s <= 0:
            raise ValueError("Simulation duration must be positive.")
        if self.area_width_m <= 0 or self.area_height_m <= 0:
            raise ValueError("Simulation area dimensions must be positive.")
        if self.lora.max_range_m <= 0:
            raise ValueError("LoRa range must be positive.")
        if self.neighbor_timeout_s <= 0:
            raise ValueError("Neighbor timeout must be positive.")
        if self.max_hops <= 0:
            raise ValueError("Maximum hop count must be positive.")
