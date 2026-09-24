#pragma once
// Portable C++11 codec. No Arduino dependencies. See BINARY_PACKET_FORMAT.md.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

namespace seian {
static const std::size_t header_bytes = 24, max_payload_bytes = 229, max_frame_bytes = 255;
static const uint16_t broadcast = 0xffff;
enum PacketType : uint8_t {
    hello=1, hello_reply=2, heartbeat=3, grid_state=4, route_advertisement=5,
    fault_alert=6, fault_ack=7, control_coordination=8, gateway_announce=9, route_error=10
};
enum FieldId : uint8_t {
    destination_id=1, destination_sequence=2, hop_count=3, route_cost=4, lifetime_s=5,
    advertised_next_hop=6, gateway_path=7, electrical_risk=8, communication_health=9,
    communication_congestion=10, communication_fault_status=11, failed_next_hop=12,
    reason=13, voltage=14, frequency=15, phase=16, load=17, temperature=18,
    fault_status=19, fault_id=20, fault_type=21, fault_domain=22, severity=23,
    recommended_action=24, recommendation=25, safety_note=26, acknowledges=27,
    timestamp=28, current=29, active_power=30, reactive_power=31, power_factor=32, thd=33
};
enum ValueType : uint8_t { null_value=0, boolean=1, int64=2, float64=3, utf8=4 };
struct Field {
    uint8_t id = 0, type = 0;
    std::vector<uint8_t> value;
};
struct Packet {
    uint8_t version = 1, type = hello;
    uint16_t network = 1, source = 1, origin = 1, next_hop = broadcast, destination = broadcast;
    uint32_t sequence = 0;
    uint8_t priority = 0, hops = 0, ttl = 1, flags = 0, key_id = 0;
    std::vector<Field> payload;
};
inline void put(std::vector<uint8_t>& out, uint64_t value, unsigned bytes) {
    for (unsigned i = bytes; i > 0; --i) out.push_back(static_cast<uint8_t>(value >> (8*(i-1))));
}
inline uint64_t get(const uint8_t* data, unsigned bytes) {
    uint64_t value = 0;
    for (unsigned i = 0; i < bytes; ++i) value = (value << 8) | data[i];
    return value;
}
inline uint16_t crc16(const uint8_t* data, std::size_t size) {
    uint16_t crc = 0xffff;
    for (std::size_t i=0; i<size; ++i) {
        crc ^= static_cast<uint16_t>(data[i]) << 8;
        for (unsigned b=0; b<8; ++b)
            crc = static_cast<uint16_t>((crc << 1) ^ ((crc & 0x8000) ? 0x1021 : 0));
    }
    return crc;
}
inline bool valid_utf8(const std::vector<uint8_t>& data) {
    std::size_t i=0;
    while (i<data.size()) {
        const uint8_t first=data[i++];
        if (first < 0x80) continue;
        unsigned tail; uint32_t cp, minimum;
        if (first >= 0xc2 && first <= 0xdf) { tail=1; cp=first & 31; minimum=0x80; }
        else if (first >= 0xe0 && first <= 0xef) { tail=2; cp=first & 15; minimum=0x800; }
        else if (first >= 0xf0 && first <= 0xf4) { tail=3; cp=first & 7; minimum=0x10000; }
        else return false;
        if (i+tail > data.size()) return false;
        for (unsigned j=0; j<tail; ++j) {
            const uint8_t ch=data[i++];
            if ((ch & 0xc0) != 0x80) return false;
            cp=(cp << 6) | (ch & 63);
        }
        if (cp<minimum || cp>0x10ffff || (cp>=0xd800 && cp<=0xdfff)) return false;
    }
    return true;
}
inline double as_double(const Field& field) {
    static_assert(sizeof(double)==8 && std::numeric_limits<double>::is_iec559, "IEEE-754 binary64 required");
    uint64_t bits=get(field.value.data(), 8); double result;
    std::memcpy(&result, &bits, sizeof result); return result;
}
inline bool valid_field(const Field& field) {
    if (field.id<1 || field.id>33 || field.value.size()>255) return false;
    switch (field.type) {
    case null_value: return field.value.empty();
    case boolean: return field.value.size()==1 && field.value[0]<=1;
    case int64: return field.value.size()==8;
    case float64: return field.value.size()==8 && std::isfinite(as_double(field));
    case utf8: return valid_utf8(field.value);
    default: return false;
    }
}
inline Field null_field(uint8_t id) { Field f; f.id=id; return f; }
inline Field bool_field(uint8_t id, bool value) {
    Field f; f.id=id; f.type=boolean; f.value.push_back(value ? 1 : 0); return f;
}
inline Field integer_field(uint8_t id, int64_t value) {
    Field f; f.id=id; f.type=int64; put(f.value, static_cast<uint64_t>(value), 8); return f;
}
inline Field double_field(uint8_t id, double value) {
    Field f; f.id=id; f.type=float64; uint64_t bits;
    static_assert(sizeof bits==sizeof value, "binary64 required");
    std::memcpy(&bits, &value, sizeof bits); put(f.value, bits, 8); return f;
}
inline Field string_field(uint8_t id, const std::string& value) {
    Field f; f.id=id; f.type=utf8; f.value.assign(value.begin(), value.end()); return f;
}
inline bool valid_header(const Packet& p) {
    return p.version==1 && p.type>=1 && p.type<=10 && p.network>0 && p.network<broadcast
        && p.source>0 && p.source<broadcast && p.origin>0 && p.origin<broadcast
        && p.next_hop>0 && p.destination>0 && p.priority<=4 && p.flags==0 && p.key_id==0;
}
inline bool encode(const Packet& p, std::vector<uint8_t>& output) {
    // Commit output only after validation; no partial output on failure.
    if (!valid_header(p)) return false;
    std::vector<Field> fields=p.payload;
    std::sort(fields.begin(), fields.end(), [](const Field& a, const Field& b) { return a.id<b.id; });
    std::vector<uint8_t> payload;
    uint8_t previous=0;
    for (const auto& field : fields) {
        if (!valid_field(field) || field.id<=previous) return false;
        previous=field.id;
        payload.push_back(field.id); payload.push_back(field.type);
        payload.push_back(static_cast<uint8_t>(field.value.size()));
        payload.insert(payload.end(), field.value.begin(), field.value.end());
        if (payload.size()>max_payload_bytes) return false;
    }
    std::vector<uint8_t> out;
    out.push_back('S'); out.push_back('A'); out.push_back(p.version); out.push_back(p.type);
    put(out,p.network,2); put(out,p.source,2); put(out,p.origin,2);
    put(out,p.next_hop,2); put(out,p.destination,2); put(out,p.sequence,4);
    out.push_back(p.priority); out.push_back(p.hops); out.push_back(p.ttl);
    out.push_back(p.flags); out.push_back(p.key_id); out.push_back(static_cast<uint8_t>(payload.size()));
    out.insert(out.end(),payload.begin(),payload.end());
    put(out,crc16(out.data(),out.size()),2);
    output.swap(out); return true;
}
inline bool decode(const uint8_t* data, std::size_t size, Packet& output,
                   uint16_t expected_network=0, uint16_t receiver=0) {
    if (!data || size<header_bytes+2 || size>max_frame_bytes) return false;
    if (data[0]!='S' || data[1]!='A' || data[23]!=size-header_bytes-2) return false;
    if (crc16(data,size-2)!=get(data+size-2,2)) return false;
    Packet p;
    p.version=data[2]; p.type=data[3]; p.network=static_cast<uint16_t>(get(data+4,2));
    p.source=static_cast<uint16_t>(get(data+6,2)); p.origin=static_cast<uint16_t>(get(data+8,2));
    p.next_hop=static_cast<uint16_t>(get(data+10,2)); p.destination=static_cast<uint16_t>(get(data+12,2));
    p.sequence=static_cast<uint32_t>(get(data+14,4)); p.priority=data[18]; p.hops=data[19];
    p.ttl=data[20]; p.flags=data[21]; p.key_id=data[22];
    if (!valid_header(p) || (expected_network && p.network!=expected_network)
        || (receiver && p.next_hop!=receiver && p.next_hop!=broadcast)) return false;
    std::size_t offset=header_bytes; uint8_t previous=0;
    while (offset<size-2) {
        if (offset+3>size-2) return false;
        Field f; f.id=data[offset++]; f.type=data[offset++]; const uint8_t length=data[offset++];
        if (offset+length>size-2 || f.id<=previous) return false;
        previous=f.id; f.value.assign(data+offset,data+offset+length); offset+=length;
        if (!valid_field(f)) return false;
        p.payload.push_back(f);
    }
    output=p; return true;
}
} // namespace seian
