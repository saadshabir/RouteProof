#include "routeproof/spf/shortest_paths.hpp"

#include <algorithm>
#include <functional>
#include <queue>
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
    if (!state.available_routers[source]) {
        return;
    }
    const auto usable = [&](const model::DirectedArc& arc) {
        return state.administratively_up_links[arc.link] &&
               state.available_routers[arc.neighbor];
    };
    using Item = std::pair<Distance, model::RouterIndex>;
    std::priority_queue<Item, std::vector<Item>, std::greater<>> queue;
    scratch.distances[source] = 0;
    queue.emplace(0, source);
    while (!queue.empty()) {
        const auto [distance, router] = queue.top();
        queue.pop();
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
                queue.emplace(candidate, arc.neighbor);
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
            const NextHopSet direct{{arc.neighbor, arc.link, arc.outgoing_interface}};
            const auto& incoming = router == source ? direct : scratch.first_hops[router];
            for (const auto& hop : incoming) {
                const auto position = std::lower_bound(target.begin(), target.end(), hop, less);
                if (position == target.end() || *position != hop) {
                    if (references >= max_scratch_next_hops) {
                        throw ResourceLimit("SPF scratch next-hop budget exceeded");
                    }
                    target.insert(position, hop);
                    ++references;
                }
            }
        }
    }
}
}  // namespace routeproof::spf
