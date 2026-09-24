# SEIAN Mesh Simulator — Implementation Status

This document separates the capabilities that were already present in the uploaded simulator, the changes made in this topology-focused update, and the work still required before the simulator can be treated as a faithful implementation of the embedded SEIAN-AMRP firmware.

## 1. Already present in the uploaded simulator

The uploaded Python project was already a substantial simulator rather than an empty starter. It contained:

- A Streamlit dashboard.
- Built-in five-node, hotel microgrid, gateway-failure, fault-propagation, congestion, and security scenarios.
- Manual node add, move, remove, failure, and recovery controls.
- Approximate distance-based LoRa RSSI, SNR, packet-loss, collision, and channel-busy modelling.
- HELLO-style neighbor discovery and neighbor tables.
- Grid-aware route-cost calculation using hop count, link quality, health, load, fault state, and gateway preference.
- Routing tables with primary and backup next hops.
- Grid-state telemetry and gateway caching.
- Fault-alert flooding, TTL, duplicate suppression, fault acknowledgements, and control-coordination packets.
- Gateway enable/disable behaviour.
- Packet, route, grid, fault, and event exports.
- Automated tests for discovery, routing, duplicate suppression, faults, gateway failure, and packet validation.

## 2. Added or corrected in this update

### Topology checking

- Connectivity status and connected-component detection.
- Isolated-node detection.
- Gateway-reachable and gateway-unreachable node lists.
- Route tracing between any selected source and destination.
- Selected-route highlighting on the topology graph.
- Articulation-point detection for critical relay nodes.
- Bridge-link detection for links with no alternate physical path.
- Physical-link table containing distance, average RSSI, SNR, link quality, directionality, and bridge status.
- Single-node failure impact analysis showing which nodes lose gateway reachability.
- Invalid route and asymmetric-neighbor checks.
- Mesh density, average node degree, and largest-component diameter.

### Interactive network creation

- Added **Create own network** as a network setup option.
- Added a click-to-place Plotly canvas in a dedicated **Network Builder** tab.
- Added standard-node and gateway-node placement tools.
- Added direct node selection, movement, and deletion on the canvas.
- Added placement snapping, automatic/custom Node IDs, undo, clear-all, and route-rebuild controls.
- Added optional visual LoRa coverage circles.
- Kept the exact-coordinate sidebar editor as a fallback for precise placement.
- Added pure, independently tested canvas-event and builder-action logic.

### Usability

- Repeatable random-topology creation with configurable node and gateway counts.
- Reloadable topology JSON import.
- Topology JSON, topology-analysis JSON, physical-link CSV, and failure-impact CSV exports.
- A dedicated **Topology Check** dashboard tab.
- Clear dashboard findings classified as errors or warnings.

### Correctness fixes

- Removed the unnecessary SimPy dependency and replaced it with a small deterministic clock.
- Corrected queue overflow logic so emergency traffic can evict low-priority telemetry instead of accidentally removing the highest-priority packet.
- Removed duplicate packet-event recording that counted one physical delivery twice.
- Added automated tests for topology analysis, route tracing, gateway outage classification, and priority queue eviction.
- Preserved the original packet creation timestamp across forwarding hops.
- Applied the approximate LoRa link delay in both manual and batch packet forwarding.
- Separated generated unicasts, physical transmission attempts, successful radio transmissions, accepted receptions, and final destination deliveries.
- Defined PDR from unique final unicast deliveries divided by unique generated unicasts.
- Restricted latency metrics to end-to-end final unicast deliveries.

### Communication/electrical plane separation

- Added explicit communication status, health, fault, load, congestion, and link-reliability state.
- Retained electrical measurements and legacy fields as separate application/EP state.
- Changed route cost to combine communication factors with explicit, bounded electrical health, load, and fault penalties.
- Added an explicit cross-plane routing boundary: normalized electrical health, load, and fault penalties influence route preference without controlling radio availability.
- Added a configurable `cross_plane_risk` multiplier that can disable electrical influence for communication-only baseline experiments.
- Added electrical state to neighbour observations and topology round-trip exports.
- Added route recalculation after electrical fault, power-stage failure, and recovery actions.
- Defined and validated abstract `ROUTE_ADVERTISEMENT` and `ROUTE_ERROR` payload contracts for the decentralized-routing update.
- Added `POWER`, `COMMUNICATION`, and `DEVICE` fault domains.
- Kept power-faulted nodes available for packet origination and relay forwarding when their radios remain healthy.
- Made communication failure and recovery independent from power-stage failure and recovery.
- Defined `FAULT_ACK` as acknowledgement of alert receipt, not confirmation that a fault was corrected.
- Added explicit `fault_domain` fields to fault-alert and control-coordination payloads.
- Added regression tests for independent CCP/EP state and transport-only grid data.

The detailed contract is documented in `docs/TWO_PLANE_ARCHITECTURE.md`.

Historical routing-branch result: **72 tests passed**. The integrated airtime
branch includes both mesh and power-plane tests; see the root README for the total.

## 3. Important simulator limitations that still require updates

### A. Decentralized routing is simulator-only

The dashboard supports decentralized packet-driven routing and a separate NetworkX oracle baseline. In decentralized mode, nodes learn routes only from received `ROUTE_ADVERTISEMENT` packets, retain alternate candidates, apply sequence freshness and split horizon, expire stale entries, and propagate `ROUTE_ERROR` after active-next-hop failure.

The route-control payload schema and update rules are specified in `docs/ROUTE_ADVERTISEMENT_SPEC.md`. The remaining alignment work is to implement the same behavior and binary representation in the embedded firmware.

Further protocol-level validation should add:

- Larger convergence and partition scenarios.
- Transient packet-loss measurements during convergence.
- Poison reverse comparison against the implemented split-horizon rule.
- Repeated seeded experiments for control overhead and convergence time.

### B. Exact frame timing is selectable; packet encoding remains provisional

The optional exact mode now calculates frame airtime from these LoRa parameters:

- Frequency.
- Spreading factor.
- Bandwidth.
- Coding rate.
- Preamble length.
- Payload length.
- Explicit/implicit header mode.
- CRC mode.
- Low-data-rate optimization.

See [the airtime model](LORA_AIRTIME_MODEL.md) for reference vectors, UTF-8 encoding,
the assumed protocol-header budget, and oversize rejection. Approximate mode remains
the default for current JSON routing experiments. Regional duty-cycle or dwell-time
limits still require the deployment band and jurisdiction to be confirmed.

### C. Collisions are probabilistic rather than event-derived

The present model uses configured probabilities for collision and channel busy events. A stronger model should track overlapping transmissions in time and frequency and apply capture-effect logic based on received power.

### D. Binary codec implemented; firmware application integration remains

Selectable Binary v1 provides matching Python/C++ codecs, numeric addresses,
typed compact payloads, real CRC-16, and a 255-byte frame limit. Host interoperability
tests pass and the codec compiles for ESP32. The repository has no firmware
application to integrate or flash; device behavior and real radio operation remain
unvalidated. See [the shared binary contract](BINARY_PACKET_FORMAT.md).

### E. Security is only behaviourally simulated

Binary mode calculates and verifies CRC-16; injected validity flags remain available
for simulation. There is no real packet authentication code, encryption, or replay
window. CRC detects corruption but does not authenticate senders.

### F. Grid behaviour is simplified

The electrical values are suitable for communication demonstrations only. They are not an electromagnetic transient model, a protection study, or a validated distributed-control model.

### G. More validation scenarios are needed

Add repeatable experiments for:

- Network scaling: 20, 50, 100, and more nodes.
- Several gateway placements.
- Sparse, line, grid, star, clustered, and random topologies.
- Moving or intermittently available nodes.
- Hidden-node collisions.
- Near-far capture.
- Burst telemetry during a fault.
- Multiple simultaneous faults.
- Network-ID overlap with an unrelated nearby mesh.
- Firmware version mismatch and key-ID mismatch.

## 4. Embedded C++ alignment issues to fix before hardware comparison

The uploaded ESP32/LoRa MVP is useful as a starting point, but the following items should be corrected before claiming that the simulator and hardware execute the same routing protocol:

1. `handleHelloReply()` calls `handleHello()`, and `handleHello()` sends another HELLO_REPLY. Because each response receives a new sequence number, this can create repeated reply traffic.
2. ROUTE_ADVERTISEMENT transmission and parsing are not implemented, so the firmware mainly learns direct routes rather than complete decentralized multi-hop routes.
3. The calculated next hop is not represented as a separate link-layer receiver field. LoRa transmission is broadcast, and receivers do not consistently filter packets based on an intended next hop.
4. Incoming unicast packets are handled without an early check that the current node is the final destination or intended forwarding node.
5. GRID_STATE_UPDATE uses the packet origin as a neighbor while RSSI/SNR describe the immediate transmitter. A neighbor table must contain one-hop transmitters; multi-hop origins belong in the routing table.
6. Priority values exist, but there is no outgoing priority queue or channel scheduler that guarantees fault traffic is sent before telemetry.
7. Node-health arithmetic uses an unsigned value and can underflow after several penalties. Calculate health with a signed integer and clamp it before converting to `uint8_t`.
8. Some minimum payload-length checks are one byte too small for the fields that are read.
9. CRC provides error detection, not source authentication. A real MIC and replay window are still required.
10. ACK timeout, retransmission, retry limits, and route-error recovery are not fully implemented.

## 5. Recommended development order

1. Use this dashboard to design node placement and identify disconnected, isolated, and critical-relay locations.
2. Compare decentralized advertisements against the NetworkX oracle baseline.
3. Define one binary packet specification shared by Python and C++.
4. Correct the embedded forwarding and destination-filtering rules.
5. Review the exact-airtime branch and add event-based collision modelling.
6. Compare simulator logs with three to five physical LoRa nodes.
7. Calibrate path loss and packet loss using measured RSSI, SNR, and delivery data.
8. Scale to the hotel and microgrid scenarios only after the small hardware topology matches the simulator.
