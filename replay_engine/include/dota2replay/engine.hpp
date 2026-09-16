#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace dota2replay {

struct ByteView {
    const std::uint8_t* data = nullptr;
    std::size_t size = 0;
};

class DecodeError final : public std::runtime_error {
public:
    DecodeError(std::string message, std::size_t offset);
    std::size_t offset() const noexcept { return offset_; }

private:
    std::size_t offset_;
};

std::vector<std::uint8_t> decode_snappy(ByteView input,
                                        std::size_t max_output_bytes = 512ULL << 20);
std::vector<std::uint8_t> decode_valve_lzss(ByteView input,
                                            std::size_t max_output_bytes = 512ULL << 20);

enum class WireType : std::uint8_t {
    Varint = 0,
    Fixed64 = 1,
    LengthDelimited = 2,
    Fixed32 = 5,
};

struct ProtoField {
    std::uint32_t number = 0;
    WireType wire_type = WireType::Varint;
    std::uint64_t scalar = 0;
    ByteView bytes{};
    std::size_t offset = 0;
};

struct NetworkScan {
    std::uint64_t message_count = 0;
    std::uint64_t body_bytes = 0;
    std::unordered_map<std::uint32_t, std::uint64_t> type_counts;
    std::optional<std::uint64_t> first_net_tick;
    std::optional<std::uint64_t> last_net_tick;
    std::uint64_t packet_entities_count = 0;
    std::uint64_t packet_entity_updates = 0;
    std::uint64_t packet_entity_data_bytes = 0;
    std::uint64_t flattened_serializer_messages = 0;
    std::uint64_t serializer_count = 0;
    std::uint64_t serializer_field_count = 0;
    std::uint64_t serializer_symbol_count = 0;
    std::uint64_t network_class_count = 0;
    std::uint64_t created_string_tables = 0;
    std::uint64_t updated_string_tables = 0;
    std::optional<std::uint64_t> server_max_classes;
    std::optional<float> server_tick_interval;
    std::string server_game_directory;
    std::uint64_t instancebaseline_declared_entries = 0;
    std::uint64_t instancebaseline_encoded_bytes = 0;
    bool instancebaseline_compressed = false;
    bool instancebaseline_varint_bit_counts = false;
    std::uint64_t instancebaseline_item_count = 0;
    std::uint64_t instancebaseline_value_bytes = 0;
    std::uint64_t instancebaseline_lzss_blocks = 0;
    std::uint64_t instancebaseline_snappy_blocks = 0;
    std::vector<std::uint32_t> instancebaseline_class_ids;
    std::vector<std::pair<std::uint32_t, std::vector<std::uint8_t>>> instancebaselines;
};

NetworkScan scan_network_packet(ByteView packet,
                                std::size_t max_messages = 1'000'000,
                                std::size_t max_message_bytes = 256ULL << 20);

struct FieldPath {
    std::array<std::int32_t, 7> components{};
    std::size_t depth = 0;
};

struct FieldPathScan {
    std::vector<FieldPath> paths;
    std::size_t bits_consumed = 0;
};

FieldPathScan scan_field_paths(ByteView encoded, std::size_t max_paths = 1'000'000);

class ProtoReader {
public:
    explicit ProtoReader(ByteView input, std::size_t max_fields = 1'000'000);
    bool next(ProtoField& field);

private:
    std::uint64_t read_varint(const char* label);
    ByteView input_;
    std::size_t cursor_ = 0;
    std::size_t count_ = 0;
    std::size_t max_fields_;
};

enum class FieldModel : std::uint8_t {
    Simple,
    FixedArray,
    FixedTable,
    VariableArray,
    VariableTable,
};

struct FieldType {
    std::string original;
    std::string base_type;
    std::string generic_type;
    std::string array_token;
    bool pointer = false;
    std::size_t count = 0;
};

FieldType parse_field_type(std::string type_name);

struct SerializerField {
    std::string variable_type;
    std::string variable_name;
    std::string serializer_name;
    std::string send_node;
    std::string encoder;
    std::string variable_serializer;
    std::optional<std::uint32_t> bit_count;
    std::optional<std::uint32_t> encode_flags;
    std::optional<float> low_value;
    std::optional<float> high_value;
    FieldType parsed_type;
    FieldModel model = FieldModel::Simple;
};

struct SerializerDefinition {
    std::string name;
    std::int32_t version = 0;
    std::vector<std::uint32_t> field_indices;
};

struct SerializerCatalog {
    std::vector<std::string> symbols;
    std::vector<SerializerField> fields;
    std::vector<SerializerDefinition> serializers;
    std::unordered_map<std::string, std::size_t> serializer_by_name;
    std::uint64_t unresolved_symbol_references = 0;
    std::uint64_t invalid_field_references = 0;
    std::uint64_t unresolved_serializer_links = 0;
};

SerializerCatalog parse_flattened_serializer(ByteView protobuf_message);

struct FileHeaderInfo {
    std::string demo_file_stamp;
    std::string server_name;
    std::string map_name;
    std::string game_directory;
    std::string demo_version_name;
    std::string game;
    std::optional<std::uint64_t> patch_version;
    std::optional<std::uint64_t> build_num;
};

struct FileInfo {
    std::optional<float> playback_time;
    std::optional<std::uint64_t> playback_ticks;
    std::optional<std::uint64_t> playback_frames;
    std::optional<std::uint64_t> match_id;
    std::optional<std::uint64_t> game_mode;
    std::optional<std::uint64_t> game_winner;
    std::size_t player_count = 0;
};

struct ScanReport {
    std::string path;
    std::uint64_t file_size = 0;
    std::uint32_t file_info_offset = 0;
    std::uint32_t spawn_groups_offset = 0;
    std::uint64_t command_count = 0;
    std::uint64_t compressed_command_count = 0;
    std::uint64_t compressed_input_bytes = 0;
    std::uint64_t decoded_payload_bytes = 0;
    std::uint64_t protobuf_field_count = 0;
    std::uint64_t packet_count = 0;
    std::uint64_t packet_data_bytes = 0;
    std::uint64_t network_message_count = 0;
    std::uint64_t network_message_body_bytes = 0;
    std::unordered_map<std::uint32_t, std::uint64_t> network_message_counts;
    std::optional<std::uint64_t> first_net_tick;
    std::optional<std::uint64_t> last_net_tick;
    std::uint64_t packet_entities_count = 0;
    std::uint64_t packet_entity_updates = 0;
    std::uint64_t packet_entity_data_bytes = 0;
    std::uint64_t flattened_serializer_messages = 0;
    std::uint64_t serializer_count = 0;
    std::uint64_t serializer_field_count = 0;
    std::uint64_t serializer_symbol_count = 0;
    std::uint64_t network_class_count = 0;
    std::uint64_t created_string_tables = 0;
    std::uint64_t updated_string_tables = 0;
    std::optional<std::uint64_t> server_max_classes;
    std::optional<float> server_tick_interval;
    std::string server_game_directory;
    std::uint64_t instancebaseline_declared_entries = 0;
    std::uint64_t instancebaseline_encoded_bytes = 0;
    bool instancebaseline_compressed = false;
    bool instancebaseline_varint_bit_counts = false;
    std::uint64_t instancebaseline_item_count = 0;
    std::uint64_t instancebaseline_value_bytes = 0;
    std::uint64_t instancebaseline_lzss_blocks = 0;
    std::uint64_t instancebaseline_snappy_blocks = 0;
    std::uint64_t instancebaseline_linked_classes = 0;
    std::uint64_t instancebaseline_unlinked_classes = 0;
    std::uint64_t baseline_field_path_count = 0;
    std::uint64_t baseline_field_path_bits = 0;
    std::uint64_t baseline_invalid_root_paths = 0;
    std::uint64_t baseline_max_field_path_depth = 0;
    std::uint64_t send_table_serializer_count = 0;
    std::uint64_t send_table_field_count = 0;
    std::uint64_t send_table_symbol_count = 0;
    std::uint64_t unresolved_serializer_symbols = 0;
    std::uint64_t invalid_serializer_field_references = 0;
    std::uint64_t linked_server_classes = 0;
    std::uint64_t unlinked_server_classes = 0;
    std::uint64_t hero_serializer_count = 0;
    std::uint64_t simple_serializer_fields = 0;
    std::uint64_t fixed_array_serializer_fields = 0;
    std::uint64_t fixed_table_serializer_fields = 0;
    std::uint64_t variable_array_serializer_fields = 0;
    std::uint64_t variable_table_serializer_fields = 0;
    std::uint64_t unresolved_nested_serializer_links = 0;
    std::uint64_t class_count = 0;
    std::uint64_t spawn_group_message_count = 0;
    std::unordered_map<std::uint32_t, std::uint64_t> command_counts;
    std::optional<FileHeaderInfo> file_header;
    std::optional<FileInfo> file_info;
};

ScanReport scan_replay(const std::string& path,
                       std::size_t max_file_bytes = 2ULL << 30,
                       std::size_t max_frame_bytes = 256ULL << 20,
                       std::size_t max_decoded_frame_bytes = 512ULL << 20);

std::string report_json(const ScanReport& report);

}  // namespace dota2replay
