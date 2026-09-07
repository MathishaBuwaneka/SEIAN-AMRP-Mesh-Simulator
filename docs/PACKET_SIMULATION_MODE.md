# Packet Simulation Mode

The **Packet Simulation** tab provides a Packet Tracer-style manual mode. It is deliberately separate from the batch engine.

## Workflow

1. Build or load a topology and rebuild neighbor/routing tables.
2. Open **Packet Simulation**.
3. Select source, destination or broadcast, packet type, priority, TTL, and payload.
4. Press **Create Packet**.
5. Press **Forward** once for each physical link transmission.
6. Inspect the current hop, waiting queue, packet header, and event history.

## One Forward press

One press attempts exactly one queued physical transmission from one sender to one receiver. It evaluates:

- sender and receiver state;
- current one-hop neighbor relationship;
- LoRa range, RSSI, SNR, channel busy, collisions, packet loss, and interference;
- Network ID, CRC, authentication, payload format, and duplicate status;
- destination delivery, TTL, routing-table next hop, or controlled flooding.

No second hop is executed until **Forward** is pressed again.

Each attempted radio transmission advances simulated time by the link delay returned by the LoRa channel model. The packet keeps its original creation timestamp across every relay, so a final destination delivery reports accumulated end-to-end latency rather than only the most recent hop delay.

The packet panel separates four views:

- **Original logical packet**: the protocol header created at the origin.
- **Last transmitted header**: the protocol header used for the most recent physical hop, including its current source, hop count, and TTL.
- **Simulator timing metadata**: creation, most recent forwarding, and current simulation times; these are not presented as protocol-header fields.
- **Payload**: the application data carried by the packet.

The displayed structures are simulator/debug representations. They are not yet the final byte-for-byte ESP32 LoRa packet format.

## Packet behavior

- Unicast packets follow the current SEIAN-AMRP routing table one hop at a time.
- Ordinary broadcasts reach direct neighbors only.
- `FAULT_ALERT`, `CONTROL_COORDINATION`, `GATEWAY_ANNOUNCE`, `ROUTE_ADVERTISEMENT`, and `ROUTE_ERROR` may use controlled flooding while TTL remains.
- `FAULT_ALERT` can generate separate `FAULT_ACK` packets, which also appear in the waiting event queue.

## Metric meanings

- `unicast_packets_generated`: unique packets created with a final destination.
- `unicast_packets_delivered`: unique packets that reached that final destination.
- `packet_delivery_ratio`: final unicast deliveries divided by generated unicast packets.
- `transmission_attempts`: physical one-link radio attempts, including failed attempts.
- `successful_link_transmissions`: attempts that reached the receiving radio.
- `link_delivery_ratio`: successful link transmissions divided by transmission attempts.
- `packets_delivered`: accepted link-level receptions, including intermediate relays.
- `average_latency_s`: end-to-end latency averaged over final unicast deliveries.

These definitions intentionally separate application-level delivery from link-level radio performance.

## Files

- `seian_sim/manual_simulation.py`: manual event queue and protocol decisions.
- `seian_sim/visualization.py`: packet-trace topology view.
- `app.py`: Packet Simulation tab and Forward button.
- `tests/test_manual_simulation.py`: deterministic step-by-step tests.
