#include "dota2replay/engine.hpp"

#include <algorithm>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <iomanip>
#include <limits>
#include <queue>
#include <sstream>
#include <string_view>
#include <unordered_set>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

namespace dota2replay {
namespace {

constexpr std::uint8_t kCompressedFlag = 0x40;
constexpr std::size_t kHeaderSize = 16;
constexpr std::uint32_t kDemFileHeader = 1;
constexpr std::uint32_t kDemFileInfo = 2;
constexpr std::uint32_t kDemSendTables = 4;
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

std::string trim_copy(std::string value) {
    const auto first = value.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return {};
    const auto last = value.find_last_not_of(" \t\r\n");
    return value.substr(first, last - first + 1);
}

bool pointer_table_type(const std::string& base_type) {
    static const std::unordered_set<std::string> types = {
        "PhysicsRagdollPose_t", "CBodyComponent", "CEntityIdentity",
        "CPhysicsComponent", "CRenderComponent", "CDOTAGamerules",
        "CDOTAGameManager", "CDOTASpectatorGraphManager", "CPlayerLocalData",
        "CPlayer_CameraServices", "CDOTAGameRules",
    };
    return types.count(base_type) != 0;
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

    std::int32_t varint32() {
        const std::uint32_t encoded = varuint32();
        const std::int32_t value = static_cast<std::int32_t>(encoded >> 1);
        return (encoded & 1U) != 0 ? ~value : value;
    }

    std::uint32_t ubitvar_field_path() {
        if (boolean()) return bits(2);
        if (boolean()) return bits(4);
        if (boolean()) return bits(10);
        if (boolean()) return bits(17);
        return bits(31);
    }

    bool boolean() { return bits(1) != 0; }

    std::string string_zero_terminated() {
        std::string value;
        while (true) {
            if (remaining() < 8) throw DecodeError("unterminated bitstream string", position_);
            const auto byte = static_cast<std::uint8_t>(bits(8));
            if (byte == 0) return value;
            value.push_back(static_cast<char>(byte));
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

struct HuffmanNode {
    std::uint64_t weight = 0;
    std::int32_t value = 0;
    std::int32_t left = -1;
    std::int32_t right = -1;
    bool leaf = false;
};

const std::vector<HuffmanNode>& field_path_huffman_tree() {
    static const std::vector<HuffmanNode> tree = [] {
        static constexpr std::array<std::uint32_t, 40> weights = {
            36271, 10334, 1375, 646, 4128, 35, 3, 521, 2942, 560,
            471, 10530, 251, 0, 0, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0, 310, 2, 0, 1837,
            149, 300, 634, 0, 0, 1, 76, 271, 99, 25474,
        };
        std::vector<HuffmanNode> nodes;
        nodes.reserve(weights.size() * 2 - 1);
        for (std::size_t value = 0; value < weights.size(); ++value) {
            nodes.push_back({std::max<std::uint32_t>(weights[value], 1),
                             static_cast<std::int32_t>(value), -1, -1, true});
        }
        struct Compare {
            const std::vector<HuffmanNode>* nodes = nullptr;
            bool operator()(std::int32_t left, std::int32_t right) const {
                const auto& a = (*nodes)[left];
                const auto& b = (*nodes)[right];
                if (a.weight != b.weight) return a.weight > b.weight;
                return a.value < b.value;
            }
        };
        std::priority_queue<std::int32_t, std::vector<std::int32_t>, Compare> queue(
            Compare{&nodes}
        );
        for (std::size_t index = 0; index < weights.size(); ++index) {
            queue.push(static_cast<std::int32_t>(index));
        }
        std::int32_t value = static_cast<std::int32_t>(weights.size());
        while (queue.size() > 1) {
            const std::int32_t left = queue.top();
            queue.pop();
            const std::int32_t right = queue.top();
            queue.pop();
            nodes.push_back({nodes[left].weight + nodes[right].weight,
                             value++, left, right, false});
            queue.push(static_cast<std::int32_t>(nodes.size() - 1));
        }
        return nodes;
    }();
    return tree;
}

std::uint32_t read_field_path_op(BitReader& reader) {
    const auto& tree = field_path_huffman_tree();
    std::int32_t node_index = static_cast<std::int32_t>(tree.size() - 1);
    while (!tree[node_index].leaf) {
        node_index = reader.boolean() ? tree[node_index].right : tree[node_index].left;
        if (node_index < 0 || static_cast<std::size_t>(node_index) >= tree.size()) {
            throw DecodeError("invalid field-path Huffman node", reader.position());
        }
    }
    return static_cast<std::uint32_t>(tree[node_index].value);
}

class MutableFieldPath {
public:
    MutableFieldPath() { components_[0] = -1; }

    std::size_t last() const { return last_; }
    std::int32_t value(std::size_t index) const { return components_.at(index); }

    void add(std::size_t index, std::int64_t delta, std::size_t offset) {
        if (index > last_) throw DecodeError("field-path component outside depth", offset);
        const std::int64_t result = static_cast<std::int64_t>(components_[index]) + delta;
        if (result < std::numeric_limits<std::int32_t>::min() ||
            result > std::numeric_limits<std::int32_t>::max()) {
            throw DecodeError("field-path component overflow", offset);
        }
        components_[index] = static_cast<std::int32_t>(result);
    }

    void push(std::int64_t value, std::size_t offset) {
        if (last_ + 1 >= components_.size()) {
            throw DecodeError("field path exceeds maximum depth", offset);
        }
        ++last_;
        if (value < std::numeric_limits<std::int32_t>::min() ||
            value > std::numeric_limits<std::int32_t>::max()) {
            throw DecodeError("field-path component overflow", offset);
        }
        components_[last_] = static_cast<std::int32_t>(value);
    }

    void pop(std::uint32_t count, std::size_t offset) {
        if (count > last_) throw DecodeError("field-path pop exceeds depth", offset);
        for (std::uint32_t index = 0; index < count; ++index) {
            components_[last_] = 0;
            --last_;
        }
    }

    FieldPath snapshot() const { return {components_, last_ + 1}; }

private:
    std::array<std::int32_t, 7> components_{};
    std::size_t last_ = 0;
};

struct StringTableItem {
    std::int32_t index = -1;
    std::string key;
    std::vector<std::uint8_t> value;
};

std::vector<StringTableItem> parse_string_table(
        ByteView encoded, std::uint32_t update_count, bool user_data_fixed,
        std::uint32_t user_data_size_bits, std::uint32_t flags,
        bool varint_bit_counts) {
    std::vector<StringTableItem> items;
    items.reserve(update_count);
    if (encoded.size == 0) return items;
    BitReader reader(encoded);
    std::int64_t index = -1;
    std::vector<std::string> history;
    history.reserve(32);

    for (std::uint32_t update = 0; update < update_count; ++update) {
        StringTableItem item;
        if (reader.boolean()) {
            ++index;
        } else {
            index += static_cast<std::int64_t>(reader.varuint32()) + 2;
        }
        if (index < 0 || index > std::numeric_limits<std::int32_t>::max()) {
            throw DecodeError("invalid string-table index", reader.position());
        }
        item.index = static_cast<std::int32_t>(index);

        if (reader.boolean()) {
            if (reader.boolean()) {
                const std::size_t history_index = reader.bits(5);
                const std::size_t prefix_size = reader.bits(5);
                const std::string suffix = reader.string_zero_terminated();
                if (history_index < history.size()) {
                    const auto& previous = history[history_index];
                    item.key = previous.substr(0, std::min(prefix_size, previous.size())) + suffix;
                } else {
                    item.key = suffix;
                }
            } else {
                item.key = reader.string_zero_terminated();
            }
            if (history.size() == 32) history.erase(history.begin());
            history.push_back(item.key);
        }

        if (reader.boolean()) {
            bool compressed = false;
            std::uint64_t bit_size = 0;
            if (user_data_fixed) {
                bit_size = user_data_size_bits;
            } else {
                if ((flags & 1U) != 0) compressed = reader.boolean();
                bit_size = static_cast<std::uint64_t>(
                    varint_bit_counts ? reader.ubitvar() : reader.bits(17)
                ) * 8;
            }
            if (bit_size > (512ULL << 20) * 8 || bit_size % 8 != 0) {
                throw DecodeError("invalid string-table value bit size", reader.position());
            }
            reader.bytes(static_cast<std::size_t>(bit_size / 8), item.value);
            if (compressed) {
                item.value = decode_snappy({item.value.data(), item.value.size()});
            }
        }
        items.push_back(std::move(item));
    }
    return items;
}

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

std::optional<float> float_field(
        const std::unordered_map<std::uint32_t, std::vector<ProtoField>>& fields,
        std::uint32_t number) {
    const ProtoField* field = first(fields, number, WireType::Fixed32);
    if (field == nullptr) return std::nullopt;
    const std::uint32_t bits = static_cast<std::uint32_t>(field->scalar);
    float value = 0;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

std::vector<std::uint32_t> repeated_int32(
        const std::unordered_map<std::uint32_t, std::vector<ProtoField>>& fields,
        std::uint32_t number) {
    std::vector<std::uint32_t> values;
    const auto found = fields.find(number);
    if (found == fields.end()) return values;
    for (const auto& field : found->second) {
        if (field.wire_type == WireType::Varint) {
            values.push_back(static_cast<std::uint32_t>(field.scalar));
        } else if (field.wire_type == WireType::LengthDelimited) {
            Cursor packed(field.bytes);
            while (!packed.done()) values.push_back(packed.varuint32("packed int32"));
        }
    }
    return values;
}

std::optional<std::uint32_t> symbol_index(
        const std::unordered_map<std::uint32_t, std::vector<ProtoField>>& fields,
        std::uint32_t number) {
    const auto value = integer_field(fields, number);
    if (!value || *value > std::numeric_limits<std::uint32_t>::max()) return std::nullopt;
    return static_cast<std::uint32_t>(*value);
}

std::string resolve_symbol(const std::vector<std::string>& symbols,
                           std::optional<std::uint32_t> index,
                           std::uint64_t& unresolved) {
    if (!index) return {};
    if (*index >= symbols.size()) {
        ++unresolved;
        return {};
    }
    return symbols[*index];
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

std::vector<std::uint8_t> decode_valve_lzss(ByteView input,
                                            std::size_t max_output_bytes) {
    if (input.size < 8 || std::memcmp(input.data, "LZSS", 4) != 0) {
        throw DecodeError("expected Valve LZSS header", 0);
    }
    const std::uint32_t expected = little_u32(input.data + 4);
    if (expected > max_output_bytes) throw DecodeError("LZSS output exceeds limit", 4);
    Cursor cursor({input.data + 8, input.size - 8});
    std::vector<std::uint8_t> output;
    output.reserve(expected);
    std::uint8_t command = 0;
    std::uint8_t command_index = 0;
    bool terminated = false;
    while (!terminated) {
        if (command_index == 0) command = cursor.bytes(1, "LZSS command").data[0];
        command_index = static_cast<std::uint8_t>((command_index + 1) & 7);
        if ((command & 1U) == 0) {
            if (output.size() >= expected) {
                throw DecodeError("LZSS literal exceeds declared output", cursor.position());
            }
            output.push_back(cursor.bytes(1, "LZSS literal").data[0]);
        } else {
            const ByteView pair = cursor.bytes(2, "LZSS back-reference");
            const std::size_t position =
                (static_cast<std::size_t>(pair.data[0]) << 4) | (pair.data[1] >> 4);
            const std::size_t count = (pair.data[1] & 0x0f) + 1;
            if (count == 1) {
                terminated = true;
            } else {
                if (position >= output.size()) {
                    throw DecodeError("invalid LZSS back-reference", cursor.position() - 2);
                }
                if (count > expected - output.size()) {
                    throw DecodeError("LZSS copy exceeds declared output", cursor.position() - 2);
                }
                const std::size_t source = output.size() - position - 1;
                for (std::size_t index = 0; index < count; ++index) {
                    output.push_back(output[source + index]);
                }
            }
        }
        command >>= 1;
    }
    if (output.size() != expected) {
        throw DecodeError("LZSS decoded size does not match header", cursor.position());
    }
    return output;
}

FieldPathScan scan_field_paths(ByteView encoded, std::size_t max_paths) {
    if (max_paths == 0) throw std::invalid_argument("max_paths must be positive");
    BitReader reader(encoded);
    MutableFieldPath path;
    FieldPathScan scan;
    scan.paths.reserve(std::min<std::size_t>(encoded.size, max_paths));

    auto read_field_delta = [&reader]() -> std::int64_t {
        return static_cast<std::int64_t>(reader.ubitvar_field_path());
    };
    auto read_ubitvar = [&reader]() -> std::int64_t {
        return static_cast<std::int64_t>(reader.ubitvar());
    };

    while (true) {
        const std::size_t operation_offset = reader.position();
        const std::uint32_t operation = read_field_path_op(reader);
        switch (operation) {
            case 0: path.add(path.last(), 1, operation_offset); break;
            case 1: path.add(path.last(), 2, operation_offset); break;
            case 2: path.add(path.last(), 3, operation_offset); break;
            case 3: path.add(path.last(), 4, operation_offset); break;
            case 4: path.add(path.last(), read_field_delta() + 5, operation_offset); break;
            case 5: path.push(0, operation_offset); break;
            case 6: path.push(read_field_delta(), operation_offset); break;
            case 7:
                path.add(path.last(), 1, operation_offset);
                path.push(0, operation_offset);
                break;
            case 8:
                path.add(path.last(), 1, operation_offset);
                path.push(read_field_delta(), operation_offset);
                break;
            case 9:
                path.add(path.last(), read_field_delta(), operation_offset);
                path.push(0, operation_offset);
                break;
            case 10:
                path.add(path.last(), read_field_delta() + 2, operation_offset);
                path.push(read_field_delta() + 1, operation_offset);
                break;
            case 11:
                path.add(path.last(), static_cast<std::int64_t>(reader.bits(3)) + 2,
                         operation_offset);
                path.push(static_cast<std::int64_t>(reader.bits(3)) + 1, operation_offset);
                break;
            case 12:
                path.add(path.last(), static_cast<std::int64_t>(reader.bits(4)) + 2,
                         operation_offset);
                path.push(static_cast<std::int64_t>(reader.bits(4)) + 1, operation_offset);
                break;
            case 13:
                path.push(read_field_delta(), operation_offset);
                path.push(read_field_delta(), operation_offset);
                break;
            case 14:
                path.push(reader.bits(5), operation_offset);
                path.push(reader.bits(5), operation_offset);
                break;
            case 15:
                path.push(read_field_delta(), operation_offset);
                path.push(read_field_delta(), operation_offset);
                path.push(read_field_delta(), operation_offset);
                break;
            case 16:
                path.push(reader.bits(5), operation_offset);
                path.push(reader.bits(5), operation_offset);
                path.push(reader.bits(5), operation_offset);
                break;
            case 17:
                path.add(path.last(), 1, operation_offset);
                path.push(read_field_delta(), operation_offset);
                path.push(read_field_delta(), operation_offset);
                break;
            case 18:
                path.add(path.last(), 1, operation_offset);
                path.push(reader.bits(5), operation_offset);
                path.push(reader.bits(5), operation_offset);
                break;
            case 19:
                path.add(path.last(), 1, operation_offset);
                path.push(read_field_delta(), operation_offset);
                path.push(read_field_delta(), operation_offset);
                path.push(read_field_delta(), operation_offset);
                break;
            case 20:
                path.add(path.last(), 1, operation_offset);
                path.push(reader.bits(5), operation_offset);
                path.push(reader.bits(5), operation_offset);
                path.push(reader.bits(5), operation_offset);
                break;
            case 21:
                path.add(path.last(), read_ubitvar() + 2, operation_offset);
                path.push(read_field_delta(), operation_offset);
                path.push(read_field_delta(), operation_offset);
                break;
            case 22:
                path.add(path.last(), read_ubitvar() + 2, operation_offset);
                path.push(reader.bits(5), operation_offset);
                path.push(reader.bits(5), operation_offset);
                break;
            case 23:
                path.add(path.last(), read_ubitvar() + 2, operation_offset);
                path.push(read_field_delta(), operation_offset);
                path.push(read_field_delta(), operation_offset);
                path.push(read_field_delta(), operation_offset);
                break;
            case 24:
                path.add(path.last(), read_ubitvar() + 2, operation_offset);
                path.push(reader.bits(5), operation_offset);
                path.push(reader.bits(5), operation_offset);
                path.push(reader.bits(5), operation_offset);
                break;
            case 25: {
                const std::uint32_t count = reader.ubitvar();
                path.add(path.last(), read_ubitvar(), operation_offset);
                for (std::uint32_t index = 0; index < count; ++index) {
                    path.push(read_field_delta(), operation_offset);
                }
                break;
            }
            case 26: {
                const std::size_t last = path.last();
                for (std::size_t index = 0; index <= last; ++index) {
                    if (reader.boolean()) {
                        path.add(index, static_cast<std::int64_t>(reader.varint32()) + 1,
                                 operation_offset);
                    }
                }
                const std::uint32_t count = reader.ubitvar();
                for (std::uint32_t index = 0; index < count; ++index) {
                    path.push(read_field_delta(), operation_offset);
                }
                break;
            }
            case 27:
                path.pop(1, operation_offset);
                path.add(path.last(), 1, operation_offset);
                break;
            case 28:
                path.pop(1, operation_offset);
                path.add(path.last(), read_field_delta() + 1, operation_offset);
                break;
            case 29:
                path.pop(static_cast<std::uint32_t>(path.last()), operation_offset);
                path.add(0, 1, operation_offset);
                break;
            case 30:
                path.pop(static_cast<std::uint32_t>(path.last()), operation_offset);
                path.add(0, read_field_delta() + 1, operation_offset);
                break;
            case 31:
                path.pop(static_cast<std::uint32_t>(path.last()), operation_offset);
                path.add(0, static_cast<std::int64_t>(reader.bits(3)) + 1, operation_offset);
                break;
            case 32:
                path.pop(static_cast<std::uint32_t>(path.last()), operation_offset);
                path.add(0, static_cast<std::int64_t>(reader.bits(6)) + 1, operation_offset);
                break;
            case 33:
                path.pop(reader.ubitvar_field_path(), operation_offset);
                path.add(path.last(), 1, operation_offset);
                break;
            case 34:
                path.pop(reader.ubitvar_field_path(), operation_offset);
                path.add(path.last(), reader.varint32(), operation_offset);
                break;
            case 35: {
                path.pop(reader.ubitvar_field_path(), operation_offset);
                const std::size_t last = path.last();
                for (std::size_t index = 0; index <= last; ++index) {
                    if (reader.boolean()) path.add(index, reader.varint32(), operation_offset);
                }
                break;
            }
            case 36: {
                const std::size_t last = path.last();
                for (std::size_t index = 0; index <= last; ++index) {
                    if (reader.boolean()) path.add(index, reader.varint32(), operation_offset);
                }
                break;
            }
            case 37:
                if (path.last() == 0) {
                    throw DecodeError("field-path penultimate component is missing",
                                      operation_offset);
                }
                path.add(path.last() - 1, 1, operation_offset);
                break;
            case 38: {
                const std::size_t last = path.last();
                for (std::size_t index = 0; index <= last; ++index) {
                    if (reader.boolean()) {
                        path.add(index, static_cast<std::int64_t>(reader.bits(4)) - 7,
                                 operation_offset);
                    }
                }
                break;
            }
            case 39:
                scan.bits_consumed = reader.position();
                return scan;
            default:
                throw DecodeError("unknown field-path operation", operation_offset);
        }
        if (scan.paths.size() >= max_paths) {
            throw DecodeError("field-path count exceeds limit", operation_offset);
        }
        scan.paths.push_back(path.snapshot());
    }
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
        } else if (type == 40) {  // svc_ServerInfo
            scan.server_max_classes = integer_field(fields, 11);
            scan.server_tick_interval = float_field(fields, 13);
            scan.server_game_directory = text_field(fields, 14);
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
            if (text_field(fields, 1) == "instancebaseline") {
                if (const auto entries = integer_field(fields, 2)) {
                    scan.instancebaseline_declared_entries += *entries;
                }
                if (const ProtoField* data = first(fields, 7, WireType::LengthDelimited)) {
                    scan.instancebaseline_encoded_bytes += data->bytes.size;
                }
                if (const auto compressed = integer_field(fields, 9)) {
                    scan.instancebaseline_compressed = *compressed != 0;
                }
                if (const auto varints = integer_field(fields, 10)) {
                    scan.instancebaseline_varint_bit_counts = *varints != 0;
                }
                const ProtoField* data = first(fields, 7, WireType::LengthDelimited);
                if (data != nullptr) {
                    std::vector<std::uint8_t> decoded;
                    ByteView table_data = data->bytes;
                    if (scan.instancebaseline_compressed) {
                        if (table_data.size >= 4 &&
                            std::memcmp(table_data.data, "LZSS", 4) == 0) {
                            decoded = decode_valve_lzss(table_data);
                            ++scan.instancebaseline_lzss_blocks;
                        } else {
                            decoded = decode_snappy(table_data);
                            ++scan.instancebaseline_snappy_blocks;
                        }
                        table_data = {decoded.data(), decoded.size()};
                    }
                    const std::uint32_t entries = static_cast<std::uint32_t>(
                        integer_field(fields, 2).value_or(0)
                    );
                    const bool fixed = integer_field(fields, 3).value_or(0) != 0;
                    const std::uint32_t fixed_bits = static_cast<std::uint32_t>(
                        integer_field(fields, 5).value_or(0)
                    );
                    const std::uint32_t table_flags = static_cast<std::uint32_t>(
                        integer_field(fields, 6).value_or(0)
                    );
                    const auto items = parse_string_table(
                        table_data, entries, fixed, fixed_bits, table_flags,
                        scan.instancebaseline_varint_bit_counts
                    );
                    scan.instancebaseline_item_count += items.size();
                    for (const auto& item : items) {
                        scan.instancebaseline_value_bytes += item.value.size();
                        const bool numeric = !item.key.empty() && std::all_of(
                            item.key.begin(), item.key.end(), [](unsigned char character) {
                                return character >= '0' && character <= '9';
                            }
                        );
                        if (!numeric) continue;
                        try {
                            const auto id = std::stoul(item.key);
                            if (id <= std::numeric_limits<std::uint32_t>::max()) {
                                const auto class_id = static_cast<std::uint32_t>(id);
                                scan.instancebaseline_class_ids.push_back(class_id);
                                scan.instancebaselines.emplace_back(class_id, item.value);
                            }
                        } catch (const std::exception&) {
                            // Item remains counted but cannot be linked to a class.
                        }
                    }
                }
            }
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

FieldType parse_field_type(std::string type_name) {
    FieldType result;
    result.original = trim_copy(std::move(type_name));
    std::string working = result.original;

    if (!working.empty() && working.back() == ']') {
        const auto open = working.find_last_of('[');
        if (open == std::string::npos) throw DecodeError("invalid field array type", 0);
        result.array_token = trim_copy(working.substr(open + 1, working.size() - open - 2));
        working = trim_copy(working.substr(0, open));
        if (result.array_token == "MAX_ITEM_STOCKS") {
            result.count = 8;
        } else if (result.array_token == "MAX_ABILITY_DRAFT_ABILITIES") {
            result.count = 48;
        } else if (!result.array_token.empty() && std::all_of(
                       result.array_token.begin(), result.array_token.end(),
                       [](unsigned char character) { return character >= '0' && character <= '9'; })) {
            result.count = static_cast<std::size_t>(std::stoull(result.array_token));
        } else if (!result.array_token.empty()) {
            // Valve occasionally leaves a symbolic bound unresolved in the
            // flattened schema; keep Manta's conservative cap.
            result.count = 1024;
        }
    }

    if (!working.empty() && working.back() == '*') {
        result.pointer = true;
        working = trim_copy(working.substr(0, working.size() - 1));
    }

    const auto generic_open = working.find('<');
    if (generic_open == std::string::npos) {
        result.base_type = trim_copy(working);
    } else {
        if (working.back() != '>') throw DecodeError("invalid generic field type", 0);
        result.base_type = trim_copy(working.substr(0, generic_open));
        result.generic_type = trim_copy(
            working.substr(generic_open + 1, working.size() - generic_open - 2)
        );
    }
    if (result.base_type.empty()) throw DecodeError("empty field base type", 0);
    return result;
}

SerializerCatalog parse_flattened_serializer(ByteView protobuf_message) {
    SerializerCatalog catalog;
    const auto root = group_fields(protobuf_message);

    if (const auto found = root.find(2); found != root.end()) {
        catalog.symbols.reserve(found->second.size());
        for (const auto& field : found->second) {
            if (field.wire_type != WireType::LengthDelimited) continue;
            catalog.symbols.emplace_back(
                reinterpret_cast<const char*>(field.bytes.data), field.bytes.size
            );
        }
    }

    if (const auto found = root.find(3); found != root.end()) {
        catalog.fields.reserve(found->second.size());
        for (const auto& outer : found->second) {
            if (outer.wire_type != WireType::LengthDelimited) continue;
            const auto fields = group_fields(outer.bytes);
            SerializerField field;
            field.variable_type = resolve_symbol(
                catalog.symbols, symbol_index(fields, 1), catalog.unresolved_symbol_references
            );
            field.variable_name = resolve_symbol(
                catalog.symbols, symbol_index(fields, 2), catalog.unresolved_symbol_references
            );
            field.bit_count = symbol_index(fields, 3);
            field.low_value = float_field(fields, 4);
            field.high_value = float_field(fields, 5);
            field.encode_flags = symbol_index(fields, 6);
            field.serializer_name = resolve_symbol(
                catalog.symbols, symbol_index(fields, 7), catalog.unresolved_symbol_references
            );
            field.send_node = resolve_symbol(
                catalog.symbols, symbol_index(fields, 9), catalog.unresolved_symbol_references
            );
            field.encoder = resolve_symbol(
                catalog.symbols, symbol_index(fields, 10), catalog.unresolved_symbol_references
            );
            field.variable_serializer = resolve_symbol(
                catalog.symbols, symbol_index(fields, 12), catalog.unresolved_symbol_references
            );
            catalog.fields.push_back(std::move(field));
        }
    }

    if (const auto found = root.find(1); found != root.end()) {
        catalog.serializers.reserve(found->second.size());
        for (const auto& outer : found->second) {
            if (outer.wire_type != WireType::LengthDelimited) continue;
            const auto fields = group_fields(outer.bytes);
            SerializerDefinition serializer;
            serializer.name = resolve_symbol(
                catalog.symbols, symbol_index(fields, 1), catalog.unresolved_symbol_references
            );
            if (const auto version = integer_field(fields, 2)) {
                serializer.version = static_cast<std::int32_t>(*version);
            }
            serializer.field_indices = repeated_int32(fields, 3);
            for (const auto index : serializer.field_indices) {
                if (index >= catalog.fields.size()) ++catalog.invalid_field_references;
            }
            const std::size_t index = catalog.serializers.size();
            if (!serializer.name.empty()) catalog.serializer_by_name[serializer.name] = index;
            catalog.serializers.push_back(std::move(serializer));
        }
    }

    for (auto& field : catalog.fields) {
        field.parsed_type = parse_field_type(field.variable_type);
        const std::string& link_name = field.serializer_name.empty()
            ? field.variable_serializer : field.serializer_name;
        if (!link_name.empty()) {
            if (catalog.serializer_by_name.count(link_name) == 0) {
                ++catalog.unresolved_serializer_links;
            } else if (field.parsed_type.pointer ||
                       pointer_table_type(field.parsed_type.base_type)) {
                field.model = FieldModel::FixedTable;
            } else {
                field.model = FieldModel::VariableTable;
            }
        } else if (field.parsed_type.count > 0 && field.parsed_type.base_type != "char") {
            field.model = FieldModel::FixedArray;
        } else if (field.parsed_type.base_type == "CUtlVector" ||
                   field.parsed_type.base_type == "CNetworkUtlVectorBase") {
            field.model = FieldModel::VariableArray;
        } else {
            field.model = FieldModel::Simple;
        }
    }
    return catalog;
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
    std::optional<SerializerCatalog> serializer_catalog;
    std::unordered_map<std::uint32_t, std::string> server_classes;
    std::unordered_set<std::uint32_t> instancebaseline_class_ids;
    std::unordered_map<std::uint32_t, std::vector<std::uint8_t>> instancebaselines;
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
        if (command == kDemSendTables) {
            const ProtoField* data = first(fields, 1, WireType::LengthDelimited);
            if (data == nullptr) throw DecodeError("DEM_SendTables has no data", frame_offset);
            Cursor send_tables(data->bytes);
            const std::uint32_t payload_size = send_tables.varuint32("send-table payload size");
            const ByteView flattened = send_tables.bytes(payload_size, "send-table payload");
            if (!send_tables.done()) {
                throw DecodeError("trailing bytes after send-table payload", frame_offset);
            }
            serializer_catalog = parse_flattened_serializer(flattened);
            report.send_table_serializer_count = serializer_catalog->serializers.size();
            report.send_table_field_count = serializer_catalog->fields.size();
            report.send_table_symbol_count = serializer_catalog->symbols.size();
            report.unresolved_serializer_symbols =
                serializer_catalog->unresolved_symbol_references;
            report.invalid_serializer_field_references =
                serializer_catalog->invalid_field_references;
            report.unresolved_nested_serializer_links =
                serializer_catalog->unresolved_serializer_links;
            for (const auto& field : serializer_catalog->fields) {
                switch (field.model) {
                    case FieldModel::Simple: ++report.simple_serializer_fields; break;
                    case FieldModel::FixedArray: ++report.fixed_array_serializer_fields; break;
                    case FieldModel::FixedTable: ++report.fixed_table_serializer_fields; break;
                    case FieldModel::VariableArray: ++report.variable_array_serializer_fields; break;
                    case FieldModel::VariableTable: ++report.variable_table_serializer_fields; break;
                }
            }
            report.hero_serializer_count = static_cast<std::uint64_t>(std::count_if(
                serializer_catalog->serializers.begin(), serializer_catalog->serializers.end(),
                [](const SerializerDefinition& serializer) {
                    return serializer.name.find("CDOTA_Unit_Hero") != std::string::npos;
                }
            ));
        }
        if (command == kDemClassInfo) {
            const auto found = fields.find(1);
            if (found != fields.end()) {
                report.class_count += found->second.size();
                for (const auto& class_field : found->second) {
                    if (class_field.wire_type != WireType::LengthDelimited) continue;
                    const auto class_fields = group_fields(class_field.bytes);
                    if (const auto class_id = integer_field(class_fields, 1)) {
                        if (*class_id <= std::numeric_limits<std::uint32_t>::max()) {
                            server_classes[static_cast<std::uint32_t>(*class_id)] =
                                text_field(class_fields, 2);
                        }
                    }
                }
            }
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
                if (network.server_max_classes) {
                    report.server_max_classes = network.server_max_classes;
                }
                if (network.server_tick_interval) {
                    report.server_tick_interval = network.server_tick_interval;
                }
                if (!network.server_game_directory.empty()) {
                    report.server_game_directory = network.server_game_directory;
                }
                report.instancebaseline_declared_entries +=
                    network.instancebaseline_declared_entries;
                report.instancebaseline_encoded_bytes +=
                    network.instancebaseline_encoded_bytes;
                report.instancebaseline_compressed =
                    report.instancebaseline_compressed || network.instancebaseline_compressed;
                report.instancebaseline_varint_bit_counts =
                    report.instancebaseline_varint_bit_counts ||
                    network.instancebaseline_varint_bit_counts;
                report.instancebaseline_item_count += network.instancebaseline_item_count;
                report.instancebaseline_value_bytes += network.instancebaseline_value_bytes;
                report.instancebaseline_lzss_blocks += network.instancebaseline_lzss_blocks;
                report.instancebaseline_snappy_blocks += network.instancebaseline_snappy_blocks;
                instancebaseline_class_ids.insert(
                    network.instancebaseline_class_ids.begin(),
                    network.instancebaseline_class_ids.end()
                );
                for (const auto& [class_id, value] : network.instancebaselines) {
                    instancebaselines[class_id] = value;
                }
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
    if (serializer_catalog) {
        for (const auto& [class_id, class_name] : server_classes) {
            (void)class_id;
            if (serializer_catalog->serializer_by_name.count(class_name) != 0) {
                ++report.linked_server_classes;
            } else {
                ++report.unlinked_server_classes;
            }
        }
    } else {
        report.unlinked_server_classes = server_classes.size();
    }
    for (const auto class_id : instancebaseline_class_ids) {
        if (server_classes.count(class_id) != 0) {
            ++report.instancebaseline_linked_classes;
        } else {
            ++report.instancebaseline_unlinked_classes;
        }
    }
    for (const auto& [class_id, baseline] : instancebaselines) {
        // Source 2 may publish an explicit empty class baseline. It carries no
        // field-path terminator and semantically means "all defaults".
        if (baseline.empty()) continue;
        FieldPathScan field_paths;
        try {
            field_paths = scan_field_paths({baseline.data(), baseline.size()});
        } catch (const DecodeError& error) {
            throw DecodeError("baseline field-path decode failed for class " +
                              std::to_string(class_id) + ": " + error.what(),
                              error.offset());
        }
        report.baseline_field_path_count += field_paths.paths.size();
        report.baseline_field_path_bits += field_paths.bits_consumed;
        for (const auto& path : field_paths.paths) {
            report.baseline_max_field_path_depth = std::max<std::uint64_t>(
                report.baseline_max_field_path_depth, path.depth
            );
        }

        if (!serializer_catalog) continue;
        const auto class_found = server_classes.find(class_id);
        if (class_found == server_classes.end()) continue;
        const auto serializer_found =
            serializer_catalog->serializer_by_name.find(class_found->second);
        if (serializer_found == serializer_catalog->serializer_by_name.end()) continue;
        const auto& serializer = serializer_catalog->serializers[serializer_found->second];
        for (const auto& path : field_paths.paths) {
            if (path.depth == 0 || path.components[0] < 0 ||
                static_cast<std::size_t>(path.components[0]) >=
                    serializer.field_indices.size()) {
                ++report.baseline_invalid_root_paths;
            }
        }
    }
    return report;
}

std::string report_json(const ScanReport& report) {
    std::ostringstream out;
    out << '{'
        << "\"schema_version\":1,"
        << "\"engine\":\"dota2replay-cpp\","
        << "\"engine_version\":\"0.2.0\","
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
        << "\"server_max_classes\":";
    optional_json(out, report.server_max_classes);
    out << ",\"server_tick_interval\":";
    optional_json(out, report.server_tick_interval);
    out << ",\"server_game_directory\":\""
        << json_escape(report.server_game_directory) << "\","
        << "\"instancebaseline_declared_entries\":"
        << report.instancebaseline_declared_entries << ','
        << "\"instancebaseline_encoded_bytes\":"
        << report.instancebaseline_encoded_bytes << ','
        << "\"instancebaseline_compressed\":"
        << (report.instancebaseline_compressed ? "true" : "false") << ','
        << "\"instancebaseline_varint_bit_counts\":"
        << (report.instancebaseline_varint_bit_counts ? "true" : "false") << ','
        << "\"instancebaseline_item_count\":"
        << report.instancebaseline_item_count << ','
        << "\"instancebaseline_value_bytes\":"
        << report.instancebaseline_value_bytes << ','
        << "\"instancebaseline_lzss_blocks\":"
        << report.instancebaseline_lzss_blocks << ','
        << "\"instancebaseline_snappy_blocks\":"
        << report.instancebaseline_snappy_blocks << ','
        << "\"instancebaseline_linked_classes\":"
        << report.instancebaseline_linked_classes << ','
        << "\"instancebaseline_unlinked_classes\":"
        << report.instancebaseline_unlinked_classes << ','
        << "\"baseline_field_path_count\":"
        << report.baseline_field_path_count << ','
        << "\"baseline_field_path_bits\":"
        << report.baseline_field_path_bits << ','
        << "\"baseline_invalid_root_paths\":"
        << report.baseline_invalid_root_paths << ','
        << "\"baseline_max_field_path_depth\":"
        << report.baseline_max_field_path_depth << ','
        << "\"send_table_serializer_count\":" << report.send_table_serializer_count << ','
        << "\"send_table_field_count\":" << report.send_table_field_count << ','
        << "\"send_table_symbol_count\":" << report.send_table_symbol_count << ','
        << "\"unresolved_serializer_symbols\":" << report.unresolved_serializer_symbols << ','
        << "\"invalid_serializer_field_references\":"
        << report.invalid_serializer_field_references << ','
        << "\"linked_server_classes\":" << report.linked_server_classes << ','
        << "\"unlinked_server_classes\":" << report.unlinked_server_classes << ','
        << "\"hero_serializer_count\":" << report.hero_serializer_count << ','
        << "\"simple_serializer_fields\":" << report.simple_serializer_fields << ','
        << "\"fixed_array_serializer_fields\":"
        << report.fixed_array_serializer_fields << ','
        << "\"fixed_table_serializer_fields\":"
        << report.fixed_table_serializer_fields << ','
        << "\"variable_array_serializer_fields\":"
        << report.variable_array_serializer_fields << ','
        << "\"variable_table_serializer_fields\":"
        << report.variable_table_serializer_fields << ','
        << "\"unresolved_nested_serializer_links\":"
        << report.unresolved_nested_serializer_links << ','
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
