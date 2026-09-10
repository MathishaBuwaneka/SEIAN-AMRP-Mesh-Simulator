# SEIAN Simulator Status and Remaining Work Report

Date: 2026-09-10
Current branch: `feature/timing-metrics-foundation`

## 1. Project Objective

SEIAN is intended to evaluate a resilient LoRa mesh in which inverter health and grid-state information influence communication routing. The simulator should eventually provide defensible answers to these questions:

1. Can packets reach their destination through multiple LoRa relays?
2. Can the mesh continue local communication without an online gateway?
3. How quickly does routing recover after a relay becomes unavailable?
4. Does priority handling improve urgent fault-message delivery?
5. Does grid-aware routing outperform hop-count or link-only routing when a relay becomes electrically unhealthy, overloaded, faulted, congested, or communication-degraded?

The current program is already useful for topology design, demonstrations, and controlled protocol experiments. It must not yet be described as a complete LoRa physical-layer model, decentralized routing implementation, electrical power-flow simulator, or protection simulator.

## 2. Current Implemented Capabilities

### Network and topology

- Built-in, random, imported, and manually created topologies.
- Coordinate-based and canvas-based node placement.
- Approximate LoRa-range neighbour discovery.
- Connected-component, isolated-node, articulation-point, bridge-link, and gateway-reachability analysis.
- Route tracing and single-node failure-impact analysis.

### Routing and resilience

- Cross-plane route cost using hop count, link quality, communication health, congestion, communication fault state, bounded electrical health/load/fault penalties, and gateway preference.
- Primary and backup next-hop selection.
- Node failure, recovery, gateway loss, and gateway restoration controls.
- Continued local mesh operation while gateway backhaul is offline.

### Packet behaviour

- Manual one-link-per-Forward packet tracing.
- Batch heartbeat and grid-state traffic.
- Unicast, broadcast, controlled fault flooding, TTL, duplicate suppression, and fault acknowledgements.
- Priority queues for background, telemetry, control, fault, and emergency traffic.
- Network-ID, CRC flag, authentication flag, malformed-payload, and replay-behaviour checks.

### Grid-state demonstrations

- Simplified voltage, frequency, phase, current, power, load, temperature, power factor, and THD values.
- Simplified spatial fault injection and fault-boundary classification.
- Grid-state and power-fault payload transport with an explicit electrical-risk boundary into route selection.
- Electrical faults can penalize relay selection without disabling a healthy radio; communication failures remain independent.

### Dashboard and exports

- Network Builder, Packet Simulation, Topology Check, Node Details, Protocol Metrics, Grid Charts, Event Log, and Export Results tabs.
- JSON and CSV exports for topology, tables, measurements, packet events, routes, faults, and logs.

## 3. Timing, Metrics, and Cross-Plane Routing Foundation

The current branch corrects the first major measurement problem and restores the proposal's grid-aware routing principle without coupling electrical and communication availability.

### Packet timestamps

- The original packet creation timestamp is preserved across relays.
- A separate latest-forwarding time is retained.
- The latest physically transmitted packet is retained in manual mode.
- Source, hop count, TTL, and path continue to change during forwarding while origin and sequence identity remain unchanged.

### Simulated transmission time

- Manual Forward advances simulated time by the approximate LoRa link delay.
- Batch packet delivery also advances simulated time by the approximate link delay.
- Multi-hop end-to-end latency accumulates all serialized link delays.

### Metric definitions

- `packets_generated`: all unique packets created.
- `unicast_packets_generated`: unique packets created with a final destination.
- `unicast_packets_delivered`: unique packets reaching their final destination.
- `transmission_attempts`: physical one-link radio attempts, including failed attempts.
- `successful_link_transmissions`: attempts that reach the receiving radio.
- `packets_delivered`: accepted link-level receptions, including intermediate relays.
- `packet_delivery_ratio`: final unicast deliveries divided by generated unicasts.
- `link_delivery_ratio`: successful radio links divided by transmission attempts.
- `average_latency_s`: end-to-end latency across final unicast deliveries.

### Packet Simulation display

The dashboard now separates:

1. Original logical packet header.
2. Last transmitted header.
3. Simulator-only timing metadata.
4. Application payload.

This prevents simulator metadata from being mistaken for the future binary ESP32 packet header.

### Cross-plane routing correction

- Electrical and communication failures remain independent.
- Electrical health, load, and fault state now contribute bounded, weighted route penalties.
- A power-faulted node remains available as a relay when its communication subsystem is healthy.
- A healthier alternate relay is preferred when the electrical penalty makes its total route cost lower.
- `cross_plane_risk=0` provides a communication-only baseline for later experiments.
- Neighbour observations and topology export/import preserve the electrical routing state.

### Verified examples

For `N05 -> N03 -> N01`, the simulator produced:

- Two physical transmission attempts.
- Two successful radio transmissions.
- One generated and delivered unicast.
- 100% end-to-end PDR.
- Approximately 0.971 seconds of accumulated latency using the current approximate delay model.

A disconnected destination correctly produces `NO_ROUTE`, no radio attempt, no destination delivery, and 0% PDR when it is the only generated unicast.

### Automated status

- Original tests retained: 27.
- New timing/metrics tests added: 5.
- Cross-plane and electrical route-penalty tests added: 15.
- Current total: 47 passing tests.
- Streamlit application smoke test: no application exceptions.

## 4. Current Branch Work Still to Finish

Before beginning another major feature:

1. Review the complete cross-plane routing diff for naming and compatibility.
2. Run `git diff --check`.
3. Run the complete 47-test suite once more.
4. Manually verify healthy-alternate routing, only-path fallback, recovery, and one `NO_ROUTE` trace.
5. Commit and push the cross-plane correction to the existing branch.
6. Open or update the pull request and merge after review.

Suggested commit message:

```text
Add reliable timing metrics and grid-aware route penalties
```

## 5. Priority 1: Decentralized Route Learning

### Current problem

The protocol engine currently creates a complete NetworkX graph and immediately calculates globally optimal paths. This is valuable as a topology-analysis oracle, but real inverter nodes do not possess complete network knowledge.

Immediate recalculation also prevents realistic measurement of route-advertisement propagation, stale routes, transient loops, and convergence time after failure.

### Required implementation

- Keep NetworkX routing available only as an analysis baseline or oracle.
- Give every node ownership of its own routing table.
- Create actual `ROUTE_ADVERTISEMENT` packet payloads.
- Advertise destination, cost, hop count, destination sequence/version, and route lifetime.
- Process advertisements only when a node receives them.
- Add periodic advertisements and triggered updates.
- Add route ageing and expiry without global rebuilding.
- Add split horizon, poison reverse, destination sequence numbers, or another explicit loop-prevention rule.
- Generate and propagate `ROUTE_ERROR` when an active next hop fails.
- Switch to a valid backup route when available.
- Measure convergence from failure detection until a stable replacement route is learned.

### Required tests

- Three-node line learns a two-hop route through advertisements.
- Diamond topology learns primary and backup routes.
- Route advertisements do not create loops.
- Stale routes expire.
- Relay failure creates a route error.
- Alternate route becomes active after measurable convergence delay.
- Partitioned nodes remain unreachable.
- Grid-health changes trigger an advertisement and route change.

### Required metrics

- Route convergence time.
- Advertisement packets and bytes.
- Route-error packets and bytes.
- Route changes per node.
- Transient packet loss during convergence.
- Loop detections.
- Control overhead as a fraction of total traffic.

## 6. Priority 2: Exact LoRa Airtime

### Current problem

Airtime is currently a base delay plus a value proportional to JSON payload length. This is useful for demonstrations but is not a LoRa PHY calculation.

### Required implementation

- Add frequency, spreading factor, bandwidth, coding rate, preamble length, header mode, CRC mode, and low-data-rate optimisation settings.
- Calculate symbol duration, preamble duration, payload symbols, and total time-on-air.
- Use encoded packet length rather than JSON string length.
- Add receiver sensitivity appropriate to configured radio parameters.
- Add jurisdiction-specific duty-cycle or dwell-time rules after the deployment band is confirmed.

### Required tests

- Airtime matches trusted reference vectors for several LoRa configurations.
- Increasing spreading factor increases airtime.
- Increasing bandwidth reduces airtime.
- Larger payloads increase airtime.
- Low-data-rate optimisation is applied when required.

## 7. Priority 3: Event-Based Shared Radio Channel

### Current problem

Batch transmissions currently consume time serially. Collision and channel-busy outcomes are selected from configured probabilities rather than produced by overlapping transmissions.

### Required implementation

- Schedule transmission start and end events.
- Track channel, frequency, bandwidth, spreading factor, transmitter, receiver, and received power.
- Detect time overlap between transmissions.
- Model co-channel and cross-spreading-factor interference using an explicitly documented approximation.
- Add hidden-node cases.
- Add near-far capture using received-power differences.
- Add channel sensing, backoff, retransmission, acknowledgement timeout, and retry limits where required by SEIAN-AMRP.
- Enforce duty-cycle availability before scheduling transmission.

### Required tests

- Non-overlapping packets both succeed.
- Equal-power overlapping packets collide under the selected model.
- A sufficiently stronger packet survives when capture applies.
- Hidden nodes collide at a shared receiver.
- Backoff reschedules a busy transmission.
- Retry limits stop indefinite retransmission.

## 8. Priority 4: Shared Python and ESP32 Packet Specification

### Current problem

The simulator uses Python dictionaries and JSON length as a convenient abstract packet representation. The embedded implementation requires a compact binary packet with exact field sizes.

### Required design decisions

- Numeric node-address size.
- Network identifier representation.
- Packet version and type widths.
- Source, origin, next-hop, and final-destination fields.
- Sequence-number and replay-window widths.
- Priority, flags, hop count, and TTL widths.
- Payload type and payload length.
- Integer scaling for voltage, frequency, phase, load, temperature, and power.
- Endianness.
- Maximum packet size.
- CRC responsibility versus message authentication responsibility.
- Key identifier, nonce, and MIC fields.

### Required implementation

- Python encoder and decoder.
- Matching C++ encoder and decoder.
- Shared packet-format document.
- Cross-language test vectors represented as hexadecimal byte sequences.
- Rejection tests for truncated, oversized, malformed, and unsupported-version packets.

## 9. Priority 5: Security Behaviour

### Current problem

CRC and authentication are represented by validity flags rather than real calculations. CRC detects corruption but does not prove packet origin.

### Required implementation

- Real message authentication code for protected packet types.
- Key identifier and key-rotation strategy suitable for the prototype.
- Replay window rather than only a simple duplicate cache.
- Authenticated sequence number and critical header fields.
- Clear policy for unsigned discovery traffic, if any.
- Persistent or safely restored sequence state on embedded restart.

Security work should remain prototype-scoped and must not claim utility-grade certification.

## 10. Priority 6: Grid-State Model and Electrical Scope

### Current problem

Electrical values are synthetic and faults are applied mainly by geometric distance. A bounded health/load/fault signal now influences routing, but the signal derivation is still simplified and electrical propagation does not generally follow radio-space distance.

### Required improvements

- Clearly label current values as injected or synthetic communication inputs.
- Separate communication topology from electrical topology.
- Represent feeder, bus, or microgrid relationships independently of node coordinates.
- Define how voltage, frequency, phase, load, temperature, and protection state produce a normalized health score.
- Define hysteresis so small fluctuations do not cause route oscillation.
- Add recovery behaviour after a temporary grid event ends.
- Optionally import time-series output from a separate power-flow or transient-study tool later.

Primary inverter protection must always remain local and override received coordination recommendations.

## 11. Priority 7: Route-Cost Calibration

### Current problem

The route-cost weights are tunable but not yet calibrated or supported by sensitivity analysis.

### Required work

- Normalize every cost component to a documented range.
- Define healthy, warning, overloaded, and faulted thresholds.
- Add route hysteresis and minimum improvement before switching paths.
- Compare several candidate weight sets.
- Run sensitivity analysis to show which factors dominate decisions.
- Check that gateway preference does not unintentionally reward every edge in a gateway-facing route.
- Report route stability as well as delivery performance.

## 12. Priority 8: Experimental Framework

### Baselines

Every experiment should compare at least:

1. Gateway-centric/direct LoRa where connectivity permits.
2. Hop-count-only mesh routing.
3. Hop-count plus link-quality routing.
4. Proposed grid-aware routing.

### Topologies

- Line.
- Star.
- Grid.
- Diamond with redundant paths.
- Sparse random.
- Dense random.
- Clustered hotel/cabana layout.
- Several gateway placements.

### Scales

- 4-6 nodes for direct hardware comparison.
- 20 nodes for the proposed hotel scenario.
- 50 and 100 nodes for scaling analysis.

### Scenarios

- Normal telemetry.
- Relay failure.
- Gateway loss.
- Background congestion plus emergency traffic.
- Electrically unhealthy shortest-path relay.
- Multiple simultaneous faults.
- Hidden-node collision.
- Intermittent node availability.
- Nearby unrelated Network ID.
- Firmware-version or key-ID mismatch.

### Statistical method

- Use multiple documented random seeds.
- Repeat each stochastic configuration enough times to report a stable mean and spread.
- Report confidence intervals or another justified uncertainty measure.
- Keep scenario inputs and result exports reproducible.
- Define success thresholds before final evaluation rather than selecting them after viewing results.

## 13. Priority 9: Hardware Validation

### Small testbed first

- Begin with three nodes in a line.
- Extend to a four-node diamond with a backup route.
- Compare packet bytes, hop decisions, RSSI, SNR, delivery, and timing against simulator traces.
- Measure real path loss at representative indoor and outdoor distances.
- Calibrate shadow fading, sensitivity, and packet-loss assumptions.

### Acceptance before scaling

- Python and C++ decode identical packets.
- Simulator and firmware choose the same next hop for controlled inputs.
- Measured and simulated airtime match within a justified tolerance.
- Small-topology route failure and recovery follow the same event sequence.

Only after this alignment should the project claim that larger simulator experiments represent likely hardware behaviour.

## 14. Dashboard and Reporting Improvements

- Show application-level PDR and link-level delivery ratio with human-readable labels.
- Add node, packet type, priority, and time-range filters to metrics and event views.
- Display route convergence timelines.
- Export experiment configuration with every result.
- Add comparison charts for baselines and repeated seeds.
- Distinguish discovery/control drops from application-data drops.
- Replace deprecated Streamlit `use_container_width` calls with the supported width API.
- Add an explicit simulator-version field to exports.

## 15. Proposal Updates Required

- Separate topology feasibility, protocol simulation, electrical-state injection, and hardware validation into distinct stages.
- State that current grid values are simplified inputs and not power-flow or protection results.
- State that current LoRa timing remains approximate until exact airtime and collision work is complete.
- Add a traceability table containing research question, scenario, baseline, metric, and success threshold.
- Define how route weights will be normalized and calibrated.
- Define how simulator results will be compared with hardware measurements.
- Avoid claiming decentralized route convergence until packet-driven route learning is implemented.

## 16. Recommended Branch Sequence

1. `feature/timing-metrics-foundation` - finish, review, commit, push, and merge.
2. `feature/decentralized-route-learning` - advertisements, expiry, route errors, loop prevention, and convergence metrics.
3. `feature/lora-airtime-model` - exact time-on-air and encoded payload length.
4. `feature/event-radio-channel` - overlapping transmissions, collisions, capture, backoff, and retries.
5. `feature/binary-packet-format` - shared Python/C++ encoding and test vectors.
6. `feature/prototype-security` - MIC and replay-window behaviour.
7. `feature/experiment-runner` - baselines, repeated seeds, confidence reporting, and exports.
8. `feature/hardware-calibration` - measurement import and calibrated channel parameters.

Each branch should have focused tests and documentation and should be merged before beginning the next major dependency.

## 17. Immediate Next Action

Do not start decentralized routing until the current timing/metrics branch is finalized.

The immediate sequence is:

```text
review cross-plane diff
-> run 47 tests
-> verify healthy-alternate, only-path, recovery, and NO_ROUTE traces
-> commit
-> push
-> pull-request review
-> begin decentralized route-learning design
```

The first design task after this merge is to specify the exact `ROUTE_ADVERTISEMENT` payload, including the bounded electrical route-suitability fields, and per-node route-update rules on paper before implementing them.
