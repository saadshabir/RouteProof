#include "document.hpp"

#include <yaml-cpp/eventhandler.h>
#include <yaml-cpp/yaml.h>

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <nlohmann/json.hpp>
#include <set>
#include <sstream>

namespace routeproof::input::detail {

bool Node::IsNull() const {
    return data_ && data_->type == YAML::NodeType::Null;
}
bool Node::IsScalar() const {
    return data_ && data_->type == YAML::NodeType::Scalar;
}
bool Node::IsMap() const {
    return data_ && data_->type == YAML::NodeType::Map;
}
bool Node::IsSequence() const {
    return data_ && data_->type == YAML::NodeType::Sequence;
}
YAML::Mark Node::Mark() const {
    return data_ ? data_->mark : YAML::Mark::null_mark();
}
const std::string& Node::Tag() const {
    return data_->tag;
}
const std::string& Node::Scalar() const {
    return data_->scalar;
}
std::size_t Node::size() const {
    if (IsSequence()) {
        return data_->elements.size();
    }
    if (IsMap()) {
        return data_->members.size();
    }
    return 0U;
}
Node Node::operator[](const std::string_view key) const {
    if (IsMap()) {
        for (const auto& member : data_->members) {
            if (member.first.Scalar() == key) {
                return member.second;
            }
        }
    }
    return {};
}
Node Node::operator[](const std::size_t index) const {
    return data_->elements.at(index);
}
const std::vector<std::pair<Node, Node>>& Node::members() const {
    return data_->members;
}
Node Document::make(const YAML::NodeType::value type, const YAML::Mark& mark,
                    const std::string& tag, const std::string& scalar) {
    arena.push_back(NodeData{type, mark, tag, scalar, {}, {}});
    return Node{&arena.back()};
}

namespace {

[[noreturn]] void fail(const std::string& source, const YAML::Mark& mark,
                       const std::string& message) {
    throw InputError(source, mark.is_null() ? 0U : mark.line + 1U,
                     mark.is_null() ? 0U : mark.column + 1U, message);
}

bool ascii_iequals(const std::string_view left, const std::string_view right) {
    if (left.size() != right.size()) {
        return false;
    }
    for (std::size_t index = 0U; index < left.size(); ++index) {
        if (std::tolower(static_cast<unsigned char>(left[index])) !=
            std::tolower(static_cast<unsigned char>(right[index]))) {
            return false;
        }
    }
    return true;
}

bool looks_like_implicit_yaml_non_string(const std::string_view text) {
    if (text == "~" || ascii_iequals(text, "null") || ascii_iequals(text, "true") ||
        ascii_iequals(text, "false") || ascii_iequals(text, "yes") || ascii_iequals(text, "no") ||
        ascii_iequals(text, "on") || ascii_iequals(text, "off")) {
        return true;
    }
    if (is_decimal_integer_text(text)) {
        return true;
    }
    if (text.size() > 2U && text[0] == '0' &&
        (text[1] == 'x' || text[1] == 'X' || text[1] == 'o' || text[1] == 'O' || text[1] == 'b' ||
         text[1] == 'B')) {
        return true;
    }
    if (text.find('/') == std::string_view::npos) {
        std::string value{text};
        char* end = nullptr;
        (void)std::strtod(value.c_str(), &end);
        if (end == value.c_str() + value.size() && end != value.c_str() &&
            text.find_first_of(".eE") != std::string_view::npos) {
            return true;
        }
    }
    return false;
}

void validate_tag(const Node node, const std::string& source) {
    const std::string& tag = node.Tag();
    if (tag.empty() || tag == "?" || tag == "!") {
        return;
    }
    bool matches = false;
    if (tag == "tag:yaml.org,2002:map") {
        matches = node.IsMap();
    } else if (tag == "tag:yaml.org,2002:seq") {
        matches = node.IsSequence();
    } else if (tag == "tag:yaml.org,2002:null") {
        matches = node.IsNull();
    } else if (tag == "tag:yaml.org,2002:str" || tag == "tag:yaml.org,2002:int" ||
               tag == "tag:yaml.org,2002:bool" || tag == "tag:yaml.org,2002:float") {
        matches = node.IsScalar();
    } else {
        fail(source, node.Mark(), "unsupported YAML tag '" + tag + "'");
    }
    if (!matches) {
        fail(source, node.Mark(), "YAML tag '" + tag + "' does not match the node type");
    }
}

class BoundedBuilder final : public YAML::EventHandler {
public:
    BoundedBuilder(Document& document, const std::string& source, const InputLimits& limits)
        : document_(document), source_(source), limits_(limits) {}

    void OnDocumentStart(const YAML::Mark& mark) override {
        if (documents_++ != 0U) {
            fail(source_, mark, "exactly one YAML document is supported");
        }
    }
    void OnDocumentEnd() override {}
    void OnNull(const YAML::Mark& mark, const YAML::anchor_t anchor) override {
        attach(make(YAML::NodeType::Null, mark, {}, {}, anchor, false));
    }
    void OnScalar(const YAML::Mark& mark, const std::string& tag, const YAML::anchor_t anchor,
                  const std::string& value) override {
        attach(make(YAML::NodeType::Scalar, mark, tag, value, anchor, false));
    }
    void OnAlias(const YAML::Mark& mark, const YAML::anchor_t anchor) override {
        count_node(mark);
        if (anchor >= anchors_.size() || !anchors_[anchor].node.IsDefined()) {
            fail(source_, mark, "unresolved YAML alias");
        }
        if (anchors_[anchor].active) {
            fail(source_, mark, "recursive YAML aliases are unsupported");
        }
        attach(anchors_[anchor].node);
    }
    void OnSequenceStart(const YAML::Mark& mark, const std::string& tag,
                         const YAML::anchor_t anchor, YAML::EmitterStyle::value) override {
        start(YAML::NodeType::Sequence, mark, tag, anchor);
    }
    void OnSequenceEnd() override { finish(); }
    void OnMapStart(const YAML::Mark& mark, const std::string& tag, const YAML::anchor_t anchor,
                    YAML::EmitterStyle::value) override {
        start(YAML::NodeType::Map, mark, tag, anchor);
    }
    void OnMapEnd() override { finish(); }

private:
    struct Anchor {
        Node node;
        bool active{};
    };
    struct Frame {
        Node node;
        Node key;
        std::set<std::string> keys;
        YAML::anchor_t anchor{};
    };

    void count_node(const YAML::Mark& mark) {
        if (frames_.size() > limits_.max_nesting) {
            fail(source_, mark,
                 "input nesting exceeds the supported depth of " +
                     std::to_string(limits_.max_nesting));
        }
        if (nodes_ >= limits_.max_nodes) {
            fail(source_, mark,
                 "input exceeds the node limit of " + std::to_string(limits_.max_nodes));
        }
        ++nodes_;
    }
    Node make(const YAML::NodeType::value type, const YAML::Mark& mark, const std::string& tag,
              const std::string& value, const YAML::anchor_t anchor, const bool active) {
        count_node(mark);
        if (value.size() > limits_.max_scalar_bytes) {
            fail(source_, mark,
                 "input exceeds the scalar byte limit of " +
                     std::to_string(limits_.max_scalar_bytes));
        }
        const Node node = document_.make(type, mark, tag, value);
        validate_tag(node, source_);
        if (anchor != YAML::NullAnchor) {
            if (anchor >= anchors_.size()) {
                anchors_.resize(anchor + 1U);
            }
            anchors_[anchor] = Anchor{node, active};
        }
        return node;
    }
    void attach(const Node node) {
        if (frames_.empty()) {
            document_.root = node;
            return;
        }
        Frame& frame = frames_.back();
        NodeData& parent = Document::data(frame.node);
        if (frame.node.IsSequence()) {
            if (parent.elements.size() >= limits_.max_collection_entries) {
                collection_limit(node);
            }
            parent.elements.push_back(node);
        } else if (!frame.key.IsDefined()) {
            if (!node.IsScalar()) {
                fail(source_, node.Mark(), "mapping keys must be scalar strings");
            }
            const std::string key = scalar_string(node, source_, "mapping key");
            if (frame.keys.size() >= limits_.max_collection_entries) {
                collection_limit(node);
            }
            if (!frame.keys.insert(key).second) {
                fail(source_, node.Mark(), "duplicate mapping key '" + key + "'");
            }
            frame.key = node;
        } else {
            parent.members.emplace_back(frame.key, node);
            frame.key = {};
        }
    }
    [[noreturn]] void collection_limit(const Node node) const {
        fail(source_, node.Mark(),
             "input exceeds the collection entry limit of " +
                 std::to_string(limits_.max_collection_entries));
    }
    void start(const YAML::NodeType::value type, const YAML::Mark& mark, const std::string& tag,
               const YAML::anchor_t anchor) {
        const Node node = make(type, mark, tag, {}, anchor, true);
        attach(node);
        frames_.push_back(Frame{node, {}, {}, anchor});
    }
    void finish() {
        const YAML::anchor_t anchor = frames_.back().anchor;
        if (anchor != YAML::NullAnchor) {
            anchors_[anchor].active = false;
        }
        frames_.pop_back();
    }

    Document& document_;
    const std::string& source_;
    const InputLimits& limits_;
    std::vector<Frame> frames_;
    std::vector<Anchor> anchors_{1U};
    std::size_t nodes_{};
    std::size_t documents_{};
};

using Json = nlohmann::json;

// SAX callbacks carry decoded values but not token locations. Advance a cursor
// over the original tokens alongside the parser to retain exact source marks.
class JsonReader final : public nlohmann::json_sax<Json> {
public:
    JsonReader(const std::string_view text, BoundedBuilder& builder)
        : text_(text), builder_(builder) {
        if (text_.substr(0U, 3U) == "\xef\xbb\xbf") {
            advance();
            advance();
            advance();
        }
    }

    bool null() override {
        const Token token = take_scalar();
        builder_.OnNull(token.mark, YAML::NullAnchor);
        return true;
    }
    bool boolean(const bool value) override {
        const Token token = take_scalar();
        builder_.OnScalar(token.mark, "tag:yaml.org,2002:bool", YAML::NullAnchor,
                          value ? "true" : "false");
        return true;
    }
    bool number_integer(number_integer_t) override { return number("tag:yaml.org,2002:int"); }
    bool number_unsigned(number_unsigned_t) override { return number("tag:yaml.org,2002:int"); }
    bool number_float(number_float_t, const string_t&) override {
        return number("tag:yaml.org,2002:float");
    }
    bool string(string_t& value) override {
        const Token token = take_scalar();
        builder_.OnScalar(token.mark, "tag:yaml.org,2002:str", YAML::NullAnchor, value);
        return true;
    }
    bool binary(binary_t&) override { return false; }
    bool start_object(std::size_t) override {
        builder_.OnMapStart(take_delimiter(), "tag:yaml.org,2002:map", YAML::NullAnchor,
                            YAML::EmitterStyle::Flow);
        return true;
    }
    bool key(string_t& value) override { return string(value); }
    bool end_object() override {
        (void)take_delimiter();
        builder_.OnMapEnd();
        return true;
    }
    bool start_array(std::size_t) override {
        builder_.OnSequenceStart(take_delimiter(), "tag:yaml.org,2002:seq", YAML::NullAnchor,
                                 YAML::EmitterStyle::Flow);
        return true;
    }
    bool end_array() override {
        (void)take_delimiter();
        builder_.OnSequenceEnd();
        return true;
    }
    bool parse_error(const std::size_t position, const std::string&,
                     const nlohmann::detail::exception& error) override {
        const std::size_t offset = position == 0U ? 0U : std::min(position - 1U, text_.size());
        cursor_ = 0U;
        mark_ = {};
        while (cursor_ < offset) {
            advance();
        }
        error_mark = mark_;
        error_message = error.what();
        return false;
    }

    YAML::Mark error_mark;
    std::string error_message;

private:
    struct Token {
        YAML::Mark mark;
        std::string_view text;
    };
    void advance() {
        const char byte = text_[cursor_++];
        ++mark_.pos;
        if (byte == '\n' || (byte == '\r' && (cursor_ == text_.size() || text_[cursor_] != '\n'))) {
            ++mark_.line;
            mark_.column = 0;
        } else {
            ++mark_.column;
        }
    }
    void skip_separators() {
        while (cursor_ < text_.size() &&
               (text_[cursor_] == ' ' || text_[cursor_] == '\t' || text_[cursor_] == '\r' ||
                text_[cursor_] == '\n' || text_[cursor_] == ',' || text_[cursor_] == ':')) {
            advance();
        }
    }
    YAML::Mark take_delimiter() {
        skip_separators();
        const YAML::Mark mark = mark_;
        advance();
        return mark;
    }
    Token take_scalar() {
        skip_separators();
        const YAML::Mark mark = mark_;
        const std::size_t start = cursor_;
        if (text_[cursor_] == '"') {
            advance();
            while (cursor_ < text_.size()) {
                const char byte = text_[cursor_];
                advance();
                if (byte == '"') {
                    break;
                }
                if (byte == '\\') {
                    advance();
                }
            }
        } else {
            while (cursor_ < text_.size() && text_[cursor_] != ',' && text_[cursor_] != ']' &&
                   text_[cursor_] != '}' && text_[cursor_] != ' ' && text_[cursor_] != '\t' &&
                   text_[cursor_] != '\r' && text_[cursor_] != '\n') {
                advance();
            }
        }
        return Token{mark, text_.substr(start, cursor_ - start)};
    }
    bool number(const char* tag) {
        const Token token = take_scalar();
        builder_.OnScalar(token.mark, tag, YAML::NullAnchor, std::string(token.text));
        return true;
    }
    std::string_view text_;
    BoundedBuilder& builder_;
    std::size_t cursor_{};
    YAML::Mark mark_;
};

}  // namespace

bool is_decimal_integer_text(const std::string_view text) {
    if (text.empty()) {
        return false;
    }
    const std::size_t start = text.front() == '-' || text.front() == '+' ? 1U : 0U;
    return start != text.size() &&
           std::all_of(text.begin() + static_cast<std::ptrdiff_t>(start), text.end(),
                       [](const char byte) { return byte >= '0' && byte <= '9'; });
}

std::string scalar_string(const Node node, const std::string& source, const std::string& field) {
    if (!node.IsScalar()) {
        fail(source, node.Mark(), field + " must be a string scalar");
    }
    const std::string& tag = node.Tag();
    if (tag.rfind("tag:yaml.org,2002:", 0U) == 0U && tag != "tag:yaml.org,2002:str") {
        fail(source, node.Mark(), field + " must be a string, not a tagged YAML value");
    }
    const std::string& value = node.Scalar();
    if (tag == "?" && looks_like_implicit_yaml_non_string(value)) {
        fail(source, node.Mark(),
             field + " must be quoted when its value looks numeric or boolean");
    }
    return value;
}

Document read_document(const std::string_view text, const std::string& source,
                       const InputLimits& limits) {
    const std::string extension = std::filesystem::path(source).extension().string();
    const bool force_json = ascii_iequals(extension, ".json");
    std::string_view content = text;
    if (content.substr(0U, 3U) == "\xef\xbb\xbf") {
        content.remove_prefix(3U);
    }
    const std::size_t first = content.find_first_not_of(" \t\r\n");
    if (force_json ||
        (first != std::string_view::npos && (content[first] == '{' || content[first] == '['))) {
        Document document;
        BoundedBuilder builder{document, source, limits};
        builder.OnDocumentStart(YAML::Mark{});
        JsonReader reader{text, builder};
        if (Json::sax_parse(text.begin(), text.end(), &reader)) {
            builder.OnDocumentEnd();
            return document;
        }
        if (force_json) {
            fail(source, reader.error_mark, "invalid JSON: " + reader.error_message);
        }
        // A flow-style YAML mapping/sequence can start with a JSON delimiter.
        // Only syntax failures fall back; duplicate keys and limits never do.
    }
    Document document;
    BoundedBuilder builder{document, source, limits};
    std::istringstream stream{std::string(text)};
    try {
        YAML::Parser parser{stream};
        while (parser.HandleNextDocument(builder)) {
        }
    } catch (const YAML::Exception& error) {
        fail(source, error.mark, "invalid YAML: " + std::string(error.what()));
    }
    return document;
}

}  // namespace routeproof::input::detail
