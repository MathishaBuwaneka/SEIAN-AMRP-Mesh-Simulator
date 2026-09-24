// Host-side interoperability test utility; no device access.
#include "seian_wire.hpp"
#include <iostream>
#include <iomanip>
#include <sstream>

int main(int argc, char** argv) {
    if (argc<3) return 2;
    seian::Packet p;
    if (std::string(argv[1])=="fixture") {
        p.type=seian::grid_state; p.source=2; p.origin=2; p.next_hop=3;
        p.destination=1; p.sequence=42; p.priority=1; p.ttl=6;
        if (std::string(argv[2])=="telemetry") {
            p.payload.push_back(seian::double_field(seian::voltage,230.0));
            p.payload.push_back(seian::double_field(seian::frequency,50.0));
            p.payload.push_back(seian::string_field(seian::fault_status,"normal"));
        } else if (std::string(argv[2])=="scalars") {
            p.payload.push_back(seian::null_field(seian::advertised_next_hop));
            p.payload.push_back(seian::bool_field(seian::gateway_path,true));
            p.payload.push_back(seian::integer_field(seian::temperature,-12));
            p.payload.push_back(seian::string_field(seian::fault_id,"\xc3\xa9"));
        } else return 2;
    } else if (std::string(argv[1])=="roundtrip") {
        std::string hex=argv[2]; std::vector<uint8_t> bytes;
        if (hex.size()%2) return 2;
        for (std::size_t i=0; i<hex.size(); i+=2) {
            unsigned value; std::istringstream in(hex.substr(i,2));
            if (!(in >> std::hex >> value)) return 2;
            bytes.push_back(static_cast<uint8_t>(value));
        }
        uint16_t network=argc>3 ? static_cast<uint16_t>(std::stoi(argv[3])) : 0;
        uint16_t receiver=argc>4 ? static_cast<uint16_t>(std::stoi(argv[4])) : 0;
        if (!seian::decode(bytes.data(),bytes.size(),p,network,receiver)) return 1;
    } else return 2;
    std::vector<uint8_t> encoded;
    if (!seian::encode(p,encoded)) return 1;
    for (uint8_t b : encoded) std::cout << std::hex << std::setfill('0') << std::setw(2) << unsigned(b);
    std::cout << '\n';
    return 0;
}
