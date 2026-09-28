#include "routeproof/input/scenario_loader.hpp"

#include <yaml-cpp/yaml.h>
#include <nlohmann/json.hpp>
#include <picosha2.h>

#include <algorithm>
#include <charconv>
#include <cctype>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <limits>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <string_view>
#include <tuple>
#include <utility>
#include <vector>

namespace routeproof::input {
namespace {

using Json = nlohmann::json;
using Node = YAML::Node;
using namespace routeproof::model;

constexpr std::uint64_t kOspfInfinity = 0x00ffffffU;
constexpr std::uint64_t kMaximumInputInteger =
    static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max());
constexpr std::size_t kMaximumNesting = 128;

std::string location_message(const std::string& source, const std::size_t line,
                             const std::size_t column,
                             const std::string& message) {
    std::ostringstream output;
    output << source;
    if (line != 0U) {
        output << ':' << line;
        if (column != 0U) {
            output << ':' << column;
        }
    }
    output << ": " << message;
    return output.str();
}

[[noreturn]] void fail(const std::string& source, const YAML::Mark& mark,
                       const std::string& message) {
    const std::size_t line = mark.is_null() ? 0U : mark.line + 1U;
    const std::size_t column = mark.is_null() ? 0U : mark.column + 1U;
    throw InputError(source, line, column, message);
}

[[noreturn]] void fail(const std::string& source, const Node& node,
                       const std::string& message) {
    fail(source, node.Mark(), message);
}

void validate_yaml_tag(const Node& node, const std::string& source) {
    const std::string tag = node.Tag();
    if (tag.empty() || tag == "?" || tag == "!") {
        return;
    }
    bool matches_kind = false;
    if (tag == "tag:yaml.org,2002:map") {
        matches_kind = node.IsMap();
    } else if (tag == "tag:yaml.org,2002:seq") {
        matches_kind = node.IsSequence();
    } else if (tag == "tag:yaml.org,2002:null") {
        matches_kind = node.IsNull();
    } else if (tag == "tag:yaml.org,2002:str" ||
               tag == "tag:yaml.org,2002:int" ||
               tag == "tag:yaml.org,2002:bool" ||
               tag == "tag:yaml.org,2002:float") {
        matches_kind = node.IsScalar();
    } else {
        fail(source, node, "unsupported YAML tag '" + tag + "'");
    }
    if (!matches_kind) {
        fail(source, node, "YAML tag '" + tag + "' does not match the node type");
    }
}

std::string scalar_string(const Node& node, const std::string& source,
                          const std::string& field);

void validate_yaml_tree(const Node& node, const std::string& source,
                        std::vector<Node>& ancestors,
                        std::vector<Node>& visited, const std::size_t depth) {
    if (!node.IsDefined()) {
        return;
    }
    if (depth > kMaximumNesting) {
        fail(source, node, "YAML nesting exceeds the supported depth of " +
                               std::to_string(kMaximumNesting));
    }
    validate_yaml_tag(node, source);
    if (!node.IsMap() && !node.IsSequence()) {
        return;
    }
    for (const Node& ancestor : ancestors) {
        if (node.is(ancestor)) {
            fail(source, node, "recursive YAML aliases are unsupported");
        }
    }
    for (const Node& prior : visited) {
        if (node.is(prior)) {
            return;
        }
    }
    visited.push_back(node);
    ancestors.push_back(node);

    if (node.IsMap()) {
        std::set<std::string> keys;
        for (const auto& entry : node) {
            const Node key = entry.first;
            if (!key.IsScalar()) {
                fail(source, key, "mapping keys must be scalar strings");
            }
            const std::string key_text = scalar_string(key, source, "mapping key");
            if (!keys.insert(key_text).second) {
                fail(source, key, "duplicate YAML key '" + key_text + "'");
            }
            validate_yaml_tree(key, source, ancestors, visited, depth + 1U);
            validate_yaml_tree(entry.second, source, ancestors, visited, depth + 1U);
        }
    } else {
        for (const Node& item : node) {
            validate_yaml_tree(item, source, ancestors, visited, depth + 1U);
        }
    }
    ancestors.pop_back();
}

bool ascii_iequals(const std::string_view left, const std::string_view right) {
    if (left.size() != right.size()) {
        return false;
    }
    for (std::size_t index = 0; index < left.size(); ++index) {
        if (std::tolower(static_cast<unsigned char>(left[index])) !=
            std::tolower(static_cast<unsigned char>(right[index]))) {
            return false;
        }
    }
    return true;
}

bool is_decimal_integer_text(const std::string_view text) {
    if (text.empty()) {
        return false;
    }
    std::size_t index = text.front() == '-' || text.front() == '+' ? 1U : 0U;
    if (index == text.size()) {
        return false;
    }
    for (; index < text.size(); ++index) {
        if (text[index] < '0' || text[index] > '9') {
            return false;
        }
    }
    return true;
}

bool utf8_codepoint_count(const std::string_view text, std::size_t& count) {
    count = 0U;
    for (std::size_t index = 0U; index < text.size();) {
        const auto first = static_cast<unsigned char>(text[index]);
        std::size_t width = 0U;
        if (first <= 0x7fU) {
            width = 1U;
        } else if (first >= 0xc2U && first <= 0xdfU) {
            width = 2U;
        } else if (first >= 0xe0U && first <= 0xefU) {
            width = 3U;
        } else if (first >= 0xf0U && first <= 0xf4U) {
            width = 4U;
        } else {
            return false;
        }
        if (index + width > text.size()) {
            return false;
        }
        for (std::size_t offset = 1U; offset < width; ++offset) {
            const auto continuation = static_cast<unsigned char>(text[index + offset]);
            if (continuation < 0x80U || continuation > 0xbfU) {
                return false;
            }
        }
        if (width >= 3U) {
            const auto second = static_cast<unsigned char>(text[index + 1U]);
            if ((first == 0xe0U && second < 0xa0U) ||
                (first == 0xedU && second > 0x9fU) ||
                (first == 0xf0U && second < 0x90U) ||
                (first == 0xf4U && second > 0x8fU)) {
                return false;
            }
        }
        index += width;
        ++count;
    }
    return true;
}

bool looks_like_implicit_yaml_non_string(const std::string_view text) {
    if (text == "~" || ascii_iequals(text, "null") ||
        ascii_iequals(text, "true") || ascii_iequals(text, "false") ||
        ascii_iequals(text, "yes") || ascii_iequals(text, "no") ||
        ascii_iequals(text, "on") || ascii_iequals(text, "off")) {
        return true;
    }
    if (is_decimal_integer_text(text)) {
        return true;
    }
    if (text.size() > 2U && text[0] == '0' &&
        (text[1] == 'x' || text[1] == 'X' || text[1] == 'o' || text[1] == 'O' ||
         text[1] == 'b' || text[1] == 'B')) {
        return true;
    }
    if (text.find('/') == std::string_view::npos) {
        std::string value{text};
        char* parsed_end = nullptr;
        (void)std::strtod(value.c_str(), &parsed_end);
        if (parsed_end == value.c_str() + value.size() && parsed_end != value.c_str() &&
            text.find_first_of(".eE") != std::string_view::npos) {
            return true;
        }
    }
    return false;
}

std::string scalar_string(const Node& node, const std::string& source,
                          const std::string& field) {
    if (!node.IsScalar()) {
        fail(source, node, field + " must be a string scalar");
    }
    const std::string tag = node.Tag();
    constexpr std::string_view string_tag = "tag:yaml.org,2002:str";
    if (tag.rfind("tag:yaml.org,2002:", 0U) == 0U && tag != string_tag) {
        fail(source, node, field + " must be a string, not a tagged YAML value");
    }
    const std::string value = node.Scalar();
    if (tag == "?" && looks_like_implicit_yaml_non_string(value)) {
        fail(source, node, field + " must be quoted when its value looks numeric or boolean");
    }
    return value;
}

void require_map(const Node& node, const std::string& source,
                 const std::string& field) {
    if (!node.IsMap()) {
        fail(source, node, field + " must be a mapping");
    }
}

void require_sequence(const Node& node, const std::string& source,
                      const std::string& field) {
    if (!node.IsSequence()) {
        fail(source, node, field + " must be a sequence");
    }
}

void check_fields(const Node& node, const std::string& source,
                  const std::string& path,
                  const std::vector<std::string_view>& allowed,
                  const std::vector<std::string_view>& required) {
    require_map(node, source, path);
    for (const auto& entry : node) {
        const std::string key = entry.first.Scalar();
        const bool known = std::find(allowed.begin(), allowed.end(), key) != allowed.end();
        if (!known) {
            fail(source, entry.first, path + " contains unsupported field '" + key + "'");
        }
    }
    for (const std::string_view field : required) {
        if (!node[std::string(field)].IsDefined()) {
            fail(source, node, path + " is missing required field '" +
                                   std::string(field) + "'");
        }
    }
}

Node field(const Node& node, const std::string_view name) {
    return node[std::string(name)];
}

std::uint64_t unsigned_integer(const Node& node, const std::string& source,
                              const std::string& field_name,
                              const std::uint64_t minimum,
                              const std::uint64_t maximum) {
    if (!node.IsScalar()) {
        fail(source, node, field_name + " must be an integer scalar");
    }
    const std::string tag = node.Tag();
    constexpr std::string_view integer_tag = "tag:yaml.org,2002:int";
    if (tag == "!" ||
        (tag.rfind("tag:yaml.org,2002:", 0U) == 0U && tag != integer_tag)) {
        fail(source, node, field_name + " must be an integer");
    }
    const std::string value = node.Scalar();
    if (!is_decimal_integer_text(value) || value.front() == '-' || value.front() == '+') {
        fail(source, node, field_name + " must be a nonnegative base-10 integer");
    }
    if (value.size() > 1U && value.front() == '0') {
        fail(source, node, field_name + " must use canonical decimal notation");
    }
    std::uint64_t result = 0U;
    const auto [end, error] = std::from_chars(value.data(), value.data() + value.size(), result);
    if (error != std::errc{} || end != value.data() + value.size()) {
        fail(source, node, field_name + " is outside the supported integer range");
    }
    if (result < minimum || result > maximum) {
        fail(source, node, field_name + " must be in " + std::to_string(minimum) +
                               ".." + std::to_string(maximum));
    }
    return result;
}

void validate_id(const std::string& value, const Node& node,
                 const std::string& source, const std::string& field_name) {
    if (value.empty() || value.size() > 64U ||
        !((value.front() >= 'A' && value.front() <= 'Z') ||
          (value.front() >= 'a' && value.front() <= 'z') ||
          (value.front() >= '0' && value.front() <= '9'))) {
        fail(source, node, field_name + " must match [A-Za-z0-9][A-Za-z0-9_.-]* "
                               "and contain at most 64 characters");
    }
    for (const char character : value) {
        const bool valid = (character >= 'A' && character <= 'Z') ||
                           (character >= 'a' && character <= 'z') ||
                           (character >= '0' && character <= '9') ||
                           character == '_' || character == '.' || character == '-';
        if (!valid) {
            fail(source, node, field_name + " must match [A-Za-z0-9][A-Za-z0-9_.-]* "
                                   "and contain at most 64 characters");
        }
    }
}

IPv4Address parse_ipv4(const std::string& text, const Node& node,
                       const std::string& source, const std::string& field_name) {
    std::uint32_t address = 0U;
    std::size_t start = 0U;
    for (std::size_t octet_index = 0U; octet_index < 4U; ++octet_index) {
        const std::size_t end = octet_index == 3U ? text.size() : text.find('.', start);
        if (end == std::string::npos || end == start) {
            fail(source, node, field_name + " must be a canonical dotted-decimal IPv4 address");
        }
        const std::string_view octet{text.data() + start, end - start};
        if ((octet.size() > 1U && octet.front() == '0') ||
            !std::all_of(octet.begin(), octet.end(), [](const char digit) {
                return digit >= '0' && digit <= '9';
            })) {
            fail(source, node, field_name + " must use canonical dotted-decimal IPv4 notation");
        }
        unsigned int value = 0U;
        const auto [parsed_end, error] =
            std::from_chars(octet.data(), octet.data() + octet.size(), value);
        if (error != std::errc{} || parsed_end != octet.data() + octet.size() || value > 255U) {
            fail(source, node, field_name + " contains an IPv4 octet outside 0..255");
        }
        address = static_cast<std::uint32_t>((address << 8U) | value);
        start = end + 1U;
    }
    if (start != text.size() + 1U) {
        fail(source, node, field_name + " must contain exactly four IPv4 octets");
    }
    return IPv4Address{address};
}

IPv4Prefix parse_prefix(const std::string& text, const Node& node,
                        const std::string& source, const std::string& field_name) {
    const std::size_t slash = text.find('/');
    if (slash == std::string::npos || text.find('/', slash + 1U) != std::string::npos) {
        fail(source, node, field_name + " must be an IPv4 network in address/prefix-length form");
    }
    const std::string address_text = text.substr(0U, slash);
    const std::string length_text = text.substr(slash + 1U);
    const IPv4Address address = parse_ipv4(address_text, node, source, field_name);
    if (length_text.empty() ||
        !std::all_of(length_text.begin(), length_text.end(), [](const char digit) {
            return digit >= '0' && digit <= '9';
        }) || (length_text.size() > 1U && length_text.front() == '0')) {
        fail(source, node, field_name + " prefix length must be canonical decimal 1..32");
    }
    unsigned int length = 0U;
    const auto [end, error] = std::from_chars(length_text.data(),
                                               length_text.data() + length_text.size(), length);
    if (error != std::errc{} || end != length_text.data() + length_text.size() || length > 32U) {
        fail(source, node, field_name + " prefix length must be in 1..32");
    }
    if (length == 0U) {
        fail(source, node, field_name + " default route '" + text +
                               "' is unsupported in ospf_spf_v1");
    }
    const std::uint32_t mask = 0xffffffffU << (32U - length);
    if ((address.value & mask) != address.value) {
        fail(source, node, field_name + " must name the canonical network address");
    }
    return IPv4Prefix{address, static_cast<std::uint8_t>(length)};
}

bool read_initial_state(const Node& node, const std::string& source,
                        const std::string& field_name) {
    if (!node.IsDefined()) {
        return true;
    }
    const std::string state = scalar_string(node, source, field_name);
    if (state == "up") {
        return true;
    }
    if (state == "down") {
        return false;
    }
    fail(source, node, field_name + " must be 'up' or 'down'");
}

struct RawLink {
    std::string id;
    std::string a;
    std::string b;
    std::uint16_t cost_ab{};
    std::uint16_t cost_ba{};
    bool initially_up{true};
};

struct RawEvent {
    Event event;
    std::string target;
    YAML::Mark mark;
};

Json normalized_representation(const Scenario& scenario) {
    Json routers = Json::array();
    for (const Router& router : scenario.routers) {
        routers.push_back(Json{{"id", router.id},
                               {"initial_state", router.initially_available ? "up" : "down"},
                               {"router_id", IPv4Address{router.router_id}.to_string()}});
    }

    Json links = Json::array();
    for (const Link& link : scenario.links) {
        links.push_back(Json{{"a", scenario.routers[link.a].id},
                             {"b", scenario.routers[link.b].id},
                             {"cost_ab", link.cost_ab},
                             {"cost_ba", link.cost_ba},
                             {"id", link.id},
                             {"initial_state", link.initially_admin_up ? "up" : "down"}});
    }

    Json prefixes = Json::array();
    for (const Prefix& prefix : scenario.prefixes) {
        prefixes.push_back(Json{{"origin", scenario.routers[prefix.origin].id},
                                {"prefix", prefix.network.to_string()},
                                {"stub_cost", prefix.stub_cost}});
    }

    Json events = Json::array();
    for (const Event& event : scenario.events) {
        Json item{{"at_ns", event.at_ns},
                  {"id", event.id},
                  {"seq", event.sequence},
                  {"type", event_type_name(event.type)}};
        if (event.type == EventType::link_down || event.type == EventType::link_up) {
            item["link"] = scenario.links[event.target_index].id;
        } else {
            item["router"] = scenario.routers[event.target_index].id;
        }
        events.push_back(std::move(item));
    }

    Json assertions = Json::array();
    for (const ReachabilityAssertion& assertion : scenario.assertions) {
        assertions.push_back(Json{{"destination", assertion.destination.to_string()},
                                  {"id", assertion.id},
                                  {"quantifier", "all"},
                                  {"scope", "every_snapshot"},
                                  {"source", scenario.routers[assertion.source].id},
                                  {"type", "must_reach"}});
    }

    return Json{{"assertions", std::move(assertions)},
                {"events", std::move(events)},
                {"links", std::move(links)},
                {"model", "ospf_spf_v1"},
                {"name", scenario.name},
                {"prefixes", std::move(prefixes)},
                {"routers", std::move(routers)},
                {"schema_version", 1}};
}

Scenario parse_document(const Node& root, const std::string& source) {
    check_fields(root, source, "scenario",
                 {"schema_version", "name", "model", "routers", "links", "prefixes",
                  "events", "assertions"},
                 {"schema_version", "name", "model", "routers", "links", "prefixes",
                  "events", "assertions"});

    const Node schema_node = field(root, "schema_version");
    if (unsigned_integer(schema_node, source, "schema_version", 1U, 1U) != 1U) {
        fail(source, schema_node, "only scenario schema_version 1 is supported");
    }
    const Node model_node = field(root, "model");
    if (scalar_string(model_node, source, "model") != "ospf_spf_v1") {
        fail(source, model_node, "only model 'ospf_spf_v1' is supported");
    }

    Scenario scenario;
    const Node name_node = field(root, "name");
    scenario.name = scalar_string(name_node, source, "name");
    std::size_t name_characters = 0U;
    if (!utf8_codepoint_count(scenario.name, name_characters)) {
        fail(source, name_node, "name must contain valid UTF-8 text");
    }
    if (name_characters == 0U || name_characters > 128U) {
        fail(source, name_node, "name must contain 1..128 characters");
    }

    std::map<std::string, RouterIndex, std::less<>> router_by_id;
    std::set<std::uint32_t> router_ids;
    const Node routers_node = field(root, "routers");
    require_sequence(routers_node, source, "routers");
    if (routers_node.size() == 0U) {
        fail(source, routers_node, "routers must contain at least one router");
    }
    for (std::size_t index = 0U; index < routers_node.size(); ++index) {
        const Node item = routers_node[index];
        const std::string path = "routers[" + std::to_string(index) + "]";
        check_fields(item, source, path, {"id", "router_id", "initial_state"},
                     {"id", "router_id"});
        const Node id_node = field(item, "id");
        const std::string id = scalar_string(id_node, source, path + ".id");
        validate_id(id, id_node, source, path + ".id");
        const Node router_id_node = field(item, "router_id");
        const std::string router_id_text =
            scalar_string(router_id_node, source, path + ".router_id");
        const std::uint32_t router_id =
            parse_ipv4(router_id_text, router_id_node, source, path + ".router_id").value;
        if (!router_by_id.emplace(id, scenario.routers.size()).second) {
            fail(source, id_node, "duplicate router id '" + id + "'");
        }
        if (!router_ids.insert(router_id).second) {
            fail(source, router_id_node, "duplicate numeric OSPF router_id '" +
                                           router_id_text + "'");
        }
        scenario.routers.push_back(
            Router{id, router_id,
                   read_initial_state(field(item, "initial_state"), source,
                                      path + ".initial_state")});
    }
    std::sort(scenario.routers.begin(), scenario.routers.end(),
              [](const Router& left, const Router& right) { return left.id < right.id; });
    router_by_id.clear();
    for (RouterIndex index = 0U; index < scenario.routers.size(); ++index) {
        router_by_id.emplace(scenario.routers[index].id, index);
    }

    std::vector<RawLink> raw_links;
    std::set<std::string> link_ids;
    const Node links_node = field(root, "links");
    require_sequence(links_node, source, "links");
    for (std::size_t index = 0U; index < links_node.size(); ++index) {
        const Node item = links_node[index];
        const std::string path = "links[" + std::to_string(index) + "]";
        check_fields(item, source, path,
                     {"id", "a", "b", "cost_ab", "cost_ba", "initial_state"},
                     {"id", "a", "b", "cost_ab", "cost_ba"});
        const Node id_node = field(item, "id");
        RawLink link;
        link.id = scalar_string(id_node, source, path + ".id");
        validate_id(link.id, id_node, source, path + ".id");
        if (!link_ids.insert(link.id).second) {
            fail(source, id_node, "duplicate link id '" + link.id + "'");
        }
        const Node a_node = field(item, "a");
        const Node b_node = field(item, "b");
        link.a = scalar_string(a_node, source, path + ".a");
        link.b = scalar_string(b_node, source, path + ".b");
        validate_id(link.a, a_node, source, path + ".a");
        validate_id(link.b, b_node, source, path + ".b");
        if (!router_by_id.contains(link.a)) {
            fail(source, a_node, path + ".a references unknown router '" + link.a + "'");
        }
        if (!router_by_id.contains(link.b)) {
            fail(source, b_node, path + ".b references unknown router '" + link.b + "'");
        }
        if (link.a == link.b) {
            fail(source, item, path + " cannot connect a router to itself");
        }
        link.cost_ab = static_cast<std::uint16_t>(unsigned_integer(
            field(item, "cost_ab"), source, path + ".cost_ab", 1U, 65535U));
        link.cost_ba = static_cast<std::uint16_t>(unsigned_integer(
            field(item, "cost_ba"), source, path + ".cost_ba", 1U, 65535U));
        link.initially_up = read_initial_state(field(item, "initial_state"), source,
                                               path + ".initial_state");
        if (link.b < link.a) {
            std::swap(link.a, link.b);
            std::swap(link.cost_ab, link.cost_ba);
        }
        raw_links.push_back(std::move(link));
    }
    std::sort(raw_links.begin(), raw_links.end(),
              [](const RawLink& left, const RawLink& right) { return left.id < right.id; });
    for (const RawLink& link : raw_links) {
        const RouterIndex a = router_by_id.at(link.a);
        const RouterIndex b = router_by_id.at(link.b);
        scenario.links.push_back(Link{link.id, a, b, link.cost_ab, link.cost_ba,
                                      link.initially_up, link.id + "@" + link.a,
                                      link.id + "@" + link.b});
    }
    std::map<std::string, LinkIndex, std::less<>> link_by_id;
    for (LinkIndex index = 0U; index < scenario.links.size(); ++index) {
        link_by_id.emplace(scenario.links[index].id, index);
    }

    const Node prefixes_node = field(root, "prefixes");
    require_sequence(prefixes_node, source, "prefixes");
    if (prefixes_node.size() == 0U) {
        fail(source, prefixes_node, "prefixes must contain at least one prefix");
    }
    for (std::size_t index = 0U; index < prefixes_node.size(); ++index) {
        const Node item = prefixes_node[index];
        const std::string path = "prefixes[" + std::to_string(index) + "]";
        check_fields(item, source, path, {"prefix", "origin", "stub_cost"},
                     {"prefix", "origin", "stub_cost"});
        const Node prefix_node = field(item, "prefix");
        const IPv4Prefix network = parse_prefix(
            scalar_string(prefix_node, source, path + ".prefix"), prefix_node, source,
            path + ".prefix");
        const Node origin_node = field(item, "origin");
        const std::string origin = scalar_string(origin_node, source, path + ".origin");
        validate_id(origin, origin_node, source, path + ".origin");
        const auto router = router_by_id.find(origin);
        if (router == router_by_id.end()) {
            fail(source, origin_node, path + ".origin references unknown router '" + origin + "'");
        }
        const auto stub_cost = static_cast<std::uint16_t>(unsigned_integer(
            field(item, "stub_cost"), source, path + ".stub_cost", 1U, 65535U));
        scenario.prefixes.push_back(Prefix{network, router->second, stub_cost});
    }
    std::sort(scenario.prefixes.begin(), scenario.prefixes.end(),
              [](const Prefix& left, const Prefix& right) {
                  return std::tie(left.network.network.value, left.network.length, left.origin,
                                  left.stub_cost) <
                         std::tie(right.network.network.value, right.network.length, right.origin,
                                  right.stub_cost);
              });
    std::uint64_t previous_end = 0U;
    bool first_prefix = true;
    for (const Prefix& prefix : scenario.prefixes) {
        if (!first_prefix && prefix.network.network.value < previous_end) {
            fail(source, prefixes_node,
                 "prefixes must be disjoint; overlapping prefix '" +
                     prefix.network.to_string() + "'");
        }
        previous_end = prefix.network.end_exclusive();
        first_prefix = false;
    }

    std::vector<RawEvent> raw_events;
    std::set<std::string> event_ids;
    std::set<std::uint64_t> event_sequences;
    const Node events_node = field(root, "events");
    require_sequence(events_node, source, "events");
    for (std::size_t index = 0U; index < events_node.size(); ++index) {
        const Node item = events_node[index];
        const std::string path = "events[" + std::to_string(index) + "]";
        check_fields(item, source, path,
                     {"id", "seq", "at_ns", "type", "link", "router"},
                     {"id", "seq", "at_ns", "type"});
        const Node id_node = field(item, "id");
        RawEvent raw;
        raw.event.id = scalar_string(id_node, source, path + ".id");
        validate_id(raw.event.id, id_node, source, path + ".id");
        if (!event_ids.insert(raw.event.id).second) {
            fail(source, id_node, "duplicate event id '" + raw.event.id + "'");
        }
        const Node sequence_node = field(item, "seq");
        raw.event.sequence = unsigned_integer(sequence_node, source, path + ".seq", 1U,
                                              kMaximumInputInteger);
        if (!event_sequences.insert(raw.event.sequence).second) {
            fail(source, sequence_node, "event sequence numbers must be unique");
        }
        raw.event.at_ns = unsigned_integer(field(item, "at_ns"), source, path + ".at_ns", 0U,
                                            kMaximumInputInteger);
        const Node type_node = field(item, "type");
        const std::string type = scalar_string(type_node, source, path + ".type");
        const Node link_node = field(item, "link");
        const Node router_node = field(item, "router");
        if (type == "link_down" || type == "link_up") {
            if (!link_node.IsDefined() || router_node.IsDefined()) {
                fail(source, item, path + " requires exactly one 'link' target for " + type);
            }
            raw.target = scalar_string(link_node, source, path + ".link");
            validate_id(raw.target, link_node, source, path + ".link");
            if (!link_by_id.contains(raw.target)) {
                fail(source, link_node, path + ".link references unknown link '" + raw.target + "'");
            }
            raw.event.type = type == "link_down" ? EventType::link_down : EventType::link_up;
        } else if (type == "router_down" || type == "router_up") {
            if (!router_node.IsDefined() || link_node.IsDefined()) {
                fail(source, item, path + " requires exactly one 'router' target for " + type);
            }
            raw.target = scalar_string(router_node, source, path + ".router");
            validate_id(raw.target, router_node, source, path + ".router");
            if (!router_by_id.contains(raw.target)) {
                fail(source, router_node, path + ".router references unknown router '" +
                                               raw.target + "'");
            }
            raw.event.type = type == "router_down" ? EventType::router_down : EventType::router_up;
        } else {
            fail(source, type_node, path + ".type must be link_down, link_up, router_down, or router_up");
        }
        raw.mark = item.Mark();
        raw_events.push_back(std::move(raw));
    }
    std::sort(raw_events.begin(), raw_events.end(), [](const RawEvent& left, const RawEvent& right) {
        return left.event.sequence < right.event.sequence;
    });
    std::uint64_t previous_at_ns = 0U;
    bool first_event = true;
    for (RawEvent& raw : raw_events) {
        if (!first_event && raw.event.at_ns < previous_at_ns) {
            fail(source, raw.mark,
                 "event at_ns values must be nondecreasing in sequence order");
        }
        previous_at_ns = raw.event.at_ns;
        first_event = false;
        if (raw.event.type == EventType::link_down || raw.event.type == EventType::link_up) {
            raw.event.target_index = link_by_id.at(raw.target);
        } else {
            raw.event.target_index = router_by_id.at(raw.target);
        }
        scenario.events.push_back(std::move(raw.event));
    }

    const Node assertions_node = field(root, "assertions");
    require_sequence(assertions_node, source, "assertions");
    std::set<std::string> assertion_ids;
    for (std::size_t index = 0U; index < assertions_node.size(); ++index) {
        const Node item = assertions_node[index];
        const std::string path = "assertions[" + std::to_string(index) + "]";
        check_fields(item, source, path,
                     {"id", "type", "source", "destination", "quantifier", "scope"},
                     {"id", "type", "source", "destination", "quantifier", "scope"});
        const Node id_node = field(item, "id");
        const std::string id = scalar_string(id_node, source, path + ".id");
        validate_id(id, id_node, source, path + ".id");
        if (!assertion_ids.insert(id).second) {
            fail(source, id_node, "duplicate assertion id '" + id + "'");
        }
        const Node type_node = field(item, "type");
        if (scalar_string(type_node, source, path + ".type") != "must_reach") {
            fail(source, type_node, "only assertion type 'must_reach' is supported");
        }
        const Node source_node = field(item, "source");
        const std::string source_id = scalar_string(source_node, source, path + ".source");
        validate_id(source_id, source_node, source, path + ".source");
        const auto source_router = router_by_id.find(source_id);
        if (source_router == router_by_id.end()) {
            fail(source, source_node, path + ".source references unknown router '" +
                                          source_id + "'");
        }
        const Node destination_node = field(item, "destination");
        const IPv4Address destination = parse_ipv4(
            scalar_string(destination_node, source, path + ".destination"), destination_node,
            source, path + ".destination");
        PrefixIndex destination_prefix = scenario.prefixes.size();
        std::size_t matches = 0U;
        for (PrefixIndex prefix_index = 0U; prefix_index < scenario.prefixes.size();
             ++prefix_index) {
            if (scenario.prefixes[prefix_index].network.contains(destination)) {
                destination_prefix = prefix_index;
                ++matches;
            }
        }
        if (matches != 1U) {
            fail(source, destination_node,
                 path + ".destination must belong to exactly one declared prefix");
        }
        const Node quantifier_node = field(item, "quantifier");
        if (scalar_string(quantifier_node, source, path + ".quantifier") != "all") {
            fail(source, quantifier_node, "only quantifier 'all' is supported");
        }
        const Node scope_node = field(item, "scope");
        if (scalar_string(scope_node, source, path + ".scope") != "every_snapshot") {
            fail(source, scope_node, "only scope 'every_snapshot' is supported");
        }
        scenario.assertions.push_back(ReachabilityAssertion{
            id, source_router->second, destination, destination_prefix});
    }
    std::sort(scenario.assertions.begin(), scenario.assertions.end(),
              [](const ReachabilityAssertion& left, const ReachabilityAssertion& right) {
                  return left.id < right.id;
              });

    std::uint64_t maximum_directional_cost = 0U;
    for (const Link& link : scenario.links) {
        maximum_directional_cost =
            std::max({maximum_directional_cost, static_cast<std::uint64_t>(link.cost_ab),
                      static_cast<std::uint64_t>(link.cost_ba)});
    }
    std::uint64_t maximum_stub_cost = 0U;
    for (const Prefix& prefix : scenario.prefixes) {
        maximum_stub_cost = std::max(maximum_stub_cost,
                                     static_cast<std::uint64_t>(prefix.stub_cost));
    }
    const std::size_t edge_count_size = scenario.routers.size() - 1U;
    if constexpr (sizeof(std::size_t) > sizeof(std::uint64_t)) {
        if (edge_count_size > std::numeric_limits<std::uint64_t>::max()) {
            fail(source, routers_node, "router count exceeds the supported cost-bound range");
        }
    }
    const std::uint64_t maximum_simple_edges = static_cast<std::uint64_t>(edge_count_size);
    if (maximum_directional_cost != 0U &&
        maximum_simple_edges > (kOspfInfinity - 1U - maximum_stub_cost) /
                                   maximum_directional_cost) {
        fail(source, root,
             "cost bound (R - 1) * maximum_directional_cost + maximum_stub_cost must be "
             "less than 0x00ffffff");
    }
    const std::uint64_t cost_bound = maximum_simple_edges * maximum_directional_cost +
                                     maximum_stub_cost;
    if (cost_bound >= kOspfInfinity) {
        fail(source, root,
             "cost bound (R - 1) * maximum_directional_cost + maximum_stub_cost must be "
             "less than 0x00ffffff");
    }
    return scenario;
}

}  // namespace

InputError::InputError(std::string source, const std::size_t line,
                       const std::size_t column, std::string message)
    : std::runtime_error(location_message(source, line, column, message)),
      source_(std::move(source)), line_(line), column_(column) {}

InputError::InputError(std::string message)
    : std::runtime_error(location_message("<input>", 0U, 0U, message)),
      source_("<input>") {}

LoadedScenario load_scenario(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw InputError(path.string(), 0U, 0U, "could not open scenario file");
    }
    std::ostringstream contents;
    contents << input.rdbuf();
    if (input.bad()) {
        throw InputError(path.string(), 0U, 0U, "failed while reading scenario file");
    }
    return parse_scenario(contents.str(), path.string());
}

LoadedScenario parse_scenario(const std::string_view text, std::string source) {
    std::vector<Node> documents;
    try {
        documents = YAML::LoadAll(std::string(text));
    } catch (const YAML::Exception& error) {
        const std::size_t line = error.mark.is_null() ? 0U : error.mark.line + 1U;
        const std::size_t column = error.mark.is_null() ? 0U : error.mark.column + 1U;
        throw InputError(std::move(source), line, column,
                         "invalid YAML: " + std::string(error.what()));
    }
    if (documents.empty() || !documents.front().IsDefined() || documents.front().IsNull()) {
        throw InputError(std::move(source), 0U, 0U, "scenario document is empty");
    }
    if (documents.size() != 1U) {
        const YAML::Mark mark = documents[1].Mark();
        throw InputError(std::move(source), mark.is_null() ? 0U : mark.line + 1U,
                         mark.is_null() ? 0U : mark.column + 1U,
                         "exactly one YAML document is supported");
    }
    std::vector<Node> ancestors;
    std::vector<Node> visited;
    validate_yaml_tree(documents.front(), source, ancestors, visited, 0U);

    Scenario scenario = parse_document(documents.front(), source);
    const Json normalized = normalized_representation(scenario);
    const std::string normalized_json = normalized.dump(-1, ' ', false);
    const std::string hash = picosha2::hash256_hex_string(normalized_json);
    Topology topology = build_topology(std::move(scenario));
    return LoadedScenario{std::move(topology), normalized_json, hash};
}

}  // namespace routeproof::input
