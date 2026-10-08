#include "routeproof/spf/shortest_paths.hpp"

#include <algorithm>
#include <functional>
#include <tuple>

namespace routeproof::spf {
Distance checked_add(const Distance left, const Distance right) {
    if (left == infinity || right >= infinity - left) {
        throw std::overflow_error("SPF distance overflow");
    }
    return left + right;
}

PhysicalState initial_state(const model::Topology& topology) {
    PhysicalState state;
    for (const auto& router : topology.scenario.routers) {
        state.available_routers.push_back(router.initially_available);
    }
    for (const auto& link : topology.scenario.links) {
        state.administratively_up_links.push_back(link.initially_admin_up);
    }
    return state;
}

void compute(const model::Topology& topology, const PhysicalState& state,
             const model::RouterIndex source, Workspace& scratch,
             const std::size_t max_scratch_next_hops) {
    const auto count = topology.scenario.routers.size();
    if (state.available_routers.size() != count ||
        state.administratively_up_links.size() != topology.scenario.links.size() ||
        source >= count) {
        throw std::invalid_argument("SPF state dimensions/source do not match topology");
    }
    scratch.distances.assign(count, infinity);
    scratch.first_hops.resize(count);
    for (auto& hops : scratch.first_hops) {
        hops.clear();
    }
    scratch.order.clear();
    scratch.queue.clear();
    if (!state.available_routers[source]) {
        return;
    }
    const auto usable = [&](const model::DirectedArc& arc) {
        return state.administratively_up_links[arc.link] &&
               state.available_routers[arc.neighbor];
    };
    // Keep heap storage with the other per-source scratch buffers.
    auto& queue = scratch.queue;
    scratch.distances[source] = 0;
    queue.emplace_back(0, source);
    while (!queue.empty()) {
        std::pop_heap(queue.begin(), queue.end(), std::greater<>{});
        const auto [distance, router] = queue.back();
        queue.pop_back();
        if (distance != scratch.distances[router]) {
            continue;
        }
        scratch.order.push_back(router);
        for (const auto& arc : topology.adjacency[router]) {
            if (!usable(arc)) {
                continue;
            }
            const auto candidate = checked_add(distance, arc.cost);
            if (candidate < scratch.distances[arc.neighbor]) {
                scratch.distances[arc.neighbor] = candidate;
                queue.emplace_back(candidate, arc.neighbor);
                std::push_heap(queue.begin(), queue.end(), std::greater<>{});
            }
        }
    }
    // Dijkstra's settled order is increasing distance. Positive costs ensure
    // every predecessor is complete before its DAG successors are visited.
    const auto less = [&](const NextHop& left, const NextHop& right) {
        return std::tie(topology.scenario.routers[left.neighbor].id,
                        topology.scenario.links[left.link].id, left.outgoing_interface) <
               std::tie(topology.scenario.routers[right.neighbor].id,
                        topology.scenario.links[right.link].id, right.outgoing_interface);
    };
    std::size_t references = 0;
    for (const auto router : scratch.order) {
        for (const auto& arc : topology.adjacency[router]) {
            if (!usable(arc) || checked_add(scratch.distances[router], arc.cost) !=
                                    scratch.distances[arc.neighbor]) {
                continue;
            }
            auto& target = scratch.first_hops[arc.neighbor];
            const auto insert = [&](const NextHop& hop) {
                const auto position = std::lower_bound(target.begin(), target.end(), hop, less);
                if (position == target.end() || *position != hop) {
                    if (references >= max_scratch_next_hops) {
                        throw ResourceLimit("SPF scratch next-hop budget exceeded");
                    }
                    target.insert(position, hop);
                    ++references;
                }
            };
            if (router == source) {
                insert({arc.neighbor, arc.link, arc.outgoing_interface});
            } else {
                const auto& incoming = scratch.first_hops[router];
                if (target.empty()) {
                    // Incoming sets are already sorted and unique. The first
                    // predecessor can copy the complete set without searches.
                    if (incoming.size() > max_scratch_next_hops - references) {
                        throw ResourceLimit("SPF scratch next-hop budget exceeded");
                    }
                    target.assign(incoming.begin(), incoming.end());
                    references += incoming.size();
                } else {
                    for (const auto& hop : incoming) { insert(hop); }
                }
            }
        }
    }
}
}  // namespace routeproof::spf
