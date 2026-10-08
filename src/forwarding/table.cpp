#include "routeproof/forwarding/table.hpp"
#include <algorithm>

namespace routeproof::forwarding {
const Route* lookup(const Tables& tables, const model::RouterIndex router,
                    const model::PrefixIndex prefix) {
    const auto& entries = tables.routers.at(router);
    const auto it = std::lower_bound(entries.begin(), entries.end(), prefix,
        [](const Route& route, const model::PrefixIndex key) { return route.prefix < key; });
    return it != entries.end() && it->prefix == prefix ? &*it : nullptr;
}
const Route* lookup(const model::Topology& topology, const Tables& tables,
                    const model::RouterIndex router, const model::IPv4Address destination) {
    for (model::PrefixIndex index = 0; index < topology.scenario.prefixes.size(); ++index) {
        if (topology.scenario.prefixes[index].network.contains(destination)) {
            return lookup(tables, router, index);
        }
    }
    return nullptr;
}
Tables compute(const model::Topology& topology, const spf::PhysicalState& state,
               const RoutingLimits& limits) {
    if (state.available_routers.size() != topology.scenario.routers.size() ||
        state.administratively_up_links.size() != topology.scenario.links.size()) {
        throw std::invalid_argument("forwarding state dimensions do not match topology");
    }
    Tables tables;
    tables.routers.resize(topology.scenario.routers.size());
    spf::Workspace scratch;
    const auto empty = std::make_shared<const spf::NextHopSet>();
    std::vector<std::shared_ptr<const spf::NextHopSet>> shared;
    for (model::RouterIndex source = 0; source < tables.routers.size(); ++source) {
        if (!state.available_routers[source]) {
            continue;
        }
        spf::compute(topology, state, source, scratch, limits.max_scratch_next_hops);
        shared.assign(tables.routers.size(), nullptr);
        for (model::PrefixIndex index = 0; index < topology.scenario.prefixes.size(); ++index) {
            const auto& prefix = topology.scenario.prefixes[index];
            const auto distance = scratch.distances[prefix.origin];
            if (distance == spf::infinity) {
                continue;
            }
            const bool local = source == prefix.origin;
            const auto size = local ? 0U : scratch.first_hops[prefix.origin].size();
            if (tables.route_entries >= limits.max_route_entries ||
                size > limits.max_next_hop_references - tables.next_hop_references) {
                throw spf::ResourceLimit("forwarding table route/next-hop budget exceeded");
            }
            if (!local && size == 0) {
                throw std::logic_error("reachable remote origin has no first hops");
            }
            auto& hops = shared[prefix.origin];
            if (!hops) {
                hops = local ? empty : std::make_shared<const spf::NextHopSet>(scratch.first_hops[prefix.origin]);
            }
            const auto protocol_cost = spf::checked_add(distance, prefix.stub_cost);
            if (protocol_cost >= 0x00ffffffU) {
                throw std::overflow_error("route cost reaches OSPF infinity");
            }
            tables.routers[source].push_back(Route{index, local ? RouteKind::connected : RouteKind::ospf,
                distance, local ? 0U : protocol_cost, protocol_cost, hops});
            ++tables.route_entries;
            tables.next_hop_references += size;
        }
    }
    validate(topology, state, tables);
    return tables;
}
void validate(const model::Topology& topology, const spf::PhysicalState& state,
              const Tables& tables) {
    for (model::RouterIndex source = 0; source < tables.routers.size(); ++source) {
        for (const auto& route : tables.routers[source]) {
            for (const auto& hop : *route.next_hops) {
                const auto* onward = lookup(tables, hop.neighbor, route.prefix);
                const auto& link = topology.scenario.links.at(hop.link);
                const bool forward = link.a == source && link.b == hop.neighbor &&
                                     link.interface_a == hop.outgoing_interface;
                const bool reverse = link.b == source && link.a == hop.neighbor &&
                                     link.interface_b == hop.outgoing_interface;
                if ((!forward && !reverse) || !state.available_routers[source] ||
                    !state.available_routers[hop.neighbor] || !state.administratively_up_links[hop.link] ||
                    !onward || onward->distance_to_origin >= route.distance_to_origin ||
                    spf::checked_add(onward->distance_to_origin, forward ? link.cost_ab : link.cost_ba) !=
                        route.distance_to_origin) {
                    throw std::logic_error("forwarding next hop violates shortest-path rank invariant");
                }
            }
        }
    }
}
}  // namespace routeproof::forwarding
