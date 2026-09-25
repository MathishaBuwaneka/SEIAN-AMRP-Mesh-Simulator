# Integrated features and test guide

Updated 2026-09-25. All six development branches below are integrated into `main`.
The integration baseline passes **314 tests, with no skips**, including the
compiled host C++ codec checks. These tests validate implemented behavior, not
agreement with physical LoRa hardware or a live PSCAD installation.

## What each branch added

| Branch | Features | What this means when using the simulator |
| --- | --- | --- |
| `feature/timing-metrics-foundation` | Preserved packet creation time across relays; accumulated link delays; separated unique application deliveries from radio attempts and relay receptions; restored bounded electrical route penalties. | A two-hop packet has one application delivery and two radio attempts. An electrically unhealthy relay can become less preferred while its radio keeps working. |
| `feature/decentralized-route-learning` | Packet-driven route advertisements, destination sequence freshness, split horizon, hysteresis, route ageing, backup routes, route errors, convergence and control-traffic metrics. | Nodes learn paths from received advertisements and react to relay failure. NetworkX remains an explicitly selectable comparison baseline. |
| `PSCAD_integration` | Separate power-plane research pipeline and dashboard, timed switching/fault scenarios, controller adapters, PSCAD trace processing and graphical editors; integrated offline regression coverage. | Explore electrical switching and measured PSCAD outputs in the research dashboard. The mesh dashboard's electrical values remain synthetic inputs; merging did not turn them into a power-flow solver. |
| `feature/lora-airtime-model` | Selectable LoRa frame time-on-air using SF, bandwidth, coding rate, preamble, header, CRC and LDRO; byte-length validation, frame-size limits and sensitivity estimate. | Radio timing changes with the configured profile and encoded packet size. Approximate timing remains available. |
| `feature/binary-packet-format` | Compact binary v1 contract, numeric addresses, separate origin/next-hop/destination fields, typed payloads, real CRC-16, matching Python/C++ codecs and common byte vectors. | Exact timing can use actual compact encoded frames, including route-control packets. The portable codec has been compiled for ESP32; a complete firmware application is still separate work. CRC detects corruption; it is not authentication. |
| `feature/event-radio-channel` | Concurrent start/end events, receiver-specific collisions and capture, hidden nodes, half duplex, carrier sensing, bounded backoff/retries, per-transmitter duty spacing, single-emission broadcasts, radio timeline and exports. | Batch traffic shares a channel and can interfere. Retries use ideal reception feedback, not transmitted ACK frames. Manual single-link tracing uses serialized mode. |

Branches are development history, not six separate applications. Select the
routing, timing, encoding and radio modes in the integrated dashboard.

## Run the complete automated test suite

Open PowerShell in `SEIAN-AMRP-Mesh-Simulator`:

```powershell
.\.venv\Scripts\python.exe scripts/build_wire_codec.py
.\.venv\Scripts\python.exe -m pytest -q -rs -p no:cacheprovider
```

The build needs `g++`, `clang++`, or the optional `ziglang==0.14.1` package in
the environment. The existing project environment is configured. On a new
machine, follow the repository setup instructions first. If the C++ executable
is missing, interoperability tests can skip: inspect the summary rather than
treating skipped tests as successful validation. The expected current result is
314 passed and no skips. Default discovery includes `tests/` and
`research_power_plane/tests/`.

For a readable list of individual cases and results, replace `-q` with `-v`.
For a report file, add `--junitxml=test-results.xml` (a local generated artifact).

## Focused test cases and expected results

For any row, run the listed files with the same pytest command. Example:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_event_radio.py tests/test_event_radio_integration.py -v -p no:cacheprovider
```

| Case | Setup/action exercised by the automated tests | Expected result | Test files under `tests/` |
| --- | --- | --- | --- |
| T01 Timing and counting | Forward one unicast across two links; also force a failed link and queue overflow. | Original creation time survives; latency accumulates; unique delivery is not counted twice; failed physical attempts and drop rows are counted correctly. | `test_timing_metrics.py` |
| T02 Manual tracing | Create a three-node chain and press the equivalent of Forward twice. Remove its relay in another run. | Exactly one link per action; source/hop/TTL evolve; final delivery after the second link; disconnected route stops without a radio attempt. | `test_manual_simulation.py` |
| T03 Distributed learning | Allow advertisements along a line/diamond; introduce stale updates and expired entries. | Multi-hop routes form without oracle installation; invalid/stale information is rejected; old routes expire. | `test_decentralized_routing.py`, `test_decentralized_simulator.py`, `test_route_messages.py` |
| T04 Recovery and partition | Fail a diamond relay; cut the only bridge in a line. | Learned backup activates when available; cross-partition routes disappear while local routes remain. | `test_decentralized_simulator.py` |
| T05 Electrical/radio separation | Fault the power stage; degrade or fail the communication plane separately; set electrical route weight to zero. | Power faults penalize routes without disabling healthy radios; communication failure removes relay availability; zero weight supplies a communication-only baseline. | `test_plane_separation.py`, `test_routing.py` |
| T06 Gateway, flooding, priority | Lose a gateway, flood a fault, send duplicates and queue mixed priorities. | Local communication behavior, controlled flood propagation, duplicate suppression and priority order satisfy the defined contracts. | `test_gateway_failure.py`, `test_fault_alerts.py`, `test_duplicate_suppression.py`, `test_queue_priority.py` |
| T07 Topology editing | Add/move/remove nodes and inspect graph connectivity. | Builder updates nodes/links; isolated nodes, critical relays and route checks match topology. | `test_network_builder.py`, `test_topology_analysis.py`, `test_discovery.py` |
| T08 Exact airtime | Vary SF, bandwidth and payload; compare reference vectors; reject invalid settings. | Formula matches vectors; timing follows frame/profile; illegal frames/settings are rejected. | `test_lora_airtime.py` |
| T09 Binary interoperability | Encode/decode common vectors in Python and compiled C++; corrupt/truncate frames. | Both codecs agree on bytes and fields; invalid frames fail validation. | `test_wire_codec.py` |
| T10 Binary transport | Use binary exact-airtime multihop routing, oversize payloads and topology round trips. | Routing and address identity survive; oversize frames consume no radio attempt; failed valid frames consume airtime. | `test_binary_transport.py` |
| T11 Collision boundaries | Schedule equal-power overlapping frames; then frames that only touch end/start boundaries. | Overlap collides; touching/non-overlapping frames succeed. | `test_event_radio.py` |
| T12 Capture and hidden nodes | Place one sender much nearer; combine interfering powers; hide two senders from each other. | Strong signal survives when threshold is met; aggregate interference can defeat capture; hidden senders can collide at their receiver. | `test_event_radio.py` |
| T13 Frequency/SF and half duplex | Separate frequency/SF, toggle cross-SF interference, transmit while receiving. | Separation follows the selected interference model; a transmitting receiver cannot receive the overlapping frame. | `test_event_radio.py` |
| T14 Backoff and retry bounds | Start traffic during a visible busy frame; force every attempt to fail; exhaust backoff. | Busy traffic reschedules; two permitted retries mean at most three emitted attempts; backoff exhaustion emits no frame for that request. | `test_event_radio.py` |
| T15 Priority, duty and broadcast | Queue same-transmitter traffic at one instant; apply duty fraction; broadcast to multiple receivers. | Ready higher priority goes first; one transmitter serializes and obeys spacing; broadcast is one emission with multiple possible receptions. | `test_event_radio.py`, `test_event_radio_integration.py` |
| T16 Shared engine and exports | Run exact binary decentralized traffic twice with the same seed; reset/delete nodes with pending work; export/import. | Results reproduce; clock and application counters stay consistent; removed/reset nodes are handled; settings and radio records export correctly. | `test_event_radio_integration.py` |
| T17 Dashboard settings | Apply exact/binary/event settings on reset; advance one step; disable required LDRO. | Dashboard runs without exceptions, emits timeline records and exports metrics; invalid LDRO reports an error. | `test_airtime_dashboard.py` |
| T18 Existing security behavior | Exercise validity flags and current packet acceptance rules. | Existing behavioral checks pass; this is not proof of cryptographic authentication or a replay window. | `test_security.py` |
| T19 Research power plane | Run the offline controller, switching timeline, faults, trace readers and dashboard tests. | Offline pipeline, validation and rendering contracts pass without claiming a fresh live PSCAD run. | Use `research_power_plane/tests` instead of `tests/`. |

The automated cases deliberately control seeds, positions and background losses.
Use them for exact collision, capture and counter assertions. Random dashboard
traffic is a smoke test and need not produce the same PDR or collision count.

## Manual dashboard acceptance checklist

Start the mesh dashboard:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Record the commit (`git rev-parse HEAD`), scenario, seed, radio settings, routing
mode and encoding for each run. Apply settings with **Create / Reset Network**;
start fresh between comparisons so old traffic does not affect the metrics.

| Check | Steps | Expected visible result |
| --- | --- | --- |
| M01 Basic batch | Choose a built-in connected scenario, **NetworkX oracle baseline**, approximate timing and **Serialized (manual tracing)**. Reset, then **Advance One Step** and **Run Batch**. | Network renders; events/metrics populate; no application exception. Random radio loss can prevent some deliveries. |
| M02 Manual packet | Keep serialized mode. In **Packet Simulation**, choose connected source/destination nodes and create a unicast; use **Forward** until complete. | Each action advances one link; last-transmitted header/path/TTL and delivery/drop status update. For a guaranteed two-hop case, use automated T02. |
| M03 Decentralized routes | Select **Decentralized advertisements**, reset and run a batch. Inspect **Node Details**, routes, and **Protocol Metrics**. | Learned routes and route-control counters appear after successful advertisements. Loss/congestion may delay convergence. T03/T04 provide controlled recovery assertions. |
| M04 Exact binary timing | Select **Binary v1**, **LoRa time-on-air**, SF7, bandwidth 125 kHz and automatic LDRO. Reset/run. Repeat with SF12. | Both configurations apply and run. Equivalent frames occupy more airtime at SF12; whole-run latency/PDR can also change with routing and traffic. T08 isolates the formula comparison. |
| M05 Event radio | Keep binary/exact timing; select **Event-based shared channel**, reset, and **Advance One Step** or **Run Batch**. | **Protocol Metrics** shows shared-radio counters and a timeline with physical emissions and receiver outcomes. Collisions are possible, not mandatory on every run. |
| M06 Export results | After M05, open **Export Results**. Download **Radio timeline CSV**, **Radio metrics JSON**, tables and topology. | Files open; timeline is populated; radio counters correspond to that run. Topology export includes `radio_config`. |
| M07 Validation | Select SF12/125 kHz and disable low-data-rate optimization. Restore Automatic afterwards. Try manual packet tracing on an event-mode network. | Required-LDRO error is shown; manual tracer explicitly rejects event mode. Restore serialized mode and reset for manual tracing. |
| M08 Builder | Select **Create own network**, reset, place/move/delete nodes, rebuild links/routes and open **Topology Check**. | Node locations and links update; disconnections/isolated nodes are visible when created. |
| M09 Research dashboard | Follow `research_power_plane/README.md` for its separate dashboard. For an offline check, keep automatic PSCAD execution disabled and inspect existing traces/editors. | Offline data/views render. A live PSCAD run is a separate check requiring its dependencies and licence. |

For an experiment record, save: case ID, settings/seed, expected outcome, observed
outcome, pass/fail, exported results and any screenshot needed for the report.
Do not set a universal 100% PDR requirement for lossy or concurrent scenarios.

## What remains outside this acceptance pass

Real on-air ACK/timeout behavior, message authentication/replay windows, calibrated
LoRa receiver behavior, regional channel rules, and hardware alignment are not
implemented or established by this suite. Repeated-seed baseline comparisons,
uncertainty reporting and route-weight sensitivity studies remain research work.
The implemented simulation is ready for controlled experiments with those limits
stated; passing tests alone does not finish the experimental evaluation.
