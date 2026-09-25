# SEIAN Simulator Status and Remaining Work Report

Date: 2026-09-25
Work branch: `feature/event-radio-channel` (based on integrated `main`)

## Event-radio update

The airtime and binary-packet branches were reviewed together (282 passing tests)
and integrated into `main` at `731dacc`. No open PRs were present; GitHub's
connector rejected PR creation with 403, so the explicitly requested integration
used Git fast-forward merges and a push.

The separate event-radio branch implements shared start/end events, physical
broadcast accounting, receiver-specific overlap/capture, half duplex, hidden
nodes, carrier sensing, bounded retries/backoff, duty-cycle spacing, a dashboard
timeline, and CSV/JSON exports. The combined result is 314 passing tests.
See [event-radio model and limits](EVENT_RADIO_CHANNEL.md). On-air ACKs and
hardware-calibrated interference remain outstanding; retries use ideal feedback.

## Binary packet branch update

This branch adds a shared v1 wire contract, Python and portable C++ codecs, real
CRC-16, numeric addresses, separate next-hop/final-destination fields, compact
typed payloads, and cross-language hexadecimal vectors. Binary mode plus exact
airtime now supports decentralized route-learning and recovery tests within the
255-byte frame limit. Topology exports retain provisioned addresses. See
[the binary packet specification](BINARY_PACKET_FORMAT.md).

The airtime and binary-packet features are now merged into `main`.
The codec compiles for ESP32, but the repository has no
firmware application to integrate or flash. Authentication, fragmentation,
event-based collision scheduling, and hardware validation remain outstanding.

## Airtime branch update

This branch adds selectable SX1276 frame airtime with reference-vector tests,
validated radio settings, automatic LDRO, UTF-8 byte counting, an explicit
protocol-header budget, frame-size rejection, and an estimated sensitivity model.
Both manual and batch forwarding use it; topology exports preserve radio settings.
Approximate mode remains the default because verbose JSON route advertisements
can exceed a physical frame. See [model assumptions](LORA_AIRTIME_MODEL.md).
The binary branch adds the shared format. Fragmentation, regulatory scheduling,
and event-based collisions remain outstanding. Historical baseline results below predate this work.

## Integration update

The timing/metrics foundation, decentralized route learning (including committed
partition and electrical-risk regression tests), and PSCAD integration are now
combined on `main`. The repository also includes `research_power_plane/` and
`research_paper/`; the mesh dashboard's electrical inputs remain synthetic, while
the separate research dashboard supports PSCAD-derived traces.

The merge preserves PSCAD-side queue-overflow event accounting and the routing
branch's transmission-attempt metrics, plus separate CCP/power-stage controls
and updated button sizing. Offline research dashboard replay loads without the
PSCAD automation package. Default pytest discovery includes both suites.

Live PSCAD execution and hardware calibration are separate validation steps;
automated offline tests do not establish either. The 72-test count below records
the earlier routing-branch baseline, rather than the integrated test total.

## 1. Project Objective

SEIAN is intended to evaluate a resilient LoRa mesh in which inverter health and grid-state information influence communication routing. The simulator should eventually provide defensible answers to these questions:

1. Can packets reach their destination through multiple LoRa relays?
2. Can the mesh continue local communication without an online gateway?
3. How quickly does routing recover after a relay becomes unavailable?
4. Does priority handling improve urgent fault-message delivery?
5. Does grid-aware routing outperform hop-count or link-only routing when a relay becomes electrically unhealthy, overloaded, faulted, congested, or communication-degraded?

The current program is useful for topology design, decentralized-routing demonstrations, and controlled protocol experiments. It must not yet be described as a complete LoRa physical-layer model, embedded-firmware-equivalent routing implementation, electrical power-flow simulator, or protection simulator.

## 2. Current Implemented Capabilities

### Network and topology

- Built-in, random, imported, and manually created topologies.
- Coordinate-based and canvas-based node placement.
- Approximate LoRa-range neighbour discovery.
- Connected-component, isolated-node, articulation-point, bridge-link, and gateway-reachability analysis.
- Route tracing and single-node failure-impact analysis.

### Routing and resilience

- Cross-plane route cost using hop count, link quality, communication health, congestion, communication fault state, bounded electrical health/load/fault penalties, and gateway preference.
- Selectable decentralized packet-advertisement routing and NetworkX oracle baseline modes.
- Destination sequences, split horizon, hysteresis, route ageing, route errors, and triggered updates.
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
- Route-control payload validation tests added: 11.
- Decentralized route-engine and simulator integration tests added: 14.
- Current total: 72 passing tests.
- Streamlit application smoke test: no application exceptions.

## 4. Decentralized Route Learning Implemented

The decentralized-routing branch now includes:

- A documented `ROUTE_ADVERTISEMENT` payload contract.
- A documented `ROUTE_ERROR` payload contract.
- Strict validation for identifiers, sequences, hop counts, costs, lifetimes, booleans, electrical risk, and communication health.
- Round-trip payload tests and malformed-field rejection tests.
- Defined freshness, split-horizon, hysteresis, expiry, triggered-update, and route-error rules.
- Packet-driven multi-hop learning without NetworkX route installation.
- Primary and backup candidate selection with deterministic tie-breaking.
- Periodic and triggered advertisements, route expiry, and propagated route errors.
- Convergence-time and route-control-overhead metrics.

The contract is documented in `docs/ROUTE_ADVERTISEMENT_SPEC.md`. NetworkX is retained as an explicit oracle/baseline mode and is not called to install routes in decentralized mode.

Completed implementation sequence:

```text
extend routing entries with sequence/learned-from state
-> install direct routes after HELLO
-> process received route advertisements
-> add periodic and triggered updates
-> add expiry and route-error propagation
-> measure convergence and control overhead
```

## 5. Priority 1: Decentralized Route Learning

### Current status

The decentralized mode gives each simulated node ownership of its routing state and changes routes only after packet reception, expiry, or local next-hop failure. The NetworkX mode remains valuable as a topology-analysis oracle.

The simulator now measures advertisement propagation and convergence using its deterministic approximate transmission clock. More demanding repeated and partitioned experiments remain to be added.

### Implemented

- NetworkX routing remains available only as an analysis baseline or oracle.
- Every node owns its routing table and learned candidate routes.
- `ROUTE_ADVERTISEMENT` packets carry destination, cost, hop count, sequence, lifetime, and bounded route-state inputs.
- Nodes process advertisements only after packet reception.
- Periodic and triggered advertisements refresh distributed state.
- Route ageing and expiry operate without a global route rebuild.
- Split horizon and destination-sequence freshness provide loop prevention.
- `ROUTE_ERROR` propagates when an active next hop fails.
- A valid learned backup becomes active when available.
- Convergence duration is measured on the deterministic simulation clock.

### Implemented tests

- Three-node line learns a two-hop route through advertisements.
- Diamond topology learns primary and backup routes.
- Stale sequence advertisements are rejected.
- Stale routes expire in focused engine tests.
- Relay failure creates a route error.
- Alternate route becomes active after a relay failure.
- A five-node relay failure removes cross-partition routes while preserving routes inside each component.
- An electrical-risk advertisement switches to the healthier relay without disabling the unhealthy relay's communication plane.

Still required: repeated seeded convergence experiments and transient application-traffic measurements during recovery.

### Implemented metrics

- Route convergence time.
- Advertisement sent, accepted, and rejected counts.
- Route-error sent, accepted, and rejected counts.
- Route changes per node.
- Route-control bytes.
- Advertisement and route-error rejection reasons.

Still required: transient packet loss during convergence, explicit loop-detection totals, and a dashboard control-overhead ratio.

## 6. Priority 2: Exact LoRa Airtime

### Current problem

Approximate mode retains the base-plus-length formula. Selectable `lora` mode
now calculates frame airtime from the SX1276 formula. Encoded application bytes
use compact UTF-8 JSON plus an assumed header budget, not the final firmware format.

### Implemented and remaining

- Implemented: frequency, SF, bandwidth, coding rate, preamble, header, CRC and LDRO settings.
- Implemented: symbol, preamble, payload, and total airtime calculations.
- Implemented: UTF-8 payload byte lengths plus a configurable header budget.
- Implemented: SF/bandwidth sensitivity estimate with an explicit override.
- Implemented: shared binary encoding; fragmentation remains outstanding.
- Remaining: jurisdiction-specific duty-cycle or dwell-time rules after the deployment band is confirmed.

### Required tests

- Airtime matches trusted reference vectors for several LoRa configurations.
- Increasing spreading factor increases airtime.
- Increasing bandwidth reduces airtime.
- Larger payloads increase airtime.
- Low-data-rate optimisation is applied when required.

## 7. Priority 3: Event-Based Shared Radio Channel

### Current problem

Serialized mode remains available. Selectable event mode now schedules concurrent
batch transmissions, uses exact frame airtime, and derives busy/collision outcomes
from active emissions. Receiver processing delay is separate from channel occupancy.

### Implemented and remaining

- Shared start/end/completion events and physical broadcast accounting.
- Frequency/bandwidth/SF overlap, aggregate receiver interference, and configurable capture.
- Hidden nodes, half duplex, carrier sensing, initial jitter, and bounded backoff.
- Bounded unicast retries using ideal reception feedback; no on-air ACK frames yet.
- Configurable per-transmitter duty-cycle spacing, with no regional compliance claim.
- Remaining: real ACK protocol, measured interference/demodulator behavior, and band-specific rules.

### Required tests

- Non-overlapping packets both succeed.
- Equal-power overlapping packets collide under the selected model.
- A sufficiently stronger packet survives when capture applies.
- Hidden nodes collide at a shared receiver.
- Backoff reschedules a busy transmission.
- Retry limits stop indefinite retransmission.

## 8. Priority 4: Shared Python and ESP32 Packet Specification

### Current problem

Binary v1 is implemented as an alternative to JSON with exact header widths,
typed compact payloads, CRC, and matching Python/C++ codecs. See
[the wire specification](BINARY_PACKET_FORMAT.md) for the frozen field IDs,
byte vectors, address provisioning, and firmware integration boundary.

### V1 design decisions documented in the shared specification

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

### Implemented

- Python encoder and decoder integrated into manual and batch forwarding.
- Matching portable C++ encoder and decoder, compiled for host and ESP32.
- Shared packet-format document with byte order, widths, units and limits.
- Cross-language test vectors represented as hexadecimal byte sequences.
- Rejection tests for truncated, oversized, malformed, and unsupported-version packets.
- Persisted numeric address map and separate next-hop receiver field.

Remaining: integrate into an actual ESP32 application and validate on hardware.
V1 uses lossless float64/int64 rather than quantized fixed-point measurements.
MIC/nonce/replay-window work belongs to the security stage.

## 9. Priority 5: Security Behaviour

### Current problem

Binary v1 calculates and checks a real CRC-16. Authentication remains behavioral,
and CRC does not prove packet origin. Existing validity flags still support fault
injection in the simulator; no MIC or replay window is implemented.

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
- Describe decentralized convergence as simulator behavior until it is matched against embedded hardware.

## 16. Recommended Branch Sequence

1. `feature/timing-metrics-foundation` - integrated into `main`.
2. `feature/decentralized-route-learning` - integrated into `main`, including advertisements, expiry, route errors, loop prevention, and convergence metrics.
3. `feature/lora-airtime-model` - integrated into `main`.
4. `feature/event-radio-channel` - overlapping transmissions, collisions, capture, backoff, and retries.
5. `feature/binary-packet-format` - integrated into `main`.
6. `feature/prototype-security` - MIC and replay-window behaviour.
7. `feature/experiment-runner` - baselines, repeated seeds, confidence reporting, and exports.
8. `feature/hardware-calibration` - measurement import and calibrated channel parameters.

Each branch should have focused tests and documentation and should be merged before beginning the next major dependency.

## 17. Immediate Next Action

Review the event-radio branch before merging. The next implementation stage is
prototype message authentication and replay protection, followed by repeatable
experiment automation:

```text
review event-radio assumptions and tests
-> integrate the reviewed event-radio feature
-> prototype authentication and replay protection
-> run repeated-seed comparisons and hardware calibration
```

Decentralized route control and selectable frame airtime are implemented in the
simulator. Compact binary packets are implemented on this branch; firmware
application integration and hardware alignment remain separate tasks.
