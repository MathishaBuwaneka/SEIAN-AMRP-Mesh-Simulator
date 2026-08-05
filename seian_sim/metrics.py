"""Simulation metrics and export helpers."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Metrics:
    """Mutable metrics accumulator for one deterministic run."""

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

    def record_drop(self, reason: str) -> None:
        """Count a dropped packet and reason."""

        self.packets_dropped += 1
        self.drop_reasons[reason] += 1

    def record_latency(self, priority: int, latency: float) -> None:
        """Record end-to-end latency by priority."""

        self.latency_by_priority[priority].append(latency)

    def summary(self) -> dict[str, Any]:
        """Return dashboard/export-friendly summary metrics."""

        sent = max(1, self.packets_transmitted)
        emergency_sent = max(1, self.emergency_sent)
        all_latencies = [v for values in self.latency_by_priority.values() for v in values]
        emergency_latencies = self.latency_by_priority.get(3, []) + self.latency_by_priority.get(4, [])
        return {
            "packet_delivery_ratio": self.packets_delivered / sent,
            "average_latency_s": sum(all_latencies) / len(all_latencies) if all_latencies else 0.0,
            "emergency_delivery_ratio": self.emergency_delivered / emergency_sent,
            "emergency_latency_s": sum(emergency_latencies) / len(emergency_latencies) if emergency_latencies else 0.0,
            "packets_transmitted": self.packets_transmitted,
            "packets_forwarded": self.packets_forwarded,
            "packets_dropped": self.packets_dropped,
            "duplicate_packets_suppressed": self.duplicate_drops,
            "route_changes": self.route_changes,
            "average_queue_delay_s": self.queue_delay_sum / sent,
            "maximum_queue_delay_s": self.queue_delay_max,
            "channel_utilization_events": sum(self.throughput_by_time.values()),
            "collision_count": self.collisions,
            "gateway_reachability_percentage": (
                100.0 * self.gateway_reachable_samples / self.gateway_total_samples
                if self.gateway_total_samples
                else 0.0
            ),
        }
