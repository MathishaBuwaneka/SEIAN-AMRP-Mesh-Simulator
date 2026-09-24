# SEIAN binary frame v1

This is a prototype shared contract implemented by `seian_sim/wire.py` and
`firmware/codec/seian_wire.hpp`. It is not claimed to match any pre-existing
ESP32 firmware. The repository contains no deployed firmware application;
radio scheduling, provisioning, and device integration remain separate work.

Select **LoRa airtime settings → Packet encoding → Binary v1**, then create/reset
the network. Select **LoRa time-on-air** to combine binary packets with physical
frame timing. Python callers set `SimulationConfig.packet_encoding = "binary"`.
JSON remains available and remains the default for arbitrary demonstration payloads.

## Frame layout

All multibyte values are big-endian. A frame is a 24-byte header, 0..229 payload
bytes, and a 2-byte CRC: **26..255 bytes total**. These are the bytes handed to
the LoRa radio; the radio's PHY header and PHY CRC are separate. In binary mode
the exact airtime calculator uses the full frame length directly, ignoring the
JSON mode's assumed protocol-header budget.

| Offset | Width | Field | Rules |
| --- | --- | --- | --- |
| 0 | 2 | Magic | ASCII `SA`, hex `5341` |
| 2 | 1 | Version | 1 only |
| 3 | 1 | Packet type | Table below |
| 4 | 2 | Network ID | 1..65534 |
| 6 | 2 | Immediate transmitter | 1..65534 |
| 8 | 2 | Original source | 1..65534 |
| 10 | 2 | Next-hop receiver | 1..65534, or 65535 for broadcast |
| 12 | 2 | Final destination | 1..65534, or 65535 for broadcast |
| 14 | 4 | Sequence | Unsigned 32-bit; overflow rejected, never silently wrapped |
| 18 | 1 | Priority | 0..4 |
| 19 | 1 | Hop count | 0..255 |
| 20 | 1 | TTL | 0..255; forwarding rules decide whether to relay |
| 21 | 1 | Flags | Reserved, must be zero |
| 22 | 1 | Key ID | Reserved, must be zero |
| 23 | 1 | Payload length | 0..229, exact length required |
| 24 | variable | Typed payload | Canonical field order |
| final 2 | 2 | CRC | Covers every preceding byte |

Type IDs are frozen: 1 HELLO, 2 HELLO_REPLY, 3 HEARTBEAT, 4 GRID_STATE_UPDATE,
5 ROUTE_ADVERTISEMENT, 6 FAULT_ALERT, 7 FAULT_ACK, 8 CONTROL_COORDINATION,
9 GATEWAY_ANNOUNCE, 10 ROUTE_ERROR. Unknown types or versions are rejected.

The simulator persists `wire_network_id` and `wire_addresses` in topology exports.
Addresses are allocated monotonically from 1 and retained after a node is removed;
re-adding the same node name restores its address. Imports reject duplicate or
out-of-range addresses. Provision the identical address map on every device:
labels are not hashed, and independent local discovery is not a provisioning protocol.

The receiver filter accepts its own next-hop address or broadcast, not any frame
whose final destination happens to be reachable. Forwarders preserve origin and
sequence, update transmitter and next hop, increment hop count, and decrement TTL.
Creation/forwarding timestamps and simulator paths are metadata outside the frame.

## Typed payload

Each entry is `[field ID: u8][value type: u8][byte length: u8][value bytes]`.
Fields must appear in strictly increasing ID order; duplicates and unknown IDs
are errors. Empty payloads are valid. Unknown custom JSON keys and nested objects
or arrays cannot be represented in v1 and are rejected, not silently discarded.

| Value type | Width | Representation |
| --- | --- | --- |
| 0 | 0 | null |
| 1 | 1 | boolean, exactly 0 or 1 |
| 2 | 8 | signed two's-complement int64 |
| 3 | 8 | finite IEEE-754 binary64 |
| 4 | variable | strict UTF-8; empty string allowed |

Measurements use their existing units (voltage V, frequency Hz, phase degrees,
temperature Celsius, load percent, current A, power kW/kvar, power factor unitless,
THD percent). Values are lossless int64 or binary64, **not scaled fixed-point**.
This avoids introducing rounding into routing decisions; a future fixed-point
profile needs its own negotiated schema. Numeric types are preserved exactly.
Route costs/lifetimes/health retain the existing route-message validation rules;
the generic codec validates representation, while packet handlers validate semantics.

| ID | Name | ID | Name |
| --- | --- | --- | --- |
| 1 | destination_id | 18 | temperature |
| 2 | destination_sequence | 19 | fault_status |
| 3 | hop_count | 20 | fault_id |
| 4 | route_cost | 21 | fault_type |
| 5 | lifetime_s | 22 | fault_domain |
| 6 | advertised_next_hop | 23 | severity |
| 7 | gateway_path | 24 | recommended_action |
| 8 | electrical_risk | 25 | recommendation |
| 9 | communication_health | 26 | safety_note |
| 10 | communication_congestion | 27 | acknowledges |
| 11 | communication_fault_status | 28 | timestamp |
| 12 | failed_next_hop | 29 | current |
| 13 | reason | 30 | active_power |
| 14 | voltage | 31 | reactive_power |
| 15 | frequency | 32 | power_factor |
| 16 | phase | 33 | thd |
| 17 | load | | |

The simulator adapter translates node-name values in fields 1, 6, and 12 into
numeric provisioned addresses encoded as int64 (null remains null), and restores
node names after decoding. The frame header itself uses uint16 addresses.

## CRC and security boundary

CRC-16/CCITT-FALSE parameters: polynomial `0x1021`, initial value `0xffff`, no
reflection, no final XOR. Check input ASCII `123456789` gives `0x29b1`. The CRC
trailer is big-endian. This application-level checksum is independent of the
optional PHY CRC and detects corruption, **not spoofing**. There is no MIC,
nonce, encryption, replay window, or key rotation in v1. Nonzero flags/key IDs
are rejected rather than implying authentication support. Existing injected
`crc_valid`/`authentication_valid` simulation flags remain separate from the
actual wire CRC; they do not create authenticated packets.

## Simulator and C++ integration

Both manual and batch forwarding encode then decode the link frame before
delivery. Invalid encoding/oversize records `wire_encode_error` before a radio
attempt or time advance. Failed radio attempts consume full frame airtime.
Batch events export `wire_frame_hex` and `wire_frame_bytes`; manual mode shows
the last transmitted frame. Route-control byte totals remain payload-byte totals
per generated control packet, excluding headers, CRC, and per-neighbor duplication.

The C++ header is portable C++11 with standard-library vectors/strings and
IEEE-754 `double`. `encode(Packet, bytes)` and `decode(data, size, packet,
expected_network, receiver)` return false on invalid input, leaving the output
unchanged. Optional filter arguments of zero disable that filter. Field helper
constructors are `integer_field`, `double_field`, `string_field`, `bool_field`,
and `null_field`. Device integration should use bounded radio buffers, provision
addresses, validate payload semantics, and honor the next-hop filter before
dispatching decoded packets. No device flashing is performed by these tools.

## Reproducible validation

Frozen vectors in `tests/fixtures/wire_v1.json` contain both structured values
and full hexadecimal frames. Telemetry is 57 bytes; the representative route
advertisement is 138 bytes. The host C++ utility independently constructs the
telemetry/scalar vectors and decodes/re-encodes all vectors. Tests also exercise
all packet types, 50 seeded mixed-value frames, CRC mutations, truncated headers
and fields, unsupported versions, malformed UTF-8, nonfinite values, duplicate
fields, the maximum frame boundary, and network/next-hop filters.

```powershell
# Use an installed g++/clang++, or optionally install the host compiler:
.venv/Scripts/python.exe -m pip install ziglang==0.14.1
.venv/Scripts/python.exe scripts/build_wire_codec.py
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

Set `SEIAN_CODEC_CLI` to an alternate compiled host utility. Without the utility,
cross-language tests report skips explicitly; do not call that a full validation.
This branch was tested with a host compiler and compiled to an ESP32 object with
the installed Xtensa toolchain. Compilation is not a hardware radio test.

Binary plus exact timing passes decentralized line learning, two-hop manual and
batch delivery, route-error propagation, partition handling, backup selection,
and electrical-risk rerouting. Fragmentation, real authentication, radio scheduling,
firmware application integration, and hardware measurements remain future work.
