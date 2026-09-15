#include "dota2replay/engine.hpp"

#include <cassert>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>

using dota2replay::ByteView;

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

std::vector<std::uint8_t> one_network_message(std::uint8_t type,
                                              const std::vector<std::uint8_t>& body) {
    // Test-only bit writer for the short UBitVar form and one-byte length.
    std::vector<unsigned> bits;
    for (unsigned i = 0; i < 6; ++i) bits.push_back((type >> i) & 1);
    for (unsigned i = 0; i < 8; ++i) bits.push_back((body.size() >> i) & 1);
    for (const auto byte : body) {
        for (unsigned i = 0; i < 8; ++i) bits.push_back((byte >> i) & 1);
    }
    std::vector<std::uint8_t> output((bits.size() + 7) / 8, 0);
    for (std::size_t i = 0; i < bits.size(); ++i) output[i / 8] |= bits[i] << (i % 8);
    return output;
}

int main() {
    {
        // decoded length=9, literal "abc", COPY_2(offset=3, length=6)
        const std::vector<std::uint8_t> encoded = {9, 8, 'a', 'b', 'c', 0x16, 3, 0};
        const auto decoded = dota2replay::decode_snappy({encoded.data(), encoded.size()});
        require(std::string(decoded.begin(), decoded.end()) == "abcabcabc", "Snappy copy");
    }
    {
        // field 1 varint=150, field 2 bytes="dota", field 3 fixed32=0xaabbccdd
        const std::vector<std::uint8_t> encoded = {
            0x08, 0x96, 0x01, 0x12, 0x04, 'd', 'o', 't', 'a',
            0x1d, 0xdd, 0xcc, 0xbb, 0xaa,
        };
        dota2replay::ProtoReader reader({encoded.data(), encoded.size()});
        dota2replay::ProtoField field;
        require(reader.next(field) && field.number == 1 && field.scalar == 150, "varint");
        require(reader.next(field) && field.number == 2 && field.bytes.size == 4, "bytes");
        require(reader.next(field) && field.number == 3 && field.scalar == 0xaabbccdd, "fixed32");
        require(!reader.next(field), "protobuf end");
    }
    {
        bool rejected = false;
        const std::vector<std::uint8_t> bad = {4, 1, 1};
        try {
            (void)dota2replay::decode_snappy({bad.data(), bad.size()});
        } catch (const dota2replay::DecodeError&) {
            rejected = true;
        }
        require(rejected, "invalid Snappy block accepted");
    }
    {
        const auto encoded = one_network_message(5, {0xab});
        const auto scan = dota2replay::scan_network_packet({encoded.data(), encoded.size()});
        require(scan.message_count == 1, "network count");
        require(scan.body_bytes == 1, "network bytes");
        require(scan.type_counts.at(5) == 1, "network type");
    }
    {
        const auto encoded = one_network_message(4, {0x08, 0x7b});
        const auto scan = dota2replay::scan_network_packet({encoded.data(), encoded.size()});
        require(scan.first_net_tick == 123, "net tick");
        require(scan.last_net_tick == 123, "last net tick");
    }
    std::cout << "replay engine core tests passed\n";
    return 0;
}
