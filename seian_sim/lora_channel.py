"""Approximate LoRa channel model for protocol research."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from seian_sim.config import LoraConfig


@dataclass(slots=True)
class LinkObservation:
    """Radio observation from one packet delivery attempt."""

    delivered: bool
    rssi: float
    snr: float
    link_quality: float
    delay_s: float
    drop_reason: str | None = None


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
        self.config = config
        self.rng = rng

    def observe(
        self,
        tx_position: tuple[float, float],
        rx_position: tuple[float, float],
        payload_length: int = 0,
    ) -> LinkObservation:
        """Return whether a packet can be delivered and the observed link values."""

        distance = max(1.0, math.dist(tx_position, rx_position))
        path_loss = 10.0 * self.config.path_loss_exponent * math.log10(
            distance / self.config.reference_distance_m
        )
        shadowing = self.rng.gauss(0.0, self.config.shadow_fading_std_db)
        rssi = self.config.reference_rssi_dbm - path_loss + shadowing
        snr = rssi - self.config.noise_floor_dbm
        loss_rate = self.config.packet_loss_probability
        link_quality = calculate_link_quality(rssi, snr, loss_rate)
        airtime = self.config.airtime_base_s + payload_length * 0.0015
        delay = self.config.transmission_delay_s + airtime

        if distance > self.config.max_range_m:
            return LinkObservation(False, rssi, snr, link_quality, delay, "outside_range")
        if rssi < self.config.sensitivity_dbm:
            return LinkObservation(False, rssi, snr, link_quality, delay, "rssi_below_sensitivity")
        if self.rng.random() < self.config.channel_busy_probability:
            return LinkObservation(False, rssi, snr, link_quality, delay, "channel_busy")
        if self.rng.random() < self.config.collision_probability:
            return LinkObservation(False, rssi, snr, link_quality, delay, "collision")
        if self.rng.random() < loss_rate:
            return LinkObservation(False, rssi, snr, link_quality, delay, "packet_loss")
        if self.config.interference_probability and self.rng.random() < self.config.interference_probability:
            return LinkObservation(False, rssi, snr, link_quality, delay, "interference")
        return LinkObservation(True, rssi, snr, link_quality, delay)
