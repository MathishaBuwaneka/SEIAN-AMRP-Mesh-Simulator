"""Configuration values for deterministic simulator runs."""

from __future__ import annotations

from dataclasses import dataclass, field
import math


@dataclass(slots=True)
class RoutingWeights:
    """Weights for communication and electrical route suitability."""

    hop_count: float = 2.0
    link_loss: float = 1.5
    communication_health: float = 3.0
    communication_congestion: float = 1.0
    communication_fault: float = 10.0
    power_health: float = 3.0
    power_load: float = 1.0
    power_fault: float = 10.0
    gateway_bonus: float = -1.0
    cross_plane_risk: float = 1.0


@dataclass(slots=True)
class LoraConfig:
    """LoRa timing settings and approximate propagation/loss settings."""

    airtime_mode: str = "approximate"
    frequency_hz: float = 868_000_000.0
    spreading_factor: int = 7
    bandwidth_hz: int = 125_000
    coding_rate_denominator: int = 5
    preamble_symbols: int = 8
    implicit_header: bool = False
    crc_enabled: bool = True
    low_data_rate_optimization: bool | None = None
    protocol_header_bytes: int = 24
    receiver_noise_figure_db: float = 6.0

    max_range_m: float = 260.0
    path_loss_exponent: float = 2.1
    reference_rssi_dbm: float = -48.0
    reference_distance_m: float = 1.0
    shadow_fading_std_db: float = 2.0
    noise_floor_dbm: float = -120.0
    sensitivity_dbm: float | None = None
    packet_loss_probability: float = 0.03
    channel_busy_probability: float = 0.02
    collision_probability: float = 0.02
    transmission_delay_s: float = 0.25
    airtime_base_s: float = 0.18
    interference_probability: float = 0.0

    def validate(self) -> None:
        """Validate the supported SX1276 profile before calculating timing."""
        if self.airtime_mode not in {"approximate", "lora"}:
            raise ValueError("Airtime mode must be 'approximate' or 'lora'.")
        for name, low, high in (
            ("spreading_factor", 6, 12),
            ("coding_rate_denominator", 5, 8),
            ("preamble_symbols", 6, 65535),
            ("protocol_header_bytes", 0, 254),
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} must be an integer in {low}..{high}.")
        if type(self.bandwidth_hz) is not int or self.bandwidth_hz not in {125_000, 250_000, 500_000}:
            raise ValueError("Bandwidth must be 125000, 250000, or 500000 Hz.")
        for name in ("implicit_header", "crc_enabled"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean.")
        if self.low_data_rate_optimization is not None and type(self.low_data_rate_optimization) is not bool:
            raise ValueError("Low-data-rate optimization must be boolean or None (automatic).")
        if self.spreading_factor == 6 and not self.implicit_header:
            raise ValueError("SF6 requires implicit header mode.")
        if 2 ** self.spreading_factor / self.bandwidth_hz > 0.016 and self.low_data_rate_optimization is False:
            raise ValueError("Low-data-rate optimization is required for symbols longer than 16 ms.")
        for name in ("frequency_hz", "receiver_noise_figure_db", "transmission_delay_s", "airtime_base_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative.")
        if not 137_000_000 <= self.frequency_hz <= 1_020_000_000:
            raise ValueError("Frequency must be within the SX1276 range, 137..1020 MHz.")
        if self.sensitivity_dbm is not None and (
            isinstance(self.sensitivity_dbm, bool)
            or not isinstance(self.sensitivity_dbm, (int, float))
            or not math.isfinite(self.sensitivity_dbm)
        ):
            raise ValueError("Sensitivity override must be finite or None.")


@dataclass(slots=True)
class RadioConfig:
    """Explicit assumptions for the event-based shared channel."""

    mode: str = "serialized"
    carrier_sense: bool = True
    carrier_sense_threshold_dbm: float = -110.0
    capture_threshold_db: float = 6.0
    cross_sf_interference: bool = False
    backoff_slot_s: float = 0.02
    max_backoffs: int = 8
    max_retries: int = 2
    initial_backoff_slots: int = 16
    retry_delay_s: float = 0.05
    duty_cycle: float = 1.0

    def validate(self) -> None:
        if self.mode not in {"serialized", "event"}:
            raise ValueError("Radio mode must be serialized or event.")
        for name in ("carrier_sense", "cross_sf_interference"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean.")
        for name in ("carrier_sense_threshold_dbm", "capture_threshold_db", "backoff_slot_s", "retry_delay_s", "duty_cycle"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite.")
        if self.capture_threshold_db < 0 or self.backoff_slot_s <= 0 or self.retry_delay_s < 0:
            raise ValueError("Capture/retry delay must be nonnegative and backoff slot positive.")
        if not 0 < self.duty_cycle <= 1:
            raise ValueError("Duty cycle must be in (0, 1].")
        for name in ("max_backoffs", "max_retries", "initial_backoff_slots"):
            if type(getattr(self, name)) is not int or not 0 <= getattr(self, name) <= 100:
                raise ValueError(f"{name} must be an integer in 0..100.")


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
    packet_encoding: str = "json"
    wire_network_id: int = 1
    wire_addresses: dict[str, int] = field(default_factory=dict)
    random_seed: int = 42
    duration_s: float = 300.0
    area_width_m: float = 600.0
    area_height_m: float = 360.0
    heartbeat_min_s: float = 10.0
    heartbeat_max_s: float = 30.0
    neighbor_timeout_s: float = 60.0
    routing_mode: str = "oracle"
    route_lifetime_s: float = 120.0
    route_switch_hysteresis: float = 0.1
    route_advertisement_interval_s: float = 30.0
    route_convergence_round_limit: int = 64
    max_hops: int = 10
    queue_limit: int = 80
    whitelist_enabled: bool = False
    key_id: str = "demo-key"
    lora: LoraConfig = field(default_factory=LoraConfig)
    radio: RadioConfig = field(default_factory=RadioConfig)
    grid: GridConfig = field(default_factory=GridConfig)
    routing_weights: RoutingWeights = field(default_factory=RoutingWeights)

    def validate(self) -> None:
        """Raise ValueError for invalid user-controlled settings."""

        self.lora.validate()
        self.radio.validate()
        if self.radio.mode == "event" and self.lora.airtime_mode != "lora":
            raise ValueError("Event radio requires LoRa time-on-air timing.")
        if self.packet_encoding not in {"json", "binary"}:
            raise ValueError("Packet encoding must be 'json' or 'binary'.")
        if type(self.wire_network_id) is not int or not 1 <= self.wire_network_id <= 65534:
            raise ValueError("Wire network ID must be an integer in 1..65534.")
        if not isinstance(self.wire_addresses, dict) or any(
            not isinstance(key, str) or not key or type(value) is not int or not 1 <= value <= 65534
            for key, value in self.wire_addresses.items()
        ):
            raise ValueError("Wire addresses must map node names to integers in 1..65534.")
        if len(set(self.wire_addresses.values())) != len(self.wire_addresses):
            raise ValueError("Wire addresses must be unique.")

        if self.duration_s <= 0:
            raise ValueError("Simulation duration must be positive.")
        if self.area_width_m <= 0 or self.area_height_m <= 0:
            raise ValueError("Simulation area dimensions must be positive.")
        if self.lora.max_range_m <= 0:
            raise ValueError("LoRa range must be positive.")
        if self.neighbor_timeout_s <= 0:
            raise ValueError("Neighbor timeout must be positive.")
        if self.routing_mode not in {"oracle", "decentralized"}:
            raise ValueError("Routing mode must be 'oracle' or 'decentralized'.")
        if self.route_lifetime_s <= 0:
            raise ValueError("Route lifetime must be positive.")
        if self.route_switch_hysteresis < 0:
            raise ValueError("Route-switch hysteresis must be non-negative.")
        if self.route_advertisement_interval_s <= 0:
            raise ValueError("Route-advertisement interval must be positive.")
        if self.route_convergence_round_limit <= 0:
            raise ValueError("Route-convergence round limit must be positive.")
        if self.max_hops <= 0:
            raise ValueError("Maximum hop count must be positive.")
        nonnegative_routing_weights = (
            self.routing_weights.hop_count,
            self.routing_weights.link_loss,
            self.routing_weights.communication_health,
            self.routing_weights.communication_congestion,
            self.routing_weights.communication_fault,
            self.routing_weights.power_health,
            self.routing_weights.power_load,
            self.routing_weights.power_fault,
            self.routing_weights.cross_plane_risk,
        )
        if any(weight < 0 for weight in nonnegative_routing_weights):
            raise ValueError("Routing penalty weights must be non-negative.")
