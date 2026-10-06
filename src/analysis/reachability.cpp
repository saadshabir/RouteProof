#include "routeproof/analysis/reachability.hpp"
#include <algorithm>
#include <deque>
#include <set>
#include <tuple>

namespace routeproof::analysis {
namespace {
std::string edge_failure(const model::Topology& topology, const spf::PhysicalState& state,
                         model::RouterIndex source, const spf::NextHop& hop) {
    if (hop.link >= topology.scenario.links.size() || hop.neighbor >= topology.scenario.routers.size()) {
        return "incomplete";
    }
    const auto& link = topology.scenario.links[hop.link];
    if (!((link.a == source && link.b == hop.neighbor && link.interface_a == hop.outgoing_interface) ||
          (link.b == source && link.a == hop.neighbor && link.interface_b == hop.outgoing_interface))) {
        return "incomplete";
    }
    if (!state.administratively_up_links[hop.link]) { return "link_down"; }
    if (!state.available_routers[hop.neighbor]) { return "next_hop_down"; }
    return {};
}
void partition(const model::Topology& topology, const spf::PhysicalState& state,
               model::RouterIndex start, Finding& finding) {
    std::vector<bool> visited(topology.scenario.routers.size());
    std::deque<model::RouterIndex> queue;
    if (state.available_routers[start]) { visited[start] = true; queue.push_back(start); }
    while (!queue.empty()) {
        const auto source = queue.front(); queue.pop_front();
        for (const auto& arc : topology.adjacency[source]) {
            if (state.administratively_up_links[arc.link] && state.available_routers[arc.neighbor] &&
                !visited[arc.neighbor]) {
                visited[arc.neighbor] = true; queue.push_back(arc.neighbor);
            }
        }
    }
    finding.component.clear(); finding.frontier.clear(); finding.unavailable_boundary_routers.clear();
    for (model::RouterIndex index = 0; index < visited.size(); ++index) {
        if (visited[index]) { finding.component.push_back(index); }
    }
    std::set<model::RouterIndex> unavailable;
    for (model::LinkIndex index = 0; index < topology.scenario.links.size(); ++index) {
        const auto& link = topology.scenario.links[index];
        if (visited[link.a] == visited[link.b]) { continue; }
        finding.frontier.push_back({index, !state.administratively_up_links[index]});
        const auto outside = visited[link.a] ? link.b : link.a;
        if (!state.available_routers[outside]) { unavailable.insert(outside); }
    }
    finding.unavailable_boundary_routers.assign(unavailable.begin(), unavailable.end());
}
std::string terminal(const model::Topology& topology, const spf::PhysicalState& state,
                     const forwarding::Tables& tables, model::PrefixIndex prefix, model::RouterIndex router) {
    if (!state.available_routers[router]) { return "next_hop_down"; }
    const auto* route = forwarding::lookup(tables, router, prefix);
    if (!route) { return "no_route"; }
    if (!route->next_hops) { return "incomplete"; }
    if (route->kind == forwarding::RouteKind::connected) {
        return router == topology.scenario.prefixes[prefix].origin && route->next_hops->empty()
                   ? "deliver" : "incomplete";
    }
    return route->next_hops->empty() ? "no_route" : "";
}
}
DestinationAnalysis::DestinationAnalysis(const model::Topology& topology, const spf::PhysicalState& state,
    const forwarding::Tables& tables, model::PrefixIndex prefix, const AnalysisLimits& limits)
    : topology_(topology), state_(state), prefix_(prefix) {
    const auto count = topology.scenario.routers.size();
    if (state.available_routers.size() != count || tables.routers.size() != count ||
        state.administratively_up_links.size() != topology.scenario.links.size() ||
        prefix >= topology.scenario.prefixes.size()) {
        throw std::invalid_argument("analysis dimensions do not match topology");
    }
    if (count > limits.max_vertices) { throw spf::ResourceLimit("destination vertex budget exceeded"); }
    nodes_.resize(count); safe_.resize(count);
    std::vector<std::vector<model::RouterIndex>> predecessors(count);
    std::vector<bool> blocked(count);
    std::deque<model::RouterIndex> queue;
    std::size_t edges = 0;
    for (model::RouterIndex source = 0; source < count; ++source) {
        auto& node = nodes_[source];
        node.terminal = terminal(topology, state, tables, prefix, source);
        if (!node.terminal.empty() && node.terminal != "deliver") { blocked[source] = true; }
        if (!node.terminal.empty()) { continue; }
        const auto* route = forwarding::lookup(tables, source, prefix);
        if (route->next_hops->size() > limits.max_edges - edges) {
            throw spf::ResourceLimit("destination edge budget exceeded");
        }
        edges += route->next_hops->size();
        auto hops = *route->next_hops;
        std::sort(hops.begin(), hops.end(), [&](const auto& left, const auto& right) {
            // Invalid indices sort deterministically too, without dereferencing.
            return std::tie(left.neighbor, left.link, left.outgoing_interface) <
                   std::tie(right.neighbor, right.link, right.outgoing_interface);
        });
        hops.erase(std::unique(hops.begin(), hops.end()), hops.end());
        for (const auto& hop : hops) {
            auto failure = edge_failure(topology, state, source, hop);
            node.edges.push_back({hop, failure});
            if (failure.empty()) { predecessors[hop.neighbor].push_back(source); }
            else { blocked[source] = true; }
        }
    }
    // Iterative Kosaraju SCC decomposition. A reachable cyclic SCC is a
    // possible nonterminating ECMP choice even when it has a delivery exit.
    // No recursion and no enumeration of complete paths.
    std::vector<bool> visited(count);
    std::vector<model::RouterIndex> finish;
    std::vector<std::pair<model::RouterIndex, std::size_t>> stack;
    for (model::RouterIndex root = 0; root < count; ++root) {
        if (visited[root]) { continue; }
        visited[root] = true; stack.emplace_back(root, 0);
        while (!stack.empty()) {
            auto& [router, next] = stack.back();
            const auto& outgoing = nodes_[router].edges;
            if (next == outgoing.size()) {
                finish.push_back(router); stack.pop_back(); continue;
            }
            const auto& edge = outgoing[next++];
            if (edge.failure.empty() && !visited[edge.hop.neighbor]) {
                visited[edge.hop.neighbor] = true; stack.emplace_back(edge.hop.neighbor, 0);
            }
        }
    }
    visited.assign(count, false);
    std::vector<model::RouterIndex> members, pending;
    for (auto it = finish.rbegin(); it != finish.rend(); ++it) {
        if (visited[*it]) { continue; }
        visited[*it] = true; pending.push_back(*it); members.clear();
        while (!pending.empty()) {
            const auto router = pending.back(); pending.pop_back(); members.push_back(router);
            for (const auto parent : predecessors[router]) {
                if (!visited[parent]) { visited[parent] = true; pending.push_back(parent); }
            }
        }
        bool cyclic = members.size() > 1;
        if (!cyclic) {
            for (const auto& edge : nodes_[members.front()].edges) {
                cyclic = cyclic || (edge.failure.empty() && edge.hop.neighbor == members.front());
            }
        }
        if (cyclic) { for (const auto router : members) { blocked[router] = true; } }
    }
    // Reverse traversal marks every source with any branch leading to a bad
    // terminal, unusable edge, or cycle. All other vertices universally deliver.
    for (model::RouterIndex router = 0; router < count; ++router) {
        if (blocked[router]) { queue.push_back(router); }
    }
    while (!queue.empty()) {
        const auto bad = queue.front(); queue.pop_front();
        for (const auto parent : predecessors[bad]) {
            if (!blocked[parent]) { blocked[parent] = true; queue.push_back(parent); }
        }
    }
    for (model::RouterIndex router = 0; router < count; ++router) { safe_[router] = !blocked[router]; }
}
std::optional<Finding> DestinationAnalysis::check(const model::RouterIndex source) const {
    if (source >= nodes_.size()) { throw std::invalid_argument("unknown analysis source"); }
    Finding finding;
    auto stop = [&](std::string reason, model::RouterIndex at) -> std::optional<Finding> {
        finding.kind = reason; finding.terminal_reason = reason;
        finding.path.push_back({at, std::nullopt});
        if (reason == "no_route") { partition(topology_, state_, at, finding); }
        return finding;
    };
    if (!state_.available_routers[source]) { return stop("source_down", source); }
    if (!state_.available_routers[topology_.scenario.prefixes[prefix_].origin]) {
        return stop("destination_down", source);
    }
    if (safe_[source]) { return std::nullopt; }
    std::vector<std::optional<std::size_t>> active(nodes_.size());
    auto current = source;
    // Each unsafe nonterminal has either a failed edge or an unsafe successor.
    // Selecting the first such edge reaches a drop or repeats a vertex in <= R hops.
    while (true) {
        if (active[current]) {
            finding.cycle_entry = *active[current];
            return stop("loop", current);
        }
        active[current] = finding.path.size();
        const auto& node = nodes_[current];
        if (!node.terminal.empty()) { return stop(node.terminal, current); }
        bool selected = false;
        for (const auto& edge : node.edges) {
            if (!edge.failure.empty() || !safe_[edge.hop.neighbor]) {
                finding.path.push_back({current, edge.hop});
                if (!edge.failure.empty()) {
                    finding.kind = edge.failure; finding.terminal_reason = edge.failure;
                    return finding;
                }
                current = edge.hop.neighbor; selected = true; break;
            }
        }
        if (!selected) { throw std::logic_error("unsafe node has no unsafe forwarding alternative"); }
    }
}
void validate_witness(const model::Topology& topology, const spf::PhysicalState& state,
                      const forwarding::Tables& tables, model::PrefixIndex prefix,
                      model::RouterIndex source, const Finding& finding) {
    auto require = [](bool condition) {
        if (!condition) { throw std::logic_error("invalid forwarding witness/certificate"); }
    };
    require(!finding.path.empty() && finding.path.front().router == source &&
            finding.kind == finding.terminal_reason);
    const auto origin = topology.scenario.prefixes.at(prefix).origin;
    model::RouterIndex current = source;
    for (std::size_t index = 0; index < finding.path.size(); ++index) {
        const auto& step = finding.path[index];
        require(step.router == current);
        if (!step.hop) { require(index + 1 == finding.path.size()); break; }
        const auto* route = forwarding::lookup(tables, current, prefix);
        require(state.available_routers.at(current) && route && route->next_hops &&
                std::find(route->next_hops->begin(), route->next_hops->end(), *step.hop) != route->next_hops->end());
        const auto failure = edge_failure(topology, state, current, *step.hop);
        if (!failure.empty()) {
            require(index + 1 == finding.path.size() && failure == finding.kind); return;
        }
        current = step.hop->neighbor;
        require(index + 1 < finding.path.size());
    }
    const auto& last = finding.path.back();
    require(!last.hop);
    if (finding.kind == "source_down") {
        require(finding.path.size() == 1 && !state.available_routers.at(source));
    } else if (finding.kind == "destination_down") {
        require(finding.path.size() == 1 && !state.available_routers.at(origin));
    } else if (finding.kind == "loop") {
        require(finding.cycle_entry && *finding.cycle_entry < finding.path.size() - 1 &&
                finding.path[*finding.cycle_entry].router == last.router);
    } else {
        require(terminal(topology, state, tables, prefix, last.router) == finding.kind);
        if (finding.kind == "no_route") {
            Finding expected; partition(topology, state, last.router, expected);
            require(expected.component == finding.component &&
                    expected.unavailable_boundary_routers == finding.unavailable_boundary_routers &&
                    expected.frontier.size() == finding.frontier.size());
            for (std::size_t index = 0; index < expected.frontier.size(); ++index) {
                require(expected.frontier[index].link == finding.frontier[index].link &&
                        expected.frontier[index].administratively_down == finding.frontier[index].administratively_down);
            }
        }
    }
}
}
