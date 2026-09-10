"""Validated payloads for decentralized route-control packets."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


def _nonempty_identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _integer(value: Any, field_name: str, minimum: int, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer.")
    if value < minimum or (maximum is not None and value > maximum):
        upper = f" and at most {maximum}" if maximum is not None else ""
        raise ValueError(f"{field_name} must be at least {minimum}{upper}.")
    return value


def _finite_number(
    value: Any,
    field_name: str,
    minimum: float,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric.")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite.")
    if number < minimum or (maximum is not None and number > maximum):
        upper = f" and at most {maximum}" if maximum is not None else ""
        raise ValueError(f"{field_name} must be at least {minimum}{upper}.")
    return number


@dataclass(frozen=True, slots=True)
class RouteAdvertisement:
    """One destination route advertised to direct radio neighbors."""

    destination_id: str
    destination_sequence: int
    hop_count: int
    route_cost: float
    lifetime_s: float
    advertised_next_hop: str | None
    gateway_path: bool
    electrical_risk: float
    communication_health: float
    communication_congestion: float
    communication_fault_status: str

    def to_payload(self) -> dict[str, Any]:
        """Return a packet-payload representation."""

        return asdict(self)

    @classmethod
    def from_payload(cls, payload: Any, *, max_hops: int) -> "RouteAdvertisement":
        """Validate and decode an abstract packet payload."""

        if not isinstance(payload, dict):
            raise ValueError("Route advertisement payload must be an object.")
        advertised_next_hop = payload.get("advertised_next_hop")
        if advertised_next_hop is not None:
            advertised_next_hop = _nonempty_identifier(
                advertised_next_hop,
                "advertised_next_hop",
            )
        gateway_path = payload.get("gateway_path")
        if not isinstance(gateway_path, bool):
            raise ValueError("gateway_path must be a boolean.")
        return cls(
            destination_id=_nonempty_identifier(payload.get("destination_id"), "destination_id"),
            destination_sequence=_integer(
                payload.get("destination_sequence"),
                "destination_sequence",
                0,
            ),
            hop_count=_integer(payload.get("hop_count"), "hop_count", 0, max_hops),
            route_cost=_finite_number(payload.get("route_cost"), "route_cost", 0.0),
            lifetime_s=_finite_number(payload.get("lifetime_s"), "lifetime_s", 0.001),
            advertised_next_hop=advertised_next_hop,
            gateway_path=gateway_path,
            electrical_risk=_finite_number(
                payload.get("electrical_risk"),
                "electrical_risk",
                0.0,
                1.0,
            ),
            communication_health=_finite_number(
                payload.get("communication_health"),
                "communication_health",
                0.0,
                1.0,
            ),
            communication_congestion=_finite_number(
                payload.get("communication_congestion"),
                "communication_congestion",
                0.0,
                1.0,
            ),
            communication_fault_status=_communication_fault_status(
                payload.get("communication_fault_status")
            ),
        )


@dataclass(frozen=True, slots=True)
class RouteErrorMessage:
    """A destination invalidation sent after next-hop failure."""

    destination_id: str
    destination_sequence: int
    failed_next_hop: str
    reason: str

    def to_payload(self) -> dict[str, Any]:
        """Return a packet-payload representation."""

        return asdict(self)

    @classmethod
    def from_payload(cls, payload: Any) -> "RouteErrorMessage":
        """Validate and decode an abstract packet payload."""

        if not isinstance(payload, dict):
            raise ValueError("Route error payload must be an object.")
        return cls(
            destination_id=_nonempty_identifier(payload.get("destination_id"), "destination_id"),
            destination_sequence=_integer(
                payload.get("destination_sequence"),
                "destination_sequence",
                0,
            ),
            failed_next_hop=_nonempty_identifier(
                payload.get("failed_next_hop"),
                "failed_next_hop",
            ),
            reason=_nonempty_identifier(payload.get("reason"), "reason"),
        )


def _communication_fault_status(value: Any) -> str:
    allowed = {"normal", "warning", "fault"}
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(
            "communication_fault_status must be normal, warning, or fault."
        )
    return value
