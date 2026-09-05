"""Physical PSCAD fault-event contract for SEIAN experiments."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable


FAULT_TYPE_FLAGS: dict[str, tuple[int, int, int, int]] = {
    "a_ground": (1, 0, 0, 1),
    "b_ground": (0, 1, 0, 1),
    "c_ground": (0, 0, 1, 1),
    "ab_ground": (1, 1, 0, 1),
    "bc_ground": (0, 1, 1, 1),
    "ca_ground": (1, 0, 1, 1),
    "abc_ground": (1, 1, 1, 1),
    "ab": (1, 1, 0, 0),
    "bc": (0, 1, 1, 0),
    "ca": (1, 0, 1, 0),
    "abc": (1, 1, 1, 0),
}

_FAULT_TYPE_ALIASES = {
    "ag": "a_ground",
    "bg": "b_ground",
    "cg": "c_ground",
    "abg": "ab_ground",
    "bcg": "bc_ground",
    "cag": "ca_ground",
    "abcg": "abc_ground",
    "three_phase_ground": "abc_ground",
    "three_phase_to_ground": "abc_ground",
    "three_phase": "abc",
}


@dataclass(slots=True, frozen=True)
class PhysicalFaultEvent:
    """One physical fault interval represented by PSCAD timed fault logic."""

    fault_id: str
    node_id: str
    start_s: float
    duration_s: float
    fault_type: str = "abc_ground"
    resistance_ohm: float = 0.05

    @property
    def end_s(self) -> float:
        return self.start_s + self.duration_s

    @property
    def phase_flags(self) -> dict[str, int]:
        a, b, c, ground = FAULT_TYPE_FLAGS[self.fault_type]
        return {"A": a, "B": b, "C": c, "G": ground}

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["end_s"] = self.end_s
        payload["phase_flags"] = self.phase_flags
        return payload


def physical_faults_from_payload(
    payload: Any,
    *,
    known_nodes: Iterable[str] | None = None,
) -> list[PhysicalFaultEvent]:
    """Parse a root payload or bare list into validated physical faults."""

    if payload is None:
        return []
    rows = payload.get("physical_faults", []) if isinstance(payload, dict) else payload
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValueError("physical_faults must be a list.")

    node_ids = {str(node) for node in known_nodes} if known_nodes is not None else None
    faults: list[PhysicalFaultEvent] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"physical_faults[{index}] must be an object.")

        fault_id = str(row.get("fault_id", "")).strip()
        node_id = str(row.get("node_id", row.get("origin_node", ""))).strip()
        if not fault_id:
            raise ValueError(f"physical_faults[{index}] must include fault_id.")
        if fault_id in seen_ids:
            raise ValueError(f"Duplicate physical fault ID: {fault_id}")
        if not node_id:
            raise ValueError(f"{fault_id}: node_id is required.")
        if node_ids is not None and node_id not in node_ids:
            raise ValueError(f"{fault_id}: unknown fault node {node_id}.")

        start_s = _finite(row.get("start_s", row.get("start_time", 0.0)), f"{fault_id} start_s")
        duration_s = _finite(row.get("duration_s", row.get("duration", 0.0)), f"{fault_id} duration_s")
        resistance_ohm = _finite(
            row.get("resistance_ohm", row.get("fault_resistance_ohm", 0.05)),
            f"{fault_id} resistance_ohm",
        )
        if start_s < 0:
            raise ValueError(f"{fault_id} start_s must be non-negative.")
        if duration_s <= 0:
            raise ValueError(f"{fault_id} duration_s must be greater than zero.")
        if resistance_ohm < 0:
            raise ValueError(f"{fault_id} resistance_ohm must be non-negative.")

        fault_type = _normalize_fault_type(row.get("fault_type", "abc_ground"), fault_id)
        faults.append(
            PhysicalFaultEvent(
                fault_id=fault_id,
                node_id=node_id,
                start_s=start_s,
                duration_s=duration_s,
                fault_type=fault_type,
                resistance_ohm=resistance_ohm,
            )
        )
        seen_ids.add(fault_id)

    return sorted(faults, key=lambda fault: (fault.start_s, fault.fault_id))


def _normalize_fault_type(value: Any, fault_id: str) -> str:
    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    normalized = _FAULT_TYPE_ALIASES.get(normalized, normalized)
    if normalized not in FAULT_TYPE_FLAGS:
        supported = ", ".join(sorted(FAULT_TYPE_FLAGS))
        raise ValueError(f"{fault_id}: unsupported fault_type '{value}'; choose one of {supported}.")
    return normalized


def _finite(value: Any, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite.")
    return number
