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
        // Valve LZSS: five literals selected by low zero bits, then end marker.
        const std::vector<std::uint8_t> encoded = {
            'L', 'Z', 'S', 'S', 5, 0, 0, 0, 0x20,
            'h', 'e', 'l', 'l', 'o', 0, 0,
        };
        const auto decoded = dota2replay::decode_valve_lzss(
            {encoded.data(), encoded.size()}
        );
        require(std::string(decoded.begin(), decoded.end()) == "hello", "Valve LZSS");
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
    {
        // Huffman stream: PlusOne (0), PlusTwo (1110), Finish (10), LSB first.
        const std::vector<std::uint8_t> encoded = {0x2e};
        const auto scan = dota2replay::scan_field_paths({encoded.data(), encoded.size()});
        require(scan.paths.size() == 2, "field-path count");
        require(scan.paths[0].depth == 1 && scan.paths[0].components[0] == 0,
                "first field path");
        require(scan.paths[1].depth == 1 && scan.paths[1].components[0] == 2,
                "second field path");
        require(scan.bits_consumed == 7, "field-path consumed bits");
    }
    {
        // symbols: 0="Hero", 1="int32", 2="m_iHealth"
        // field: var_type_sym=1, var_name_sym=2
        // serializer: name_sym=0, version=1, fields_index=[0]
        const std::vector<std::uint8_t> serializer = {
            0x0a, 0x06, 0x08, 0x00, 0x10, 0x01, 0x18, 0x00,
            0x12, 0x04, 'H', 'e', 'r', 'o',
            0x12, 0x05, 'i', 'n', 't', '3', '2',
            0x12, 0x09, 'm', '_', 'i', 'H', 'e', 'a', 'l', 't', 'h',
            0x1a, 0x04, 0x08, 0x01, 0x10, 0x02,
        };
        const auto catalog = dota2replay::parse_flattened_serializer(
            {serializer.data(), serializer.size()}
        );
        require(catalog.symbols.size() == 3, "serializer symbols");
        require(catalog.fields.size() == 1, "serializer fields");
        require(catalog.serializers.size() == 1, "serializers");
        require(catalog.serializers[0].name == "Hero", "serializer name");
        require(catalog.fields[0].variable_type == "int32", "field type");
        require(catalog.fields[0].variable_name == "m_iHealth", "field name");
        require(catalog.invalid_field_references == 0, "field references");
    }
    {
        const auto nested = dota2replay::parse_field_type(
            "CUtlVector< CHandle< CBaseEntity > >*"
        );
        require(nested.base_type == "CUtlVector", "generic base type");
        require(nested.generic_type == "CHandle< CBaseEntity >", "generic child type");
        require(nested.pointer, "generic pointer");
        const auto fixed = dota2replay::parse_field_type("Item_t[MAX_ITEM_STOCKS]");
        require(fixed.base_type == "Item_t", "array base type");
        require(fixed.count == 8, "symbolic array count");
    }
    std::cout << "replay engine core tests passed\n";
    return 0;
}
