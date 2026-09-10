# SEIAN Two-Plane Simulator Architecture

## Purpose

The simulator separates the **Communication and Coordination Plane (CCP)** from the **Electrical Plane (EP)**. Electrical values remain synthetic application data rather than power-flow or protection results, but the EP publishes a bounded route-suitability signal to the CCP. This explicit cross-plane input implements the proposal's grid-aware routing concept without coupling subsystem availability.

The central rule is:

> An EP fault is not automatically a CCP failure, and a CCP failure is not automatically an EP fault.

Plane separation does not mean plane isolation. An electrically unhealthy node can continue communicating while receiving a higher forwarding cost. It remains usable when no alternative path exists.

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
- Route calculation, cross-plane risk weighting, backup next hops, forwarding, and route recovery.
- Priority queues, communication load, congestion, and duplicate suppression.
- Fault-alert transport, acknowledgements, gateway delivery, and communication failures.

The node communication state consists of `communication_status`, `communication_health`, `communication_fault_status`, `communication_load`, `communication_congestion`, and `link_reliability`. The legacy `active` field is retained for topology-file and dashboard compatibility, but CCP code reads `communication_available`.

## Electrical Plane

The EP state remains represented by electrical measurements, `health_score`, `load_percent`, `fault_status`, and `power_stage_operational`. The `power_health` and `power_fault_status` properties provide explicit names while preserving existing exports and UI behavior.

The CCP transports `GRID_STATE_UPDATE`, `FAULT_ALERT`, and `CONTROL_COORDINATION` payloads. For route selection it consumes normalized health, load, and fault penalties published by the EP. It does not calculate power flow, protection action, P/Q dispatch, or electrical control decisions.

## Route Cost

Both the decentralized routing mode and centralized topology oracle use this cross-plane cost:

```text
W1 * HopCount
+ W2 * LinkQualityPenalty
+ W3 * CommunicationHealthPenalty
+ W4 * CommunicationCongestionPenalty
+ W5 * CommunicationFaultPenalty
+ K * (W6 * PowerHealthPenalty + W7 * PowerLoadPenalty + W8 * PowerFaultPenalty)
+ W9 * GatewayPreference
```

`K` is the `cross_plane_risk` multiplier. It defaults to `1.0` and can be set to zero for a communication-only experimental baseline. Power health is clamped to `0..1`, load is converted to a bounded `0..1` value, and fault state maps to a bounded penalty. Raw voltage, frequency, and phase values do not directly enter route cost; they first affect the EP's health/fault state.

Communication availability remains a hard routing condition. Electrical risk is a soft cost: it can make a healthier path preferable but cannot by itself remove a radio-capable node from the mesh.

The decentralized engine exchanges normalized communication and electrical-risk inputs in `ROUTE_ADVERTISEMENT` packets. NetworkX remains available as an explicit topology oracle and comparison baseline; it is not used to install routes in decentralized mode.

## Fault Domains

Every `FaultEvent` has a `fault_domain`:

- `POWER`: voltage, frequency, phase, overload, short-circuit, and islanding events.
- `COMMUNICATION`: communication loss.
- `DEVICE`: inverter overtemperature and device-local events.

Power and device faults update EP state and route suitability without disabling CCP. A communication failure updates CCP state, removes the relay from active routes, and records `ROUTE_ERROR` behavior without changing EP state.

## Packet Semantics

- `HELLO` and `HELLO_REPLY` discover immediate radio transmitters and populate communication-only neighbor entries.
- `GRID_STATE_UPDATE` carries application measurements. Receiving arbitrary payload values does not directly mutate routing state; validated local EP state is published through the explicit cross-plane boundary.
- `FAULT_ALERT` carries `fault_id`, `fault_type`, `fault_domain`, severity, and a recommendation label.
- `FAULT_ACK` acknowledges alert receipt and processing only; it does not claim the underlying fault was corrected.
- `ROUTE_ERROR` represents communication-route failure only.
- `CONTROL_COORDINATION` transports a recommendation to a controller boundary; CCP does not execute electrical control.

## Compatibility Boundary

Existing topology files may continue using `active`, `health_score`, and `load_percent`. New topology exports also include explicit CCP fields, `power_stage_operational`, and `fault_status`, allowing electrical route suitability to survive export/import. Existing `FaultEvent` fields required by the controller adapter remain unchanged, with `fault_domain` added as an extension.
