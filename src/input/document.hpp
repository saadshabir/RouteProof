#pragma once

#include <yaml-cpp/mark.h>
#include <yaml-cpp/node/type.h>

#include <deque>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "routeproof/input/scenario_loader.hpp"

namespace routeproof::input::detail {

struct NodeData;

// Both parsers build the same typed, source-marked tree. Alias edges borrow
// arena nodes; cycle checks happen before an edge is attached.
class Node {
public:
    Node() = default;
    explicit Node(NodeData* data) : data_(data) {}
    [[nodiscard]] bool IsDefined() const { return data_ != nullptr; }
    [[nodiscard]] bool IsNull() const;
    [[nodiscard]] bool IsScalar() const;
    [[nodiscard]] bool IsMap() const;
    [[nodiscard]] bool IsSequence() const;
    [[nodiscard]] YAML::Mark Mark() const;
    [[nodiscard]] const std::string& Tag() const;
    [[nodiscard]] const std::string& Scalar() const;
    [[nodiscard]] std::size_t size() const;
    [[nodiscard]] Node operator[](std::string_view key) const;
    [[nodiscard]] Node operator[](std::size_t index) const;
    [[nodiscard]] const std::vector<std::pair<Node, Node>>& members() const;

private:
    NodeData* data_{};
    friend struct Document;
};

struct NodeData {
    YAML::NodeType::value type;
    YAML::Mark mark;
    std::string tag;
    std::string scalar;
    std::vector<Node> elements;
    std::vector<std::pair<Node, Node>> members;
};

struct Document {
    std::deque<NodeData> arena;
    Node root;

    Document() = default;
    Document(const Document&) = delete;
    Document& operator=(const Document&) = delete;
    Document(Document&&) = default;
    Document& operator=(Document&&) = default;

    Node make(YAML::NodeType::value type, const YAML::Mark& mark, const std::string& tag,
              const std::string& scalar = {});
    static NodeData& data(Node node) { return *node.data_; }
};

[[nodiscard]] Document read_document(std::string_view text, const std::string& source,
                                     const InputLimits& limits);
[[nodiscard]] std::string scalar_string(Node node, const std::string& source,
                                        const std::string& field);
[[nodiscard]] bool is_decimal_integer_text(std::string_view text);

}  // namespace routeproof::input::detail
