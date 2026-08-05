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

Current automated result: **19 tests passed**.

## 3. Important simulator limitations that still require updates

### A. The routing engine is centralized

The dashboard currently rebuilds the complete topology graph and uses NetworkX shortest paths. This is useful for checking whether the proposed topology can support routes, but it is not a packet-by-packet decentralized implementation of ROUTE_ADVERTISEMENT learning.

For protocol-level validation, add:

- Per-node route advertisements.
- Route update propagation delays.
- Split horizon, sequence numbers, or another loop-prevention rule for route advertisements.
- Route expiry based on received advertisements.
- Route-error propagation when a next hop fails.

### B. LoRa timing remains approximate

The radio model should eventually calculate airtime from actual LoRa parameters:

- Frequency.
- Spreading factor.
- Bandwidth.
- Coding rate.
- Preamble length.
- Payload length.
- Explicit/implicit header mode.
- CRC mode.
- Low-data-rate optimization.

Also add regional duty-cycle or dwell-time limits when required by the selected band and jurisdiction.

### C. Collisions are probabilistic rather than event-derived

The present model uses configured probabilities for collision and channel busy events. A stronger model should track overlapping transmissions in time and frequency and apply capture-effect logic based on received power.

### D. The packet format is abstract

The Python packet payload is a dictionary. Firmware-alignment work should implement the same binary field sizes, scaling, endianness, header flags, CRC/MIC, and maximum packet size used on the embedded nodes.

### E. Security is only behaviourally simulated

The simulator can reject wrong Network IDs, invalid CRCs, and invalid authentication flags, but it does not yet calculate a real packet authentication code or encrypt payloads.

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
2. Implement decentralized route advertisements in the simulator.
3. Define one binary packet specification shared by Python and C++.
4. Correct the embedded forwarding and destination-filtering rules.
5. Add exact LoRa airtime and event-based collision modelling.
6. Compare simulator logs with three to five physical LoRa nodes.
7. Calibrate path loss and packet loss using measured RSSI, SNR, and delivery data.
8. Scale to the hotel and microgrid scenarios only after the small hardware topology matches the simulator.
