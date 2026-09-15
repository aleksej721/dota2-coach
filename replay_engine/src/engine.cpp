#include "dota2replay/engine.hpp"

#include <algorithm>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <iomanip>
#include <limits>
#include <sstream>
#include <string_view>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

namespace dota2replay {
namespace {

constexpr std::uint8_t kCompressedFlag = 0x40;
constexpr std::size_t kHeaderSize = 16;
constexpr std::uint32_t kDemFileHeader = 1;
constexpr std::uint32_t kDemFileInfo = 2;
constexpr std::uint32_t kDemClassInfo = 5;
constexpr std::uint32_t kDemPacket = 7;
constexpr std::uint32_t kDemSignonPacket = 8;
constexpr std::uint32_t kDemFullPacket = 13;
constexpr std::uint32_t kDemSpawnGroups = 15;

std::uint32_t little_u32(const std::uint8_t* data) {
    return static_cast<std::uint32_t>(data[0]) |
           (static_cast<std::uint32_t>(data[1]) << 8) |
           (static_cast<std::uint32_t>(data[2]) << 16) |
           (static_cast<std::uint32_t>(data[3]) << 24);
}

std::uint64_t little_u64(const std::uint8_t* data) {
    return static_cast<std::uint64_t>(little_u32(data)) |
           (static_cast<std::uint64_t>(little_u32(data + 4)) << 32);
}

class MappedFile {
public:
    explicit MappedFile(const std::string& path) : path_(path) {
        fd_ = ::open(path.c_str(), O_RDONLY);
        if (fd_ < 0) {
            throw std::runtime_error("cannot open replay: " + path + ": " + std::strerror(errno));
        }
        struct stat status {};
        if (::fstat(fd_, &status) != 0) {
            const std::string message = std::strerror(errno);
            ::close(fd_);
            fd_ = -1;
            throw std::runtime_error("cannot stat replay: " + path + ": " + message);
        }
        if (!S_ISREG(status.st_mode) || status.st_size < 0) {
            ::close(fd_);
            fd_ = -1;
            throw std::runtime_error("replay is not a regular file: " + path);
        }
        size_ = static_cast<std::size_t>(status.st_size);
        if (size_ != 0) {
            void* mapping = ::mmap(nullptr, size_, PROT_READ, MAP_PRIVATE, fd_, 0);
            if (mapping == MAP_FAILED) {
                const std::string message = std::strerror(errno);
                ::close(fd_);
                fd_ = -1;
                throw std::runtime_error("cannot map replay: " + path + ": " + message);
            }
            data_ = static_cast<const std::uint8_t*>(mapping);
        }
    }

    MappedFile(const MappedFile&) = delete;
    MappedFile& operator=(const MappedFile&) = delete;

    ~MappedFile() {
        if (data_ != nullptr) ::munmap(const_cast<std::uint8_t*>(data_), size_);
        if (fd_ >= 0) ::close(fd_);
    }

    ByteView view() const { return {data_, size_}; }
    std::size_t size() const { return size_; }

private:
    std::string path_;
    int fd_ = -1;
    const std::uint8_t* data_ = nullptr;
    std::size_t size_ = 0;
};

class Cursor {
public:
    explicit Cursor(ByteView input) : input_(input) {}

    std::size_t position() const { return cursor_; }
    bool done() const { return cursor_ == input_.size; }

    std::uint32_t varuint32(const char* label) {
        const std::size_t start = cursor_;
        std::uint32_t value = 0;
        for (unsigned index = 0; index < 5; ++index) {
            if (cursor_ >= input_.size) {
                throw DecodeError(std::string("truncated ") + label + " varint", start);
            }
            const std::uint8_t byte = input_.data[cursor_++];
            if (index == 4 && byte > 0x0f) {
                throw DecodeError(std::string(label) + " varint overflows uint32", start);
            }
            value |= static_cast<std::uint32_t>(byte & 0x7f) << (index * 7);
            if ((byte & 0x80) == 0) return value;
        }
        throw DecodeError(std::string("unterminated ") + label + " varint", start);
    }

    ByteView bytes(std::size_t size, const char* label) {
        const std::size_t start = cursor_;
        if (size > input_.size - cursor_) {
            throw DecodeError(std::string("truncated ") + label, start);
        }
        cursor_ += size;
        return {input_.data + start, size};
    }

private:
    ByteView input_;
    std::size_t cursor_ = 0;
};

class BitReader {
public:
    explicit BitReader(ByteView input) : input_(input) {}

    std::size_t position() const { return position_; }
    std::size_t remaining() const { return input_.size * 8 - position_; }

    std::uint32_t bits(unsigned count) {
        if (count > 32) throw std::invalid_argument("bit read exceeds 32 bits");
        const std::size_t start = position_;
        if (count > remaining()) throw DecodeError("truncated bitstream", start);
        std::uint32_t value = 0;
        unsigned shift = 0;
        unsigned left = count;
        while (left != 0) {
            const std::size_t byte_index = position_ >> 3;
            const unsigned bit_index = static_cast<unsigned>(position_ & 7);
            const unsigned take = std::min(left, 8U - bit_index);
            const std::uint32_t mask = (1U << take) - 1U;
            value |= ((input_.data[byte_index] >> bit_index) & mask) << shift;
            position_ += take;
            shift += take;
            left -= take;
        }
        return value;
    }

    std::uint32_t varuint32() {
        const std::size_t start = position_;
        std::uint32_t value = 0;
        for (unsigned index = 0; index < 5; ++index) {
            const std::uint32_t byte = bits(8);
            if (index == 4 && byte > 0x0f) throw DecodeError("varuint32 overflow", start);
            value |= (byte & 0x7f) << (index * 7);
            if ((byte & 0x80) == 0) return value;
        }
        throw DecodeError("unterminated varuint32", start);
    }

    std::uint32_t ubitvar() {
        const std::uint32_t prefix = bits(6);
        switch (prefix & 0x30) {
            case 0x10: return (prefix & 0x0f) | (bits(4) << 4);
            case 0x20: return (prefix & 0x0f) | (bits(8) << 4);
            case 0x30: return (prefix & 0x0f) | (bits(28) << 4);
            default: return prefix;
        }
    }

    void skip(std::size_t count) {
        if (count > remaining()) throw DecodeError("bitstream body exceeds packet", position_);
        position_ += count;
    }

    void bytes(std::size_t count, std::vector<std::uint8_t>& output) {
        if (count > remaining() / 8) {
            throw DecodeError("bitstream body exceeds packet", position_);
        }
        output.resize(count);
        if ((position_ & 7) == 0) {
            std::memcpy(output.data(), input_.data + (position_ >> 3), count);
            position_ += count * 8;
            return;
        }
        for (std::size_t index = 0; index < count; ++index) {
            output[index] = static_cast<std::uint8_t>(bits(8));
        }
    }

private:
    ByteView input_;
    std::size_t position_ = 0;
};

std::unordered_map<std::uint32_t, std::vector<ProtoField>> group_fields(ByteView input,
                                                                        std::uint64_t* count = nullptr) {
    std::unordered_map<std::uint32_t, std::vector<ProtoField>> grouped;
    ProtoReader reader(input);
    ProtoField field;
    while (reader.next(field)) {
        grouped[field.number].push_back(field);
        if (count != nullptr) ++*count;
    }
    return grouped;
}

const ProtoField* first(const std::unordered_map<std::uint32_t, std::vector<ProtoField>>& fields,
                        std::uint32_t number, WireType wire) {
    const auto found = fields.find(number);
    if (found == fields.end()) return nullptr;
    for (const auto& field : found->second) {
        if (field.wire_type == wire) return &field;
    }
    return nullptr;
}

std::string text_field(const std::unordered_map<std::uint32_t, std::vector<ProtoField>>& fields,
                       std::uint32_t number) {
    const ProtoField* field = first(fields, number, WireType::LengthDelimited);
    if (field == nullptr) return {};
    return std::string(reinterpret_cast<const char*>(field->bytes.data), field->bytes.size);
}

std::optional<std::uint64_t> integer_field(
        const std::unordered_map<std::uint32_t, std::vector<ProtoField>>& fields,
        std::uint32_t number) {
    const ProtoField* field = first(fields, number, WireType::Varint);
    if (field == nullptr) return std::nullopt;
    return field->scalar;
}

FileHeaderInfo parse_file_header(ByteView body) {
    const auto fields = group_fields(body);
    return {
        text_field(fields, 1), text_field(fields, 3), text_field(fields, 5),
        text_field(fields, 6), text_field(fields, 11), text_field(fields, 14),
        integer_field(fields, 2), integer_field(fields, 13),
    };
}

FileInfo parse_file_info(ByteView body) {
    const auto fields = group_fields(body);
    FileInfo info;
    if (const ProtoField* playback = first(fields, 1, WireType::Fixed32)) {
        const std::uint32_t bits = static_cast<std::uint32_t>(playback->scalar);
        float value = 0;
        std::memcpy(&value, &bits, sizeof(value));
        info.playback_time = value;
    }
    info.playback_ticks = integer_field(fields, 2);
    info.playback_frames = integer_field(fields, 3);
    const ProtoField* game_info = first(fields, 4, WireType::LengthDelimited);
    if (game_info == nullptr) return info;
    const auto game_fields = group_fields(game_info->bytes);
    const ProtoField* dota = first(game_fields, 4, WireType::LengthDelimited);
    if (dota == nullptr) return info;
    const auto dota_fields = group_fields(dota->bytes);
    info.match_id = integer_field(dota_fields, 1);
    info.game_mode = integer_field(dota_fields, 2);
    info.game_winner = integer_field(dota_fields, 3);
    const auto players = dota_fields.find(4);
    if (players != dota_fields.end()) {
        info.player_count = static_cast<std::size_t>(std::count_if(
            players->second.begin(), players->second.end(),
            [](const ProtoField& field) { return field.wire_type == WireType::LengthDelimited; }));
    }
    return info;
}

std::optional<ByteView> packet_data(
        std::uint32_t command,
        const std::unordered_map<std::uint32_t, std::vector<ProtoField>>& fields) {
    if (command == kDemPacket || command == kDemSignonPacket) {
        const ProtoField* data = first(fields, 3, WireType::LengthDelimited);
        return data == nullptr ? std::nullopt : std::optional<ByteView>(data->bytes);
    }
    if (command != kDemFullPacket) return std::nullopt;
    const ProtoField* packet = first(fields, 2, WireType::LengthDelimited);
    if (packet == nullptr) return std::nullopt;
    const auto packet_fields = group_fields(packet->bytes);
    const ProtoField* data = first(packet_fields, 3, WireType::LengthDelimited);
    return data == nullptr ? std::nullopt : std::optional<ByteView>(data->bytes);
}

std::string json_escape(std::string_view value) {
    std::ostringstream out;
    for (const unsigned char character : value) {
        switch (character) {
            case '"': out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\b': out << "\\b"; break;
            case '\f': out << "\\f"; break;
            case '\n': out << "\\n"; break;
            case '\r': out << "\\r"; break;
            case '\t': out << "\\t"; break;
            default:
                if (character < 0x20) {
                    out << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                        << static_cast<unsigned>(character) << std::dec;
                } else {
                    out << character;
                }
        }
    }
    return out.str();
}

template <typename T>
void optional_json(std::ostringstream& out, const std::optional<T>& value) {
    if (value) out << *value;
    else out << "null";
}

}  // namespace

DecodeError::DecodeError(std::string message, std::size_t offset)
    : std::runtime_error(std::move(message) + " at byte offset " + std::to_string(offset)),
      offset_(offset) {}

std::vector<std::uint8_t> decode_snappy(ByteView input, std::size_t max_output_bytes) {
    Cursor cursor(input);
    const std::uint32_t expected = cursor.varuint32("Snappy decoded length");
    if (expected > max_output_bytes) {
        throw DecodeError("Snappy decoded size exceeds limit", 0);
    }
    std::vector<std::uint8_t> output(expected);
    std::size_t written = 0;
    while (written < expected) {
        const std::size_t tag_offset = cursor.position();
        const ByteView tag_view = cursor.bytes(1, "Snappy tag");
        const std::uint8_t tag = tag_view.data[0];
        const std::uint8_t kind = tag & 3;
        if (kind == 0) {
            std::size_t length = tag >> 2;
            if (length < 60) {
                ++length;
            } else {
                const std::size_t length_bytes = length - 59;
                const ByteView encoded = cursor.bytes(length_bytes, "Snappy literal length");
                std::uint64_t value = 0;
                for (std::size_t i = 0; i < length_bytes; ++i) {
                    value |= static_cast<std::uint64_t>(encoded.data[i]) << (8 * i);
                }
                length = static_cast<std::size_t>(value + 1);
            }
            const ByteView literal = cursor.bytes(length, "Snappy literal");
            if (length > output.size() - written) {
                throw DecodeError("Snappy literal exceeds declared output", tag_offset);
            }
            std::memcpy(output.data() + written, literal.data, length);
            written += length;
            continue;
        }

        std::size_t length = 0;
        std::size_t offset = 0;
        if (kind == 1) {
            length = 4 + ((tag >> 2) & 7);
            const ByteView encoded = cursor.bytes(1, "Snappy COPY_1 offset");
            offset = static_cast<std::size_t>((tag & 0xe0) << 3) | encoded.data[0];
        } else if (kind == 2) {
            length = 1 + (tag >> 2);
            const ByteView encoded = cursor.bytes(2, "Snappy COPY_2 offset");
            offset = static_cast<std::size_t>(encoded.data[0]) |
                     (static_cast<std::size_t>(encoded.data[1]) << 8);
        } else {
            length = 1 + (tag >> 2);
            const ByteView encoded = cursor.bytes(4, "Snappy COPY_4 offset");
            offset = little_u32(encoded.data);
        }
        if (offset == 0 || offset > written) {
            throw DecodeError("invalid Snappy copy offset", tag_offset);
        }
        if (length > output.size() - written) {
            throw DecodeError("Snappy copy exceeds declared output", tag_offset);
        }
        for (std::size_t i = 0; i < length; ++i) {
            output[written + i] = output[written - offset + i];
        }
        written += length;
    }
    if (!cursor.done()) throw DecodeError("trailing bytes after Snappy block", cursor.position());
    return output;
}

ProtoReader::ProtoReader(ByteView input, std::size_t max_fields)
    : input_(input), max_fields_(max_fields) {
    if (max_fields == 0) throw std::invalid_argument("max_fields must be positive");
}

NetworkScan scan_network_packet(ByteView packet, std::size_t max_messages,
                                std::size_t max_message_bytes) {
    if (max_messages == 0 || max_message_bytes == 0) {
        throw std::invalid_argument("network message limits must be positive");
    }
    BitReader reader(packet);
    NetworkScan scan;
    std::vector<std::uint8_t> body;
    // A minimal message needs a 6-bit type and one 8-bit size byte. Fewer bits
    // can only be byte-container padding left by the packed bitstream.
    while (reader.remaining() >= 14) {
        const std::size_t offset = reader.position();
        const std::uint32_t type = reader.ubitvar();
        const std::uint32_t size = reader.varuint32();
        if (size > max_message_bytes) {
            throw DecodeError("network message body exceeds limit", offset);
        }
        if (++scan.message_count > max_messages) {
            throw DecodeError("network message count exceeds limit", offset);
        }
        scan.body_bytes += size;
        ++scan.type_counts[type];

        const bool inspect_body = type == 4 || type == 40 || type == 41 ||
                                  type == 42 || type == 44 || type == 45 || type == 55;
        if (!inspect_body) {
            reader.skip(static_cast<std::size_t>(size) * 8);
            continue;
        }
        reader.bytes(size, body);
        const ByteView body_view{body.data(), body.size()};
        const auto fields = group_fields(body_view);
        if (type == 4) {  // net_Tick / CNETMsg_Tick
            const auto tick = integer_field(fields, 1);
            if (tick) {
                if (!scan.first_net_tick) scan.first_net_tick = *tick;
                scan.last_net_tick = *tick;
            }
        } else if (type == 41) {  // svc_FlattenedSerializer
            ++scan.flattened_serializer_messages;
            if (const auto found = fields.find(1); found != fields.end()) {
                scan.serializer_count += found->second.size();
            }
            if (const auto found = fields.find(2); found != fields.end()) {
                scan.serializer_symbol_count += found->second.size();
            }
            if (const auto found = fields.find(3); found != fields.end()) {
                scan.serializer_field_count += found->second.size();
            }
        } else if (type == 42) {  // svc_ClassInfo
            if (const auto found = fields.find(2); found != fields.end()) {
                scan.network_class_count += found->second.size();
            }
        } else if (type == 44) {  // svc_CreateStringTable
            ++scan.created_string_tables;
        } else if (type == 45) {  // svc_UpdateStringTable
            ++scan.updated_string_tables;
        } else if (type == 55) {  // svc_PacketEntities
            ++scan.packet_entities_count;
            if (const auto updates = integer_field(fields, 2)) {
                scan.packet_entity_updates += *updates;
            }
            if (const ProtoField* entity_data = first(fields, 7, WireType::LengthDelimited)) {
                scan.packet_entity_data_bytes += entity_data->bytes.size;
            }
            if (const ProtoField* serialized = first(fields, 13, WireType::LengthDelimited)) {
                scan.packet_entity_data_bytes += serialized->bytes.size;
            }
        }
    }
    // Valve's packet container is byte-sized while its final UBitVar stream is
    // not necessarily byte-aligned. Manta likewise stops when no complete next
    // header can be read; the remaining sub-header bits are opaque padding.
    return scan;
}

std::uint64_t ProtoReader::read_varint(const char* label) {
    const std::size_t start = cursor_;
    std::uint64_t value = 0;
    for (unsigned index = 0; index < 10; ++index) {
        if (cursor_ >= input_.size) {
            throw DecodeError(std::string("truncated protobuf ") + label, start);
        }
        const std::uint8_t byte = input_.data[cursor_++];
        if (index == 9 && byte > 1) {
            throw DecodeError(std::string("protobuf ") + label + " overflows uint64", start);
        }
        value |= static_cast<std::uint64_t>(byte & 0x7f) << (index * 7);
        if ((byte & 0x80) == 0) return value;
    }
    throw DecodeError(std::string("unterminated protobuf ") + label, start);
}

bool ProtoReader::next(ProtoField& field) {
    if (cursor_ == input_.size) return false;
    const std::size_t start = cursor_;
    const std::uint64_t key = read_varint("field key");
    const std::uint64_t number = key >> 3;
    const std::uint8_t wire = static_cast<std::uint8_t>(key & 7);
    if (number == 0 || number > std::numeric_limits<std::uint32_t>::max()) {
        throw DecodeError("invalid protobuf field number", start);
    }
    if (++count_ > max_fields_) throw DecodeError("protobuf field count exceeds limit", start);
    field = {};
    field.number = static_cast<std::uint32_t>(number);
    field.offset = start;
    switch (wire) {
        case 0:
            field.wire_type = WireType::Varint;
            field.scalar = read_varint("value");
            break;
        case 1:
            if (input_.size - cursor_ < 8) throw DecodeError("truncated protobuf fixed64", start);
            field.wire_type = WireType::Fixed64;
            field.scalar = little_u64(input_.data + cursor_);
            cursor_ += 8;
            break;
        case 2: {
            field.wire_type = WireType::LengthDelimited;
            const std::uint64_t length = read_varint("length");
            if (length > input_.size - cursor_) {
                throw DecodeError("protobuf field exceeds message", start);
            }
            field.bytes = {input_.data + cursor_, static_cast<std::size_t>(length)};
            cursor_ += static_cast<std::size_t>(length);
            break;
        }
        case 5:
            if (input_.size - cursor_ < 4) throw DecodeError("truncated protobuf fixed32", start);
            field.wire_type = WireType::Fixed32;
            field.scalar = little_u32(input_.data + cursor_);
            cursor_ += 4;
            break;
        default:
            throw DecodeError("unsupported protobuf wire type " + std::to_string(wire), start);
    }
    return true;
}

ScanReport scan_replay(const std::string& path, std::size_t max_file_bytes,
                       std::size_t max_frame_bytes, std::size_t max_decoded_frame_bytes) {
    MappedFile file(path);
    if (file.size() > max_file_bytes) throw DecodeError("replay exceeds file-size limit", 0);
    const ByteView input = file.view();
    if (input.size < kHeaderSize) throw DecodeError("truncated PBDEMS2 header", input.size);
    static constexpr std::uint8_t magic[] = {'P', 'B', 'D', 'E', 'M', 'S', '2', 0};
    if (std::memcmp(input.data, magic, sizeof(magic)) != 0) {
        throw DecodeError("unexpected replay magic; expected PBDEMS2", 0);
    }

    ScanReport report;
    report.path = path;
    report.file_size = input.size;
    report.file_info_offset = little_u32(input.data + 8);
    report.spawn_groups_offset = little_u32(input.data + 12);
    if (report.file_info_offset != 0 &&
        (report.file_info_offset < kHeaderSize || report.file_info_offset >= input.size)) {
        throw DecodeError("DEM_FileInfo offset outside command stream", 8);
    }
    if (report.spawn_groups_offset != 0 &&
        (report.spawn_groups_offset < kHeaderSize || report.spawn_groups_offset >= input.size)) {
        throw DecodeError("DEM_SpawnGroups offset outside command stream", 12);
    }

    Cursor cursor({input.data + kHeaderSize, input.size - kHeaderSize});
    bool info_target_seen = false;
    bool spawn_target_seen = false;
    while (!cursor.done()) {
        const std::size_t frame_offset = kHeaderSize + cursor.position();
        const std::uint32_t raw_command = cursor.varuint32("command");
        (void)cursor.varuint32("tick");
        const std::uint32_t body_size = cursor.varuint32("body size");
        if (body_size > max_frame_bytes) throw DecodeError("command body exceeds limit", frame_offset);
        const ByteView stored_body = cursor.bytes(body_size, "command body");
        const bool compressed = (raw_command & kCompressedFlag) != 0;
        const std::uint32_t command = raw_command & ~kCompressedFlag;
        ++report.command_count;
        ++report.command_counts[command];

        std::vector<std::uint8_t> decoded;
        ByteView body = stored_body;
        if (compressed) {
            ++report.compressed_command_count;
            report.compressed_input_bytes += stored_body.size;
            try {
                decoded = decode_snappy(stored_body, max_decoded_frame_bytes);
            } catch (const DecodeError& error) {
                throw DecodeError("Snappy decode failed for command " + std::to_string(command) +
                                  ": " + error.what(), frame_offset);
            }
            body = {decoded.data(), decoded.size()};
        }
        report.decoded_payload_bytes += body.size;
        std::unordered_map<std::uint32_t, std::vector<ProtoField>> fields;
        try {
            fields = group_fields(body, &report.protobuf_field_count);
        } catch (const DecodeError& error) {
            throw DecodeError("protobuf decode failed for command " + std::to_string(command) +
                              ": " + error.what(), frame_offset);
        }

        if (frame_offset == report.file_info_offset) info_target_seen = command == kDemFileInfo;
        if (frame_offset == report.spawn_groups_offset) spawn_target_seen = command == kDemSpawnGroups;
        if (command == kDemFileHeader) report.file_header = parse_file_header(body);
        if (command == kDemFileInfo) report.file_info = parse_file_info(body);
        if (command == kDemClassInfo) {
            const auto found = fields.find(1);
            if (found != fields.end()) report.class_count += found->second.size();
        }
        if (command == kDemSpawnGroups) {
            const auto found = fields.find(3);
            if (found != fields.end()) report.spawn_group_message_count += found->second.size();
        }
        if (const auto packet = packet_data(command, fields)) {
            ++report.packet_count;
            report.packet_data_bytes += packet->size;
            try {
                const NetworkScan network = scan_network_packet(*packet);
                report.network_message_count += network.message_count;
                report.network_message_body_bytes += network.body_bytes;
                for (const auto& [type, count] : network.type_counts) {
                    report.network_message_counts[type] += count;
                }
                if (network.first_net_tick && !report.first_net_tick) {
                    report.first_net_tick = network.first_net_tick;
                }
                if (network.last_net_tick) report.last_net_tick = network.last_net_tick;
                report.packet_entities_count += network.packet_entities_count;
                report.packet_entity_updates += network.packet_entity_updates;
                report.packet_entity_data_bytes += network.packet_entity_data_bytes;
                report.flattened_serializer_messages += network.flattened_serializer_messages;
                report.serializer_count += network.serializer_count;
                report.serializer_field_count += network.serializer_field_count;
                report.serializer_symbol_count += network.serializer_symbol_count;
                report.network_class_count += network.network_class_count;
                report.created_string_tables += network.created_string_tables;
                report.updated_string_tables += network.updated_string_tables;
            } catch (const DecodeError& error) {
                throw DecodeError("network framing failed for command " +
                                  std::to_string(command) + ": " + error.what(),
                                  frame_offset);
            }
        }
    }
    if (report.file_info_offset != 0 && !info_target_seen) {
        throw DecodeError("DEM_FileInfo offset does not point to DEM_FileInfo", report.file_info_offset);
    }
    if (report.spawn_groups_offset != 0 && !spawn_target_seen) {
        throw DecodeError("DEM_SpawnGroups offset does not point to DEM_SpawnGroups",
                          report.spawn_groups_offset);
    }
    return report;
}

std::string report_json(const ScanReport& report) {
    std::ostringstream out;
    out << '{'
        << "\"schema_version\":1,"
        << "\"engine\":\"dota2replay-cpp\","
        << "\"engine_version\":\"0.1.0\","
        << "\"status\":\"payloads_decoded\"," 
        << "\"path\":\"" << json_escape(report.path) << "\"," 
        << "\"file_size\":" << report.file_size << ','
        << "\"file_info_offset\":" << report.file_info_offset << ','
        << "\"spawn_groups_offset\":" << report.spawn_groups_offset << ','
        << "\"command_count\":" << report.command_count << ','
        << "\"compressed_command_count\":" << report.compressed_command_count << ','
        << "\"compressed_input_bytes\":" << report.compressed_input_bytes << ','
        << "\"decoded_payload_bytes\":" << report.decoded_payload_bytes << ','
        << "\"protobuf_field_count\":" << report.protobuf_field_count << ','
        << "\"packet_count\":" << report.packet_count << ','
        << "\"packet_data_bytes\":" << report.packet_data_bytes << ','
        << "\"network_message_count\":" << report.network_message_count << ','
        << "\"network_message_body_bytes\":" << report.network_message_body_bytes << ','
        << "\"first_net_tick\":";
    optional_json(out, report.first_net_tick);
    out << ",\"last_net_tick\":";
    optional_json(out, report.last_net_tick);
    out << ",\"packet_entities_count\":" << report.packet_entities_count << ','
        << "\"packet_entity_updates\":" << report.packet_entity_updates << ','
        << "\"packet_entity_data_bytes\":" << report.packet_entity_data_bytes << ','
        << "\"flattened_serializer_messages\":" << report.flattened_serializer_messages << ','
        << "\"serializer_count\":" << report.serializer_count << ','
        << "\"serializer_field_count\":" << report.serializer_field_count << ','
        << "\"serializer_symbol_count\":" << report.serializer_symbol_count << ','
        << "\"network_class_count\":" << report.network_class_count << ','
        << "\"created_string_tables\":" << report.created_string_tables << ','
        << "\"updated_string_tables\":" << report.updated_string_tables << ','
        << "\"class_count\":" << report.class_count << ','
        << "\"spawn_group_message_count\":" << report.spawn_group_message_count << ',';

    out << "\"network_message_counts\":{";
    std::vector<std::pair<std::uint32_t, std::uint64_t>> network_counts(
        report.network_message_counts.begin(), report.network_message_counts.end());
    std::sort(network_counts.begin(), network_counts.end());
    for (std::size_t index = 0; index < network_counts.size(); ++index) {
        if (index != 0) out << ',';
        out << '\"' << network_counts[index].first << "\":" << network_counts[index].second;
    }
    out << "},";

    out << "\"file_header\":";
    if (!report.file_header) {
        out << "null";
    } else {
        const auto& h = *report.file_header;
        out << '{'
            << "\"demo_file_stamp\":\"" << json_escape(h.demo_file_stamp) << "\"," 
            << "\"server_name\":\"" << json_escape(h.server_name) << "\"," 
            << "\"map_name\":\"" << json_escape(h.map_name) << "\"," 
            << "\"game_directory\":\"" << json_escape(h.game_directory) << "\"," 
            << "\"demo_version_name\":\"" << json_escape(h.demo_version_name) << "\"," 
            << "\"game\":\"" << json_escape(h.game) << "\"," 
            << "\"patch_version\":";
        optional_json(out, h.patch_version);
        out << ",\"build_num\":";
        optional_json(out, h.build_num);
        out << '}';
    }

    out << ",\"file_info\":";
    if (!report.file_info) {
        out << "null";
    } else {
        const auto& info = *report.file_info;
        out << "{\"playback_time\":";
        optional_json(out, info.playback_time);
        out << ",\"playback_ticks\":";
        optional_json(out, info.playback_ticks);
        out << ",\"playback_frames\":";
        optional_json(out, info.playback_frames);
        out << ",\"match_id\":";
        optional_json(out, info.match_id);
        out << ",\"game_mode\":";
        optional_json(out, info.game_mode);
        out << ",\"game_winner\":";
        optional_json(out, info.game_winner);
        out << ",\"player_count\":" << info.player_count << '}';
    }
    out << '}';
    return out.str();
}

}  // namespace dota2replay
