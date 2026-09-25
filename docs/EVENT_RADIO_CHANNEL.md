# Event-based shared radio channel

Select **LoRa airtime settings → LoRa time-on-air**, preferably **Binary v1**, then
**Shared radio channel → Event-based shared channel** and create/reset the network.
Use **Run Batch** or **Advance One Step**. Serialized mode remains available for
the manual one-link tracer; manual tracing explicitly rejects event-mode networks.

In Python, set `config.lora.airtime_mode = "lora"` and
`config.radio.mode = "event"` before constructing the simulator. Submit traffic
with `route_packet()`/`broadcast()` and call `process_queues()` to run pending
radio and receiver events. In this mode a true send result means **queued**, not
delivered. Check delivery metrics or completion records for the outcome.

## Shared clock and physical attempts

All transmitters share a start/end/completion event heap. Packet duration comes
from the exact LoRa formula and the actual encoded frame size. Receiver processing
delay is separate and occurs after airtime ends. Consecutive sends submitted at
the same simulated time can overlap; the clock does not advance for each call.
A broadcast has one start/end pair and one physical transmission attempt, with
independent reception results for its intended neighbors. A failed attempt still
occupies the channel for its airtime.

Events ending at a timestamp are completed before new transmissions start at that
timestamp, so touching intervals do not collide. Simultaneous contenders sense
the same pre-existing channel state. The first submitted packet does not gain an
artificial advantage. The simulator adds seeded initial random backoff (0..16
slots by default); set `initial_backoff_slots=0` for synchronized stress tests.

One transmitter sends at a time. Among ready requests from the same node at an
instant, larger packet priority is selected first. Frames already on air are not
preempted. Transmitting nodes cannot receive overlapping packets (half duplex).
Topology/radio observations are sampled per attempt; continuous motion during a
frame and propagation delay are not modeled. Node availability is checked at
start/end and completion. Discovery still probes physical links directly rather
than transmitting actual HELLO frames through the event scheduler.

## Collision and capture assumptions

Frequency bands overlap when their center separation is less than half their
combined bandwidths. By default, only matching spreading factors interfere;
`cross_sf_interference=True` is a conservative alternative in which every
overlapping band interferes irrespective of SF. Neither option is a calibrated
inter-SF rejection matrix or a detailed receiver/demodulator model. Mixed-profile
tests assume compatible ideal receive paths; the dashboard uses one common profile.

At every change in the set of active transmitters, the desired signal at each
receiver is compared with the **sum of interfering powers in linear units**.
Capture succeeds only when the desired-to-interference ratio meets
`capture_threshold_db` (default 6 dB). The use of a 6 dB threshold is consistent
with the heuristic in [the authors' LoRaSim implementation](https://github.com/mcbor/lorasim/blob/main/loraDir.py).
This implementation is independently written and uses its own conservative
whole-frame overlap rule; it does not reproduce LoRaSim's preamble timing model.
Once a frame is damaged it cannot become successful when an interferer ends.

Interference is evaluated at each receiving node, including emissions addressed
to somebody else. Carrier sensing is evaluated at the transmitter, allowing
hidden-node collisions. Path loss and seeded shadowing remain approximate.
Configured probabilistic `collision_probability` and `channel_busy_probability`
are ignored in event mode, including discovery probes. Packet-loss probability
and external-interference probability remain explicit independent background-loss
assumptions. They do not substitute for overlap detection.

## Backoff, retries, and duty cycle

Carrier sensing checks band-overlapping active emissions against the transmitter's
`carrier_sense_threshold_dbm` (default -110 dBm). A busy result reschedules using
seeded exponential random slots, with a 20 ms slot and at most eight backoffs by
default. Backoff exhaustion records a drop without counting a radio attempt.

Failed unicast radio attempts can retry, default twice beyond the original
attempt. Each retry has a distinct physical attempt, airtime, and reception row;
application origin/sequence and creation time are preserved. Broadcasts do not
retry automatically. **Feedback is ideal:** the scheduler uses the reception
outcome after completion plus `retry_delay_s` (default 50 ms), then random backoff.
No on-air ACK, ACK loss, ACK timeout protocol, or ACK airtime is implemented.
Queue rejection and authentication rejection after a successful radio reception
do not trigger these radio-loss retries.

An optional duty fraction enforces next-start time >= previous-start + airtime /
duty fraction for each transmitter, conservatively across all frequencies. The
default is 1.0 (100%, unrestricted experiment). This is not regional regulatory
compliance; band-specific rules, dwell time, and frequency hopping remain future work.

`process_queues()` drains pending work, including retries and forwarded packets.
As in the existing batch driver, the requested batch duration is a traffic-step
horizon, not a hard cutoff: draining the last step can finish after that time.
A 100,000-event limit stops pathological runs with an explicit error and retains
pending work. There is no silently dropped pending tail.

## Metrics and exports

Protocol Metrics shows shared-radio counters and the latest timeline rows. Export
Results offers the complete **Radio timeline CSV** and **Radio metrics JSON**.
`export_tables_json()` includes `radio_events`, `radio_metrics`, and configuration;
topology JSON round-trips the `radio_config` settings.

- `transmission_attempts` counts physical emissions, including retries and one per broadcast.
- `successful_link_transmissions` counts emissions with at least one successful radio reception,
  before protocol/queue validation, so the existing link delivery ratio stays <= 1.
- `receptions` in radio metrics counts successful receiver-frame pairs; it may exceed emissions.
- `collision`, `half_duplex`, and other drop counters are per receiver-attempt.
- `physical_transmissions`, summed `airtime_s`, `retries`, `retry_exhausted`,
  `carrier_sense_busy`, `backoff_exhausted`, and `transmitter_deferrals` describe channel activity.
- `capture_checks_passed` counts successful interference comparisons, not unique captured packets.
- Application PDR remains unique destination deliveries / unique generated unicasts.

Radio timeline records carry transmission IDs, attempts, timestamps, transmitter,
frequency, bandwidth, SF, frame bytes, receiver outcomes, power, and retry/backoff
decisions. Summed transmitter airtime can exceed elapsed time under concurrency;
it is not a channel-utilization percentage.

## Validation and remaining scope

Tests cover overlap/non-overlap boundaries, aggregate interference, near-far capture,
hidden nodes, half duplex, SF/frequency separation, deterministic simultaneous CCA,
backoff limits, retry limits, source serialization, priority, duty-cycle spacing,
node disappearance, physical broadcast counts, exact multi-hop latency, binary
decentralized routing, export/import, seeded reproducibility, and dashboard controls.
The full mesh, power-plane, and compiled C++ interoperability suites also run.

Remaining work includes real ACK traffic, realistic demodulator capacity and
preamble locking, measured cross-SF rejection, band-specific channel access rules,
hardware calibration, authentication, and large repeated experiments. This is a
documented discrete-event approximation, not a validated LoRa PHY implementation.
