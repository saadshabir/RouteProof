#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace routeproof::model {

using RouterIndex = std::size_t;
using LinkIndex = std::size_t;
using PrefixIndex = std::size_t;

struct IPv4Address {
    std::uint32_t value{};

    [[nodiscard]] std::string to_string() const;
};

struct IPv4Prefix {
    IPv4Address network;
    std::uint8_t length{};

    [[nodiscard]] bool contains(IPv4Address address) const noexcept;
    [[nodiscard]] std::uint64_t end_exclusive() const noexcept;
    [[nodiscard]] std::string to_string() const;
};

enum class EventType {
    link_down,
    link_up,
    router_down,
    router_up,
};

struct Router {
    std::string id;
    std::uint32_t router_id{};
    bool initially_available{true};
};

struct Link {
    std::string id;
    RouterIndex a{};
    RouterIndex b{};
    std::uint16_t cost_ab{};
    std::uint16_t cost_ba{};
    bool initially_admin_up{true};
    std::string interface_a;
    std::string interface_b;
};

struct Prefix {
    IPv4Prefix network;
    RouterIndex origin{};
    std::uint16_t stub_cost{};
};

struct Event {
    std::string id;
    std::uint64_t sequence{};
    std::uint64_t at_ns{};
    EventType type{};
    std::size_t target_index{};
};

struct ReachabilityAssertion {
    std::string id;
    RouterIndex source{};
    IPv4Address destination;
    PrefixIndex destination_prefix{};
};

struct Scenario {
    std::string name;
    std::vector<Router> routers;
    std::vector<Link> links;
    std::vector<Prefix> prefixes;
    std::vector<Event> events;
    std::vector<ReachabilityAssertion> assertions;
};

[[nodiscard]] const char* event_type_name(EventType type) noexcept;

}  // namespace routeproof::model
