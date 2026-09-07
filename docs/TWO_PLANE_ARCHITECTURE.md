# SEIAN Two-Plane Simulator Architecture

## Purpose

The simulator separates the **Communication and Coordination Plane (CCP)** from the **Electrical Plane (EP)**. The root Python simulator implements and evaluates CCP behavior. Electrical values remain synthetic application data used to exercise packet transport and fault reporting.

The central rule is:

> An EP fault is not automatically a CCP failure, and a CCP failure is not automatically an EP fault.

This permits all four valid states:

| CCP | EP | Expected behavior |
|---|---|---|
| operational | operational | Normal measurement and packet transport |
| operational | failed | The node can report its power fault and relay packets |
| failed | operational | The power stage remains operational but the node cannot participate in the mesh |
| failed | failed | Neither packet transport nor normal power-stage operation is available |

## Communication and Coordination Plane

The CCP owns:

- LoRa link observation, discovery, and neighbor expiry.
- Communication-only neighbor state.
- Route calculation, backup next hops, forwarding, and route recovery.
- Priority queues, communication load, congestion, and duplicate suppression.
- Fault-alert transport, acknowledgements, gateway delivery, and communication failures.

The node communication state consists of `communication_status`, `communication_health`, `communication_fault_status`, `communication_load`, `communication_congestion`, and `link_reliability`. The legacy `active` field is retained for topology-file and dashboard compatibility, but CCP code reads `communication_available`.

## Electrical Plane

The EP state remains represented by electrical measurements, `health_score`, `fault_status`, and `power_stage_operational`. The `power_health` and `power_fault_status` properties provide explicit names while preserving existing exports and UI behavior.

The CCP transports `GRID_STATE_UPDATE`, `FAULT_ALERT`, and `CONTROL_COORDINATION` payloads. It does not calculate power flow, protection action, P/Q dispatch, or electrical control decisions.

## Route Cost

The centralized topology oracle currently uses this communication-only cost:

```text
W1 * HopCount
+ W2 * LinkQualityPenalty
+ W3 * CommunicationHealthPenalty
+ W4 * CommunicationCongestionPenalty
+ W5 * CommunicationFaultPenalty
+ W6 * GatewayPreference
```

Voltage, frequency, phase angle, inverter electrical load, power health, and power fault state do not directly affect route cost. `cross_plane_risk` exists as a disabled configuration placeholder with a default weight of zero and is not part of the current route calculation.

The routing engine remains centralized and NetworkX-based. Decentralized `ROUTE_ADVERTISEMENT` learning is intentionally deferred to a separate change.

## Fault Domains

Every `FaultEvent` has a `fault_domain`:

- `POWER`: voltage, frequency, phase, overload, short-circuit, and islanding events.
- `COMMUNICATION`: communication loss.
- `DEVICE`: inverter overtemperature and device-local events.

Power and device faults update EP state without disabling CCP. A communication failure updates CCP state, removes the relay from active routes, and records `ROUTE_ERROR` behavior without changing EP state.

## Packet Semantics

- `HELLO` and `HELLO_REPLY` discover immediate radio transmitters and populate communication-only neighbor entries.
- `GRID_STATE_UPDATE` carries application measurements without changing route selection.
- `FAULT_ALERT` carries `fault_id`, `fault_type`, `fault_domain`, severity, and a recommendation label.
- `FAULT_ACK` acknowledges alert receipt and processing only; it does not claim the underlying fault was corrected.
- `ROUTE_ERROR` represents communication-route failure only.
- `CONTROL_COORDINATION` transports a recommendation to a controller boundary; CCP does not execute electrical control.

## Compatibility Boundary

Existing topology files may continue using `active`, `health_score`, and `load_percent`. New topology exports also include explicit CCP fields and `power_stage_operational`. Existing `FaultEvent` fields required by the controller adapter remain unchanged, with `fault_domain` added as an extension.
