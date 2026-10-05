#include "routeproof/forwarding/table.hpp"
#include "routeproof/input/scenario_loader.hpp"
#include <algorithm>
#include <iostream>
#include <limits>
#include <utility>

namespace {
void require(bool condition, const char* message) {
    if (!condition) { throw std::runtime_error(message); }
}
template<class Exception, class Function>
void rejects(Function function, const char* message) {
    try { function(); } catch (const Exception&) { return; }
    throw std::runtime_error(message);
}
void check_unavailable_sources() {
    // This valid topology stays cheap only if unavailable sources are skipped.
    // CTest's timeout catches quadratic work without a host-specific timing assertion.
    constexpr std::size_t count = 100'000U;
    routeproof::model::Scenario scenario;
    scenario.name = "unavailable-sources";
    scenario.routers.reserve(count);
    for (std::size_t index = 0; index < count; ++index) {
        scenario.routers.push_back({"r" + std::to_string(index),
            static_cast<std::uint32_t>(index + 1), false});
    }
    scenario.prefixes.push_back({{{0x0a000000U}, 24}, 0, 1});
    const auto topology = routeproof::model::build_topology(std::move(scenario));
    auto state = routeproof::spf::initial_state(topology);
    auto limits = routeproof::forwarding::RoutingLimits{0, 0, 0};
    const auto unavailable = routeproof::forwarding::compute(topology, state, limits);
    require(unavailable.routers.size() == count && unavailable.route_entries == 0 &&
            unavailable.next_hop_references == 0 &&
            std::all_of(unavailable.routers.begin(), unavailable.routers.end(),
                [](const auto& entries) { return entries.empty(); }),
            "all-down topology must retain empty tables without consuming routing budgets");
    auto bad_state = state;
    bad_state.available_routers.pop_back();
    rejects<std::invalid_argument>([&]{ (void)routeproof::forwarding::compute(topology, bad_state); },
        "all-down topology accepted mismatched router state dimensions");
    bad_state = state;
    bad_state.administratively_up_links.push_back(false);
    rejects<std::invalid_argument>([&]{ (void)routeproof::forwarding::compute(topology, bad_state); },
        "all-down topology accepted mismatched link state dimensions");
    state.available_routers[0] = true;
    limits.max_route_entries = 1;
    const auto restored = routeproof::forwarding::compute(topology, state, limits);
    const auto* local = routeproof::forwarding::lookup(restored, 0, 0);
    require(restored.route_entries == 1 && restored.next_hop_references == 0 && local &&
            local->kind == routeproof::forwarding::RouteKind::connected,
            "restoring one origin must calculate its connected route");
}
}
int main(int argc, char** argv) {
    try {
        require(argc == 2, "expected fixture");
        const auto loaded = routeproof::input::load_scenario(argv[1]);
        const auto& topology = loaded.topology;
        const auto source = topology.router_index_by_id.at("r0");
        const auto origin = topology.router_index_by_id.at("r5");
        auto state = routeproof::spf::initial_state(topology);
        const auto baseline = routeproof::forwarding::compute(topology, state);
        const auto& owned = topology.prefixes_by_origin[origin];
        const auto* first = routeproof::forwarding::lookup(baseline, source, owned[0]);
        const auto* second = routeproof::forwarding::lookup(baseline, source, owned[1]);
        require(first && second && first->next_hops == second->next_hops, "prefixes must share immutable ECMP sets");
        require(first->next_hops->size() == 2 && first->distance_to_origin == 4, "merged ECMP loses alternatives");
        require(routeproof::forwarding::lookup(topology, baseline, source,
            topology.scenario.prefixes[owned[0]].network.network) == first, "address lookup failed");
        require(!routeproof::forwarding::lookup(topology, baseline, source, {0xffffffffU}), "unknown destination matched");
        const auto* local = routeproof::forwarding::lookup(baseline, origin, owned[0]);
        require(local && local->kind == routeproof::forwarding::RouteKind::connected &&
                local->metric == 0 && local->protocol_cost == topology.scenario.prefixes[owned[0]].stub_cost &&
                local->next_hops->empty(), "connected delivery metadata wrong");
        for (std::size_t link = 0; link < topology.scenario.links.size(); ++link) {
            state.administratively_up_links[link] = false;
            const auto removed = routeproof::forwarding::compute(topology, state);
            for (std::size_t router = 0; router < baseline.routers.size(); ++router) {
                for (const auto& route : removed.routers[router]) {
                    const auto* previous = routeproof::forwarding::lookup(baseline, router, route.prefix);
                    require(previous && route.distance_to_origin >= previous->distance_to_origin,
                            "link removal reduced distance");
                }
            }
            state.administratively_up_links[link] = true;
        }
        state.available_routers[origin] = false;
        const auto unavailable = routeproof::forwarding::compute(topology, state);
        require(unavailable.routers[origin].empty() &&
                !routeproof::forwarding::lookup(unavailable, source, owned[0]), "down origin still routable");
        state.available_routers[origin] = true;
        const auto restored = routeproof::forwarding::compute(topology, state);
        require(restored.route_entries == baseline.route_entries &&
                restored.next_hop_references == baseline.next_hop_references, "restoration counters differ");
        auto limits = routeproof::forwarding::RoutingLimits{};
        limits.max_route_entries = baseline.route_entries;
        limits.max_next_hop_references = baseline.next_hop_references;
        (void)routeproof::forwarding::compute(topology, state, limits);
        --limits.max_route_entries;
        rejects<routeproof::spf::ResourceLimit>([&]{ (void)routeproof::forwarding::compute(topology, state, limits); },
            "route budget did not reject at boundary");
        ++limits.max_route_entries;
        --limits.max_next_hop_references;
        rejects<routeproof::spf::ResourceLimit>([&]{ (void)routeproof::forwarding::compute(topology, state, limits); },
            "next-hop budget did not reject at boundary");
        limits = {};
        limits.max_scratch_next_hops = 0;
        rejects<routeproof::spf::ResourceLimit>([&]{ (void)routeproof::forwarding::compute(topology, state, limits); },
            "scratch budget did not reject");
        auto bad_state = state;
        bad_state.available_routers.pop_back();
        rejects<std::invalid_argument>([&]{ (void)routeproof::forwarding::compute(topology, bad_state); },
            "state dimension mismatch accepted");
        rejects<std::overflow_error>([]{ (void)routeproof::spf::checked_add(routeproof::spf::infinity-1, 1); },
            "distance overflow accepted");
        auto corrupt = baseline;
        const auto prefix_index = owned[0];
        for (auto& route : corrupt.routers[source]) {
            if (route.prefix == prefix_index) { route.distance_to_origin = 0; }
        }
        rejects<std::logic_error>([&]{ routeproof::forwarding::validate(topology, state, corrupt); },
            "rank invariant accepted corruption");
        check_unavailable_sources();
        std::cout << "PASS routing contract: shared sets, lookup, connected cost, removal/restoration, resource boundaries, rank/overflow checks, 100000 unavailable sources and state dimensions\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL routing contract: " << error.what() << '\n';
        return 1;
    }
}
