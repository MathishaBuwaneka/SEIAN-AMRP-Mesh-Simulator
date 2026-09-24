"""Approximate LoRa channel model for protocol research."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from seian_sim.config import LoraConfig
from seian_sim.lora_airtime import calculate_airtime, receiver_sensitivity_dbm


@dataclass(slots=True)
class LinkObservation:
    """Radio observation from one packet delivery attempt."""

    delivered: bool
    rssi: float
    snr: float
    link_quality: float
    delay_s: float
    drop_reason: str | None = None
    airtime_s: float = 0.0


def calculate_link_quality(rssi: float, snr: float, loss_rate: float) -> float:
    """Normalize RSSI, SNR, and expected loss into a 0..1 link-quality score.

    RSSI is mapped from the practical LoRa region of -120 dBm to -55 dBm, SNR
    from -20 dB to 12 dB, and the expected loss rate directly reduces the score.
    The weighted result is clipped to keep routing calculations stable.
    """

    rssi_score = (rssi + 120.0) / 65.0
    snr_score = (snr + 20.0) / 32.0
    loss_score = 1.0 - loss_rate
    score = 0.45 * rssi_score + 0.35 * snr_score + 0.20 * loss_score
    return max(0.0, min(1.0, score))


class LoraChannel:
    """Distance-based probabilistic LoRa channel."""

    def __init__(self, config: LoraConfig, rng: random.Random) -> None:
        config.validate()
        self.config = config
        self.rng = rng

    def supports_payload(self, payload_length: int) -> bool:
        """Whether the encoded payload and assumed protocol header fit one frame."""
        return self.config.airtime_mode != "lora" or 1 <= payload_length + self.config.protocol_header_bytes <= 255

    def airtime_s(self, payload_length: int) -> float:
        if self.config.airtime_mode == "approximate":
            return self.config.airtime_base_s + payload_length * 0.0015
        return calculate_airtime(payload_length + self.config.protocol_header_bytes, self.config).total_s

    def observe(
        self,
        tx_position: tuple[float, float],
        rx_position: tuple[float, float],
        payload_length: int | None = None,
    ) -> LinkObservation:
        """Observe a frame, or probe a link without frame timing when length is None."""

        distance = max(1.0, math.dist(tx_position, rx_position))
        path_loss = 10.0 * self.config.path_loss_exponent * math.log10(
            distance / self.config.reference_distance_m
        )
        shadowing = self.rng.gauss(0.0, self.config.shadow_fading_std_db)
        rssi = self.config.reference_rssi_dbm - path_loss + shadowing
        noise_floor = self.config.noise_floor_dbm
        if self.config.airtime_mode == "lora":
            noise_floor = -174.0 + 10 * math.log10(self.config.bandwidth_hz) + self.config.receiver_noise_figure_db
        snr = rssi - noise_floor
        loss_rate = self.config.packet_loss_probability
        link_quality = calculate_link_quality(rssi, snr, loss_rate)
        airtime = self.airtime_s(payload_length) if payload_length is not None else 0.0
        delay = self.config.transmission_delay_s + airtime if payload_length is not None else 0.0

        if distance > self.config.max_range_m:
            return LinkObservation(False, rssi, snr, link_quality, delay, "outside_range", airtime)
        if rssi < receiver_sensitivity_dbm(self.config):
            return LinkObservation(False, rssi, snr, link_quality, delay, "rssi_below_sensitivity", airtime)
        if self.rng.random() < self.config.channel_busy_probability:
            return LinkObservation(False, rssi, snr, link_quality, delay, "channel_busy", airtime)
        if self.rng.random() < self.config.collision_probability:
            return LinkObservation(False, rssi, snr, link_quality, delay, "collision", airtime)
        if self.rng.random() < loss_rate:
            return LinkObservation(False, rssi, snr, link_quality, delay, "packet_loss", airtime)
        if self.config.interference_probability and self.rng.random() < self.config.interference_probability:
            return LinkObservation(False, rssi, snr, link_quality, delay, "interference", airtime)
        return LinkObservation(True, rssi, snr, link_quality, delay, airtime_s=airtime)
