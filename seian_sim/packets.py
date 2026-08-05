"""Packet model, priorities, and duplicate cache."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from seian_sim.enums import PacketType


PRIORITY_BACKGROUND = 0
PRIORITY_TELEMETRY = 1
PRIORITY_CONTROL = 2
PRIORITY_FAULT = 3
PRIORITY_EMERGENCY = 4


@dataclass(slots=True)
class Packet:
    """Common SEIAN-AMRP packet."""

    version: int
    packet_type: PacketType
    source_id: str
    origin_id: str
    destination_id: str | None
    sequence_number: int
    priority: int
    hop_count: int
    ttl: int
    timestamp: float
    flags: dict[str, Any] = field(default_factory=dict)
    payload_length: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    crc_valid: bool = True
    authentication_valid: bool = True
    network_id: str = "SEIAN-LAB"
    key_id: str = "demo-key"
    path: list[str] = field(default_factory=list)

    @property
    def duplicate_key(self) -> tuple[str, int]:
        """Return the cache key used for duplicate suppression."""

        return (self.origin_id, self.sequence_number)

    def forwarded(self, new_source_id: str, timestamp: float) -> "Packet":
        """Create a forwarded packet with decremented TTL and extended path."""

        return Packet(
            version=self.version,
            packet_type=self.packet_type,
            source_id=new_source_id,
            origin_id=self.origin_id,
            destination_id=self.destination_id,
            sequence_number=self.sequence_number,
            priority=self.priority,
            hop_count=self.hop_count + 1,
            ttl=self.ttl - 1,
            timestamp=timestamp,
            flags=dict(self.flags),
            payload_length=self.payload_length,
            payload=dict(self.payload),
            crc_valid=self.crc_valid,
            authentication_valid=self.authentication_valid,
            network_id=self.network_id,
            key_id=self.key_id,
            path=[*self.path, new_source_id],
        )


class DuplicateCache:
    """Bounded recent-packet cache keyed by origin and sequence number."""

    def __init__(self, max_size: int = 512) -> None:
        self.max_size = max_size
        self._items: OrderedDict[tuple[str, int], float] = OrderedDict()

    def seen(self, packet: Packet, timestamp: float) -> bool:
        """Return True if packet has been observed; otherwise remember it."""

        key = packet.duplicate_key
        if key in self._items:
            self._items.move_to_end(key)
            return True
        self._items[key] = timestamp
        if len(self._items) > self.max_size:
            self._items.popitem(last=False)
        return False

    def __len__(self) -> int:
        return len(self._items)
