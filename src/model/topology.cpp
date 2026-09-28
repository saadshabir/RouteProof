#include "routeproof/model/topology.hpp"

#include <algorithm>
#include <tuple>
#include <utility>

namespace routeproof::model {

std::string IPv4Address::to_string() const {
    return std::to_string((value >> 24U) & 0xffU) + "." +
           std::to_string((value >> 16U) & 0xffU) + "." +
           std::to_string((value >> 8U) & 0xffU) + "." +
           std::to_string(value & 0xffU);
}

bool IPv4Prefix::contains(const IPv4Address address) const noexcept {
    const std::uint32_t mask = length == 0U
                                   ? 0U
                                   : 0xffffffffU << (32U - length);
    return (address.value & mask) == network.value;
}

std::uint64_t IPv4Prefix::end_exclusive() const noexcept {
    const std::uint64_t size = std::uint64_t{1} << (32U - length);
    return static_cast<std::uint64_t>(network.value) + size;
}

std::string IPv4Prefix::to_string() const {
    return network.to_string() + "/" + std::to_string(length);
}

const char* event_type_name(const EventType type) noexcept {
    switch (type) {
        case EventType::link_down:
            return "link_down";
        case EventType::link_up:
            return "link_up";
        case EventType::router_down:
            return "router_down";
        case EventType::router_up:
            return "router_up";
    }
    return "unknown";
}

Topology build_topology(Scenario scenario) {
    Topology topology;
    topology.scenario = std::move(scenario);
    topology.adjacency.resize(topology.scenario.routers.size());
    topology.prefixes_by_origin.resize(topology.scenario.routers.size());

    for (RouterIndex index = 0; index < topology.scenario.routers.size(); ++index) {
        topology.router_index_by_id.emplace(topology.scenario.routers[index].id, index);
    }
    for (LinkIndex index = 0; index < topology.scenario.links.size(); ++index) {
        const Link& link = topology.scenario.links[index];
        topology.link_index_by_id.emplace(link.id, index);

        topology.adjacency[link.a].push_back(
            DirectedArc{link.b, index, link.interface_a, link.cost_ab});
        topology.adjacency[link.b].push_back(
            DirectedArc{link.a, index, link.interface_b, link.cost_ba});
    }
    for (PrefixIndex index = 0; index < topology.scenario.prefixes.size(); ++index) {
        topology.prefixes_by_origin[topology.scenario.prefixes[index].origin]
            .push_back(index);
    }

    for (auto& arcs : topology.adjacency) {
        std::sort(arcs.begin(), arcs.end(), [&](const DirectedArc& left,
                                                const DirectedArc& right) {
            return std::tie(topology.scenario.routers[left.neighbor].id,
                            topology.scenario.links[left.link].id,
                            left.outgoing_interface, left.cost) <
                   std::tie(topology.scenario.routers[right.neighbor].id,
                            topology.scenario.links[right.link].id,
                            right.outgoing_interface, right.cost);
        });
    }
    for (auto& owned_prefixes : topology.prefixes_by_origin) {
        std::sort(owned_prefixes.begin(), owned_prefixes.end(),
                  [&](const PrefixIndex left, const PrefixIndex right) {
                      return topology.scenario.prefixes[left].network.to_string() <
                             topology.scenario.prefixes[right].network.to_string();
                  });
    }

    return topology;
}

}  // namespace routeproof::model
