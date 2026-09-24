"""Version 1 binary frames; see docs/BINARY_PACKET_FORMAT.md.

CRC provides corruption detection only. This version carries no authentication.
"""

from dataclasses import dataclass
import math
import struct

from seian_sim.enums import PacketType


MAGIC = b"SA"
VERSION = 1
BROADCAST = 0xFFFF
MAX_FRAME_BYTES = 255
HEADER = struct.Struct(">2sBBHHHHHIBBBBBB")
HEADER_BYTES = HEADER.size
CRC_BYTES = 2
MAX_PAYLOAD_BYTES = MAX_FRAME_BYTES - HEADER_BYTES - CRC_BYTES
PACKET_TYPES = {
    PacketType.HELLO: 1, PacketType.HELLO_REPLY: 2, PacketType.HEARTBEAT: 3,
    PacketType.GRID_STATE_UPDATE: 4, PacketType.ROUTE_ADVERTISEMENT: 5,
    PacketType.FAULT_ALERT: 6, PacketType.FAULT_ACK: 7,
    PacketType.CONTROL_COORDINATION: 8, PacketType.GATEWAY_ANNOUNCE: 9,
    PacketType.ROUTE_ERROR: 10,
}
# Frozen IDs: append new fields only in a new negotiated schema/version.
FIELDS = {
    "destination_id": 1, "destination_sequence": 2, "hop_count": 3,
    "route_cost": 4, "lifetime_s": 5, "advertised_next_hop": 6,
    "gateway_path": 7, "electrical_risk": 8, "communication_health": 9,
    "communication_congestion": 10, "communication_fault_status": 11,
    "failed_next_hop": 12, "reason": 13, "voltage": 14, "frequency": 15,
    "phase": 16, "load": 17, "temperature": 18, "fault_status": 19,
    "fault_id": 20, "fault_type": 21, "fault_domain": 22, "severity": 23,
    "recommended_action": 24, "recommendation": 25, "safety_note": 26,
    "acknowledges": 27, "timestamp": 28, "current": 29, "active_power": 30,
    "reactive_power": 31, "power_factor": 32, "thd": 33,
}
FIELD_NAMES = {value: key for key, value in FIELDS.items()}


class WireError(ValueError):
    """Malformed, unsupported, or oversized frame/payload."""


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: polynomial 0x1021, init 0xffff, no reflection/xor."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xFFFF
    return crc


def encode_binary_payload(payload: dict) -> bytes:
    """Canonical field-ID/type/length/value entries, preserving scalar types."""
    if not isinstance(payload, dict) or any(key not in FIELDS for key in payload):
        raise WireError("Binary payload requires recognized field names.")
    output = bytearray()
    for key in sorted(payload, key=FIELDS.__getitem__):
        value = payload[key]
        if value is None:
            tag, data = 0, b""
        elif type(value) is bool:
            tag, data = 1, bytes([value])
        elif type(value) is int:
            if not -(1 << 63) <= value < (1 << 63):
                raise WireError("Integer payload value exceeds int64.")
            tag, data = 2, struct.pack(">q", value)
        elif type(value) is float:
            if not math.isfinite(value):
                raise WireError("Non-finite float payload value.")
            tag, data = 3, struct.pack(">d", value)
        elif type(value) is str:
            try:
                data = value.encode("utf-8")
            except UnicodeError as exc:
                raise WireError("Invalid UTF-8 string.") from exc
            tag = 4
        else:
            raise WireError("Binary payload supports null, boolean, int64, float64, and UTF-8 strings.")
        if len(data) > 255:
            raise WireError("Field exceeds uint8 length.")
        output.extend(bytes([FIELDS[key], tag, len(data)]) + data)
    if len(output) > MAX_PAYLOAD_BYTES:
        raise WireError("Binary payload exceeds 229 bytes.")
    return bytes(output)


def decode_binary_payload(data: bytes) -> dict:
    if len(data) > MAX_PAYLOAD_BYTES:
        raise WireError("Binary payload exceeds 229 bytes.")
    output = {}
    offset, previous = 0, 0
    while offset < len(data):
        if offset + 3 > len(data):
            raise WireError("Truncated field header.")
        key, tag, size = data[offset:offset + 3]
        offset += 3
        if key not in FIELD_NAMES or key <= previous or offset + size > len(data):
            raise WireError("Unknown, duplicate, unordered, or truncated field.")
        previous = key
        value_bytes = data[offset:offset + size]
        offset += size
        if tag == 0 and size == 0:
            value = None
        elif tag == 1 and size == 1 and value_bytes[0] in (0, 1):
            value = bool(value_bytes[0])
        elif tag == 2 and size == 8:
            value = struct.unpack(">q", value_bytes)[0]
        elif tag == 3 and size == 8:
            value = struct.unpack(">d", value_bytes)[0]
            if not math.isfinite(value):
                raise WireError("Non-finite float payload value.")
        elif tag == 4:
            try:
                value = value_bytes.decode("utf-8")
            except UnicodeError as exc:
                raise WireError("Invalid UTF-8 string.") from exc
        else:
            raise WireError("Invalid field type or width.")
        output[FIELD_NAMES[key]] = value
    return output


@dataclass(frozen=True)
class WirePacket:
    packet_type: PacketType
    network: int
    source: int
    origin: int
    next_hop: int
    destination: int
    sequence: int
    priority: int
    hops: int
    ttl: int
    payload: dict
    key_id: int = 0
    flags: int = 0
    version: int = VERSION


def _validate(packet: WirePacket) -> None:
    if packet.version != VERSION or type(packet.version) is not int:
        raise WireError("Unsupported wire version.")
    if packet.packet_type not in PACKET_TYPES:
        raise WireError("Unsupported packet type.")
    for name, low, high in (
        ("network", 1, 65534), ("source", 1, 65534), ("origin", 1, 65534),
        ("next_hop", 1, 65535), ("destination", 1, 65535),
        ("sequence", 0, 0xFFFFFFFF), ("priority", 0, 4),
        ("hops", 0, 255), ("ttl", 0, 255), ("key_id", 0, 0), ("flags", 0, 0),
    ):
        value = getattr(packet, name)
        if type(value) is not int or not low <= value <= high:
            raise WireError(f"Invalid {name}; expected integer {low}..{high}.")


def encode_frame(packet: WirePacket) -> bytes:
    _validate(packet)
    payload = encode_binary_payload(packet.payload)
    header = HEADER.pack(MAGIC, packet.version, PACKET_TYPES[packet.packet_type],
                         packet.network, packet.source, packet.origin, packet.next_hop,
                         packet.destination, packet.sequence, packet.priority, packet.hops,
                         packet.ttl, packet.flags, packet.key_id, len(payload))
    data = header + payload
    return data + struct.pack(">H", crc16(data))


def decode_frame(data: bytes, *, expected_network: int | None = None,
                 receiver: int | None = None) -> WirePacket:
    if not HEADER_BYTES + CRC_BYTES <= len(data) <= MAX_FRAME_BYTES:
        raise WireError("Invalid frame length.")
    if crc16(data[:-2]) != int.from_bytes(data[-2:], "big"):
        raise WireError("CRC mismatch.")
    magic, version, kind, network, source, origin, next_hop, dest, seq, priority, hops, ttl, flags, key, size = HEADER.unpack(data[:HEADER_BYTES])
    types = {value: name for name, value in PACKET_TYPES.items()}
    if magic != MAGIC or kind not in types or size != len(data) - HEADER_BYTES - CRC_BYTES:
        raise WireError("Invalid magic, packet type, or payload length.")
    packet = WirePacket(types[kind], network, source, origin, next_hop, dest,
                        seq, priority, hops, ttl, decode_binary_payload(data[HEADER_BYTES:-2]), key, flags, version)
    _validate(packet)
    if expected_network is not None and network != expected_network:
        raise WireError("Wrong network.")
    if receiver is not None and next_hop not in (receiver, BROADCAST):
        raise WireError("Frame is addressed to another next hop.")
    return packet
