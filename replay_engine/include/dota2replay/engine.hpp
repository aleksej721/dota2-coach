#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
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
};

NetworkScan scan_network_packet(ByteView packet,
                                std::size_t max_messages = 1'000'000,
                                std::size_t max_message_bytes = 256ULL << 20);

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
