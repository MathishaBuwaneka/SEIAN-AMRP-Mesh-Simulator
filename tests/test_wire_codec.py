from dataclasses import replace
import json
import math
import os
from pathlib import Path
import random
import struct
import subprocess

import pytest

from seian_sim.enums import PacketType
from seian_sim.wire import (
    BROADCAST, HEADER_BYTES, WireError, WirePacket, crc16, decode_frame,
    encode_frame, encode_binary_payload, decode_binary_payload,
)

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads((ROOT / "tests/fixtures/wire_v1.json").read_text(encoding="utf-8"))


def sample():
    return WirePacket(**VECTORS[0]["packet"])


@pytest.fixture(scope="module")
def cpp():
    filename = "codec_cli.exe" if os.name == "nt" else "codec_cli"
    path = Path(os.environ.get("SEIAN_CODEC_CLI", ROOT / "output/wire-codec" / filename))
    if not path.is_file():
        pytest.skip("Build the host C++ test utility with scripts/build_wire_codec.py first.")
    return path


def cpp_run(path, frame, *filters):
    return subprocess.run([str(path), "roundtrip", frame.hex(), *map(str, filters)],
                          capture_output=True, text=True, timeout=10)


@pytest.mark.parametrize("row", VECTORS, ids=lambda row: row["name"])
def test_frozen_vectors_python(row):
    packet = WirePacket(**row["packet"])
    expected = bytes.fromhex(row["hex"])
    assert encode_frame(packet) == expected
    assert decode_frame(expected) == packet


@pytest.mark.parametrize("row", VECTORS, ids=lambda row: row["name"])
def test_cpp_decodes_and_reencodes_vectors(cpp, row):
    result = cpp_run(cpp, bytes.fromhex(row["hex"]))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == row["hex"]


@pytest.mark.parametrize("name", ["telemetry", "scalars"])
def test_cpp_constructed_packets_match_python_and_frozen_vectors(cpp, name):
    result = subprocess.run([str(cpp), "fixture", name], capture_output=True, text=True, timeout=10)
    row = next(row for row in VECTORS if row["name"] == name)
    assert result.returncode == 0
    assert result.stdout.strip() == row["hex"]
    assert decode_frame(bytes.fromhex(result.stdout)) == WirePacket(**row["packet"])


def with_crc(data):
    return data + crc16(data).to_bytes(2, "big")


def malformed_frames():
    valid = encode_frame(sample())
    frames = [valid[:-1], valid+b"\x00", b"\x00"*256, valid[:-1]+bytes([valid[-1]^1])]
    # Recompute CRC so header-validation tests actually get past checksum checks.
    for offset, value in [(0, 0), (2, 2), (3, 255), (18, 5), (21, 1), (22, 1), (23, 0)]:
        data = bytearray(valid[:-2]); data[offset] = value
        frames.append(with_crc(data))
    for offset in [4, 6, 8, 10, 12]:
        data = bytearray(valid[:-2]); data[offset:offset+2] = b"\x00\x00"
        frames.append(with_crc(data))
    for payload in [
        b"\x01", b"\x00\x00\x00", b"\x22\x00\x00", b"\x01\xff\x00",
        b"\x01\x01\x01\x02", b"\x01\x02\x01\x01",
        b"\x01\x04\x02\xc0\x80", b"\x01\x04\x03\xed\xa0\x80",
        b"\x01\x03\x08"+struct.pack(">d", math.inf),
        b"\x01\x00\x00\x01\x00\x00", b"\x02\x00\x00\x01\x00\x00",
        b"\x01\x04\xffx",
    ]:
        header = bytearray(valid[:HEADER_BYTES]); header[23] = len(payload)
        frames.append(with_crc(header+payload))
    return frames


@pytest.mark.parametrize("frame", malformed_frames(), ids=lambda value: value.hex()[:16]+f"-{len(value)}")
def test_python_rejects_malformed_frames(frame):
    with pytest.raises(WireError):
        decode_frame(frame)


def test_cpp_rejects_same_malformed_frames_and_all_truncations(cpp):
    valid = encode_frame(sample())
    for frame in malformed_frames() + [valid[:size] for size in range(len(valid))]:
        assert cpp_run(cpp, frame).returncode == 1, frame.hex()


def test_python_rejects_all_truncations_and_crc_reference():
    assert HEADER_BYTES == 24
    assert crc16(b"123456789") == 0x29B1
    frame = encode_frame(sample())
    for size in range(len(frame)):
        with pytest.raises(WireError):
            decode_frame(frame[:size])


@pytest.mark.parametrize("changes", [
    {"version": 2}, {"flags": 1}, {"key_id": 1}, {"priority": 5}, {"ttl": 256},
    {"source": 0}, {"origin": BROADCAST}, {"sequence": 2**32}, {"sequence": -1},
    {"network": True}, {"hops": -1}, {"payload": {"voltage": math.nan}},
    {"payload": {"temperature": 2**63}}, {"payload": {"temperature": -2**63-1}},
    {"payload": {"unknown": 1}}, {"payload": {"voltage": [1, 2]}},
    {"payload": {"fault_id": "x" * 227}}, {"payload": {"fault_id": "\ud800"}},
])
def test_encoder_rejects_unsupported_inputs(changes):
    with pytest.raises(WireError):
        encode_frame(replace(sample(), **changes))


def test_maximum_frame_boundary_and_canonical_field_order():
    frame = encode_frame(replace(sample(), payload={"fault_id": "x" * 226}))
    assert len(frame) == 255
    assert decode_frame(frame).payload == {"fault_id": "x" * 226}
    assert encode_binary_payload({"voltage": 230.0, "frequency": 50.0}) == encode_binary_payload({"frequency": 50.0, "voltage": 230.0})
    for value in [-2**63, 2**63-1, -0.0, 0.0, 1e-300, 1e300, None, False, True, "\U0001f50c"]:
        assert decode_binary_payload(encode_binary_payload({"voltage": value})) == {"voltage": value}


def test_network_and_next_hop_filtering_python_and_cpp(cpp):
    frame = encode_frame(sample())
    assert decode_frame(frame, expected_network=1, receiver=3) == sample()
    for network, receiver in [(2, 3), (1, 2)]:
        with pytest.raises(WireError):
            decode_frame(frame, expected_network=network, receiver=receiver)
        assert cpp_run(cpp, frame, network, receiver).returncode == 1
    broadcast = encode_frame(replace(sample(), next_hop=BROADCAST, destination=BROADCAST))
    assert decode_frame(broadcast, receiver=4).destination == BROADCAST
    assert cpp_run(cpp, broadcast, 1, 4).returncode == 0


def test_seeded_cross_language_roundtrips_all_packet_types(cpp):
    rng = random.Random(371)
    for kind in PacketType:
        for _ in range(5):
            packet = replace(sample(), packet_type=kind, sequence=rng.randrange(2**32),
                             hops=rng.randrange(256), ttl=rng.randrange(256),
                             payload={"voltage": rng.uniform(-500, 500),
                                      "temperature": rng.randrange(-2**63, 2**63),
                                      "gateway_path": bool(rng.randrange(2))})
            frame = encode_frame(packet)
            result = cpp_run(cpp, frame)
            assert result.returncode == 0
            assert result.stdout.strip() == frame.hex()
            assert decode_frame(bytes.fromhex(result.stdout)) == packet
