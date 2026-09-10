# SEIAN-AMRP Route-Control Specification

Status: implemented simulator contract for `feature/decentralized-route-learning`

## 1. Scope

This document defines the packet payloads and node-local update rules required to replace immediate NetworkX route installation with decentralized SEIAN-AMRP learning. NetworkX remains available only as a topology oracle and experimental baseline.

This stage uses validated Python dictionaries. Exact binary widths, integer scaling, endianness, and MIC fields belong to the later shared Python/C++ packet-format update.

## 2. Node-Local State

Each node owns:

- its direct-neighbor observations;
- its routing table;
- a monotonically increasing sequence number for its own destination;
- the newest destination sequence seen for every remote destination;
- route expiry times;
- triggered-update state; and
- recently invalidated destinations.

No protocol node may inspect the complete topology graph when learning or repairing a route.

## 3. ROUTE_ADVERTISEMENT Payload

One packet advertises one destination route:

| Field | Meaning | Validation |
|---|---|---|
| `destination_id` | Reachable final destination | Non-empty node identifier |
| `destination_sequence` | Freshness version owned by the destination | Integer `>= 0` |
| `hop_count` | Advertiser's distance to the destination | Integer `0..max_hops` |
| `route_cost` | Advertiser's cumulative cost | Finite number `>= 0` |
| `lifetime_s` | Requested validity after reception | Finite number `> 0` |
| `advertised_next_hop` | Advertiser's selected next hop, or `null` for itself | Node identifier or `null` |
| `gateway_path` | Whether the destination/path provides online gateway reachability | Boolean |
| `electrical_risk` | Advertiser's bounded EP route-suitability signal | Number `0..1` |
| `communication_health` | Advertiser's bounded CCP health | Number `0..1` |
| `communication_congestion` | Advertiser's bounded queue/channel congestion | Number `0..1` |
| `communication_fault_status` | Advertiser's CCP fault state | `normal`, `warning`, or `fault` |

The packet header supplies the advertiser/source ID, origin ID, packet sequence, Network ID, priority, TTL, and authentication fields. Route advertisements are one-hop broadcasts. Receivers create their own new advertisements after accepting a change; they do not forward the same packet unchanged.

## 4. Candidate Calculation

After receiving an advertisement from direct neighbor `A`, node `B` calculates:

```text
candidate_hops = advertised_hops + 1
candidate_cost = local_link_and_neighbor_cost(B, A) + advertised_route_cost
candidate_expiry = receive_time + min(advertised_lifetime, configured_route_lifetime)
```

The local edge cost includes link quality, `A`'s communication state, and `A`'s bounded electrical route penalty. The electrical signal influences preference but never decides whether `A`'s radio is available.

## 5. Validation and Loop Prevention

A receiver rejects an advertisement when:

- normal Network-ID, trust, CRC, authentication, or payload validation fails;
- the sender is not a current direct neighbor;
- the destination is the receiver itself;
- the advertised next hop is the receiver, implementing split horizon;
- adding one hop exceeds `max_hops`;
- any numeric field is non-finite or outside its defined range; or
- the destination sequence is older than the newest accepted sequence.

Poison reverse will advertise an unreachable cost back toward the selected next hop when route invalidation is implemented. Packet path checks remain a final forwarding guard, not the primary route-learning loop-prevention method.

## 6. Route Selection

For a destination, a candidate is accepted in this order:

1. A newer destination sequence always replaces an older sequence.
2. An older destination sequence is rejected.
3. For equal sequences, an expired or invalid current route is replaced.
4. An update from the current next hop refreshes lifetime and current metrics.
5. A different next hop must improve cost by at least the configured hysteresis margin.
6. Equal-cost candidates prefer fewer hops, then the lexicographically smaller next-hop ID for deterministic tests.

The routing table records destination, next hop, hop count, cumulative cost, destination sequence, expiry, learned-from neighbor, backup next hop, and last update time.

## 7. Advertisement Scheduling

- Every node advertises itself after discovery with hop count `0` and cost `0`.
- Periodic full-table advertisements refresh valid routes.
- Triggered advertisements are scheduled after route creation, material cost change, next-hop change, gateway-state change, or invalidation.
- Triggered updates are rate-limited and coalesced to reduce LoRa airtime.
- Electrical changes must exceed the route hysteresis threshold before triggering a route switch or advertisement.

## 8. ROUTE_ERROR Payload

| Field | Meaning |
|---|---|
| `destination_id` | Destination no longer reachable through the sender |
| `destination_sequence` | New invalidation version |
| `failed_next_hop` | Neighbor whose loss invalidated the route |
| `reason` | Machine-readable reason such as `neighbor_timeout` |

A node accepts a route error only from the next hop currently used for that destination, or when it identifies the same failed next hop locally. It invalidates affected routes, attempts a valid backup, and emits a triggered route error/update to dependent neighbors.

## 9. Required Metrics

- route-advertisement packets and bytes;
- route-error packets and bytes;
- accepted and rejected advertisements by reason;
- route changes per node;
- convergence time after a failure or electrical-risk change;
- transient data-packet loss during convergence;
- loop detections; and
- route-control overhead as a fraction of total traffic.

## 10. Implementation Status

Implemented: validated route-control payloads, destination sequences, learned-from state, packet-reception processing, periodic and triggered advertisements, split horizon, route expiry, route errors, backup activation, convergence metrics, control-overhead metrics, and an explicit NetworkX oracle mode.

Not yet implemented: poison reverse as an alternative to split horizon, a shared binary Python/C++ packet format, and embedded-firmware route-advertisement handling.
