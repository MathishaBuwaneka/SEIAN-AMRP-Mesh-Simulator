"""Simulation metrics and export helpers."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Metrics:
    """Mutable metrics accumulator for one deterministic run."""

    packets_generated: int = 0
    unicast_packets_generated: int = 0
    unicast_packets_delivered: int = 0
    transmission_attempts: int = 0
    successful_link_transmissions: int = 0
    packets_transmitted: int = 0
    packets_delivered: int = 0
    packets_forwarded: int = 0
    packets_dropped: int = 0
    duplicate_drops: int = 0
    route_changes: int = 0
    collisions: int = 0
    channel_busy_events: int = 0
    emergency_sent: int = 0
    emergency_delivered: int = 0
    gateway_reachable_samples: int = 0
    gateway_total_samples: int = 0
    queue_delay_sum: float = 0.0
    queue_delay_max: float = 0.0
    latency_by_priority: dict[int, list[float]] = field(default_factory=lambda: defaultdict(list))
    drop_reasons: Counter[str] = field(default_factory=Counter)
    queue_drops_by_priority: Counter[int] = field(default_factory=Counter)
    throughput_by_time: Counter[int] = field(default_factory=Counter)
    _generated_packet_keys: set[tuple[str, int]] = field(default_factory=set, repr=False)
    _generated_unicast_keys: set[tuple[str, int]] = field(default_factory=set, repr=False)
    _delivered_unicast_keys: set[tuple[str, int]] = field(default_factory=set, repr=False)

    def record_packet_generated(
        self,
        packet_key: tuple[str, int],
        destination_id: str | None,
    ) -> None:
        """Count a newly created packet once, including unicast PDR eligibility."""

        if packet_key not in self._generated_packet_keys:
            self._generated_packet_keys.add(packet_key)
            self.packets_generated += 1
        if destination_id is not None and packet_key not in self._generated_unicast_keys:
            self._generated_unicast_keys.add(packet_key)
            self.unicast_packets_generated += 1

    def record_transmission_attempt(self) -> None:
        """Count one physical link transmission attempt."""

        self.transmission_attempts += 1
        self.packets_transmitted += 1

    def record_link_success(self) -> None:
        """Count a radio transmission that reached the receiving radio."""

        self.successful_link_transmissions += 1

    def record_final_delivery(
        self,
        packet_key: tuple[str, int],
        priority: int,
        latency: float,
    ) -> None:
        """Count one unique unicast destination delivery and its end-to-end latency."""

        if packet_key in self._delivered_unicast_keys:
            return
        self._delivered_unicast_keys.add(packet_key)
        self.unicast_packets_delivered += 1
        self.record_latency(priority, latency)

    def record_drop(self, reason: str) -> None:
        """Count a dropped packet and reason."""

        self.packets_dropped += 1
        self.drop_reasons[reason] += 1

    def record_latency(self, priority: int, latency: float) -> None:
        """Record end-to-end latency by priority."""

        self.latency_by_priority[priority].append(latency)

    def summary(self) -> dict[str, Any]:
        """Return dashboard/export-friendly summary metrics."""

        attempts = max(1, self.transmission_attempts)
        emergency_sent = max(1, self.emergency_sent)
        all_latencies = [v for values in self.latency_by_priority.values() for v in values]
        emergency_latencies = self.latency_by_priority.get(3, []) + self.latency_by_priority.get(4, [])
        return {
            "packet_delivery_ratio": (
                self.unicast_packets_delivered / self.unicast_packets_generated
                if self.unicast_packets_generated
                else 0.0
            ),
            "link_delivery_ratio": self.successful_link_transmissions / attempts,
            "average_latency_s": sum(all_latencies) / len(all_latencies) if all_latencies else 0.0,
            "emergency_delivery_ratio": self.emergency_delivered / emergency_sent,
            "emergency_latency_s": sum(emergency_latencies) / len(emergency_latencies) if emergency_latencies else 0.0,
            "packets_generated": self.packets_generated,
            "unicast_packets_generated": self.unicast_packets_generated,
            "unicast_packets_delivered": self.unicast_packets_delivered,
            "transmission_attempts": self.transmission_attempts,
            "successful_link_transmissions": self.successful_link_transmissions,
            "packets_transmitted": self.packets_transmitted,
            "packets_forwarded": self.packets_forwarded,
            "packets_dropped": self.packets_dropped,
            "duplicate_packets_suppressed": self.duplicate_drops,
            "route_changes": self.route_changes,
            "average_queue_delay_s": self.queue_delay_sum / attempts,
            "maximum_queue_delay_s": self.queue_delay_max,
            "channel_utilization_events": sum(self.throughput_by_time.values()),
            "collision_count": self.collisions,
            "gateway_reachability_percentage": (
                100.0 * self.gateway_reachable_samples / self.gateway_total_samples
                if self.gateway_total_samples
                else 0.0
            ),
        }
