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

## Packet behavior

- Unicast packets follow the current SEIAN-AMRP routing table one hop at a time.
- Ordinary broadcasts reach direct neighbors only.
- `FAULT_ALERT`, `CONTROL_COORDINATION`, `GATEWAY_ANNOUNCE`, `ROUTE_ADVERTISEMENT`, and `ROUTE_ERROR` may use controlled flooding while TTL remains.
- `FAULT_ALERT` can generate separate `FAULT_ACK` packets, which also appear in the waiting event queue.

## Files

- `seian_sim/manual_simulation.py`: manual event queue and protocol decisions.
- `seian_sim/visualization.py`: packet-trace topology view.
- `app.py`: Packet Simulation tab and Forward button.
- `tests/test_manual_simulation.py`: deterministic step-by-step tests.
