#include "routeproof/analysis/reachability.hpp"
#include "routeproof/engine/replay.hpp"
#include "routeproof/input/scenario_loader.hpp"
#include "routeproof/output/simulation.hpp"
#include <algorithm>
#include <iostream>
#include <limits>

namespace {
void require(bool value, const char* message) { if (!value) { throw std::runtime_error(message); } }
template<class Function> void rejects(Function function, const char* message) {
    try { function(); } catch (const std::logic_error&) { return; }
    throw std::runtime_error(message);
}
}
int main(int argc, char** argv) {
    using namespace routeproof;
    try {
        require(argc == 2, "expected diamond fixture");
        const auto loaded = input::load_scenario(argv[1]);
        const auto& topology = loaded.topology;
        const auto a = topology.router_index_by_id.at("a"), b = topology.router_index_by_id.at("b");
        const auto c = topology.router_index_by_id.at("c"), d = topology.router_index_by_id.at("d");
        const auto prefix = loaded.topology.scenario.assertions.at(0).destination_prefix;
        auto state = spf::initial_state(topology);
        const auto baseline = forwarding::compute(topology, state);
        auto expect = [&](const forwarding::Tables& tables, const char* kind) {
            analysis::DestinationAnalysis graph(topology, state, tables, prefix);
            auto finding = graph.check(a);
            require(finding && finding->kind == kind, "malformed FIB was not rejected with expected reason");
            analysis::validate_witness(topology, state, tables, prefix, a, *finding);
            auto reordered = tables;
            for (auto& entries : reordered.routers) {
                for (auto& route : entries) {
                    if (!route.next_hops) { continue; }
                    auto hops = *route.next_hops; std::reverse(hops.begin(), hops.end());
                    route.next_hops = std::make_shared<const spf::NextHopSet>(hops);
                }
            }
            const analysis::DestinationAnalysis alternative(topology,state,reordered,prefix);
            require(alternative.check(a) == finding && graph.check(a) == finding,
                    "FIB order/repeat changes chosen witness");
            auto corrupt = *finding; corrupt.path.front().router = d;
            rejects([&]{ analysis::validate_witness(topology, state, tables, prefix, a, corrupt); },
                    "invalid source witness accepted");
            return *finding;
        };
        analysis::DestinationAnalysis good(topology, state, baseline, prefix);
        for (const auto router : {a,b,c,d}) { require(!good.check(router), "valid all-branch delivery failed"); }
        // one_bad_ecmp_branch: c still delivers, but b loses its route.
        auto hole = baseline; hole.routers[b].clear();
        const auto drop = expect(hole, "no_route");
        require(drop.path.size() == 2 && drop.path[0].hop->neighbor == b,
                "failed ECMP branch witness wrong");
        auto corrupt_certificate = drop; corrupt_certificate.component.clear();
        rejects([&]{ analysis::validate_witness(topology, state, hole, prefix, a, corrupt_certificate); },
                "corrupt component accepted");
        // cycle_with_exit: a can deliver via c, but may loop a -> b -> a.
        auto cycle = baseline;
        for (auto& route : cycle.routers[b]) {
            route.next_hops = std::make_shared<const spf::NextHopSet>(spf::NextHopSet{
                {a, topology.link_index_by_id.at("ab"), "ab@b"}});
        }
        const auto loop = expect(cycle, "loop");
        require(loop.path.size() == 3 && loop.cycle_entry == 0 && loop.path.back().router == a,
                "closed cycle with exit was not detected");
        auto corrupt_cycle = loop; corrupt_cycle.cycle_entry = 1;
        rejects([&]{ analysis::validate_witness(topology, state, cycle, prefix, a, corrupt_cycle); },
                "unclosed cycle witness accepted");
        for (const auto entry : {loop.path.size() - 1, loop.path.size(), std::numeric_limits<std::size_t>::max()}) {
            corrupt_cycle = loop; corrupt_cycle.cycle_entry = entry;
            rejects([&]{ analysis::validate_witness(topology, state, cycle, prefix, a, corrupt_cycle); },
                    "out-of-range cycle entry accepted");
        }
        corrupt_cycle = loop; corrupt_cycle.cycle_entry.reset();
        rejects([&]{ analysis::validate_witness(topology, state, cycle, prefix, a, corrupt_cycle); },
                "missing cycle entry accepted");
        // Exercise state validation against supplied stale tables.
        state.administratively_up_links[topology.link_index_by_id.at("ab")] = false;
        (void)expect(baseline, "link_down");
        state = spf::initial_state(topology); state.available_routers[b] = false;
        (void)expect(baseline, "next_hop_down");
        state.available_routers[a] = false; (void)expect(baseline, "source_down");
        state = spf::initial_state(topology); state.available_routers[d] = false;
        (void)expect(baseline, "destination_down");
        state = spf::initial_state(topology);
        auto empty = baseline;
        for (auto& route : empty.routers[b]) { route.next_hops = std::make_shared<const spf::NextHopSet>(); }
        (void)expect(empty, "no_route");
        auto wrong_interface = baseline;
        for (auto& route : wrong_interface.routers[b]) {
            auto hops = *route.next_hops; hops.front().outgoing_interface = "invalid";
            route.next_hops = std::make_shared<const spf::NextHopSet>(hops);
        }
        (void)expect(wrong_interface, "incomplete");
        auto invalid_connected = baseline;
        for (auto& route : invalid_connected.routers[b]) { route.kind = forwarding::RouteKind::connected; }
        (void)expect(invalid_connected, "incomplete");
        // Exhaust the 64 FIB edge subsets at a/b/c. This independent tiny
        // reference follows every reachable edge using three-color traversal.
        // It rejects both drops and gray-vertex revisits, including cycles
        // whose other branch reaches d. The production checker uses iterative SCC classification.
        for (unsigned mask = 0; mask < 64; ++mask) {
            auto supplied = baseline;
            for (const auto router : {a,b,c}) {
                const unsigned bits = (mask >> (router * 2)) & 3U;
                spf::NextHopSet selected;
                for (std::size_t i = 0; i < topology.adjacency[router].size(); ++i) {
                    const auto& arc = topology.adjacency[router][i];
                    if (bits & (1U << i)) { selected.push_back({arc.neighbor, arc.link, arc.outgoing_interface}); }
                }
                for (auto& route : supplied.routers[router]) {
                    route.next_hops = std::make_shared<const spf::NextHopSet>(selected);
                }
            }
            analysis::DestinationAnalysis graph(topology, state, supplied, prefix);
            for (const auto source : {a,b,c,d}) {
                std::vector<unsigned> color(4);
                std::function<bool(model::RouterIndex)> visit = [&](auto router) {
                    if (router == d) { return true; }
                    if (color[router] == 1) { return false; }
                    if (color[router] == 2) { return true; }
                    const auto* route = forwarding::lookup(supplied, router, prefix);
                    if (!route || route->next_hops->empty()) { return false; }
                    color[router] = 1;
                    for (const auto& hop : *route->next_hops) { if (!visit(hop.neighbor)) { return false; } }
                    color[router] = 2; return true;
                };
                const bool expected = visit(source);
                const auto finding = graph.check(source);
                require(expected == !finding, "all-branch checker differs from exhaustive tiny-FIB reference");
                if (finding) { analysis::validate_witness(topology, state, supplied, prefix, source, *finding); }
            }
        }
        // A long supplied chain protects iterative analysis/witness validation
        // from stack exhaustion. No all-pairs SPF is needed for this fixture.
        {
            constexpr std::size_t count = 20000;
            model::Scenario chain;
            for (std::size_t i = 0; i < count; ++i) {
                chain.routers.push_back({"r"+std::to_string(i), static_cast<std::uint32_t>(i+1), true});
                if (i) { chain.links.push_back({"l"+std::to_string(i),i-1,i,1,1,true,
                    "out"+std::to_string(i-1),"back"+std::to_string(i)}); }
            }
            chain.prefixes.push_back({{{0x0a000000U},24},count-1,1});
            const auto long_topology = model::build_topology(std::move(chain));
            const auto long_state = spf::initial_state(long_topology);
            forwarding::Tables fib; fib.routers.resize(count);
            for (std::size_t i = 0; i < count; ++i) {
                auto hops = std::make_shared<spf::NextHopSet>();
                if (i+1 < count) { hops->push_back({i+1,i,"out"+std::to_string(i)}); }
                fib.routers[i].push_back({0,i+1 == count ? forwarding::RouteKind::connected : forwarding::RouteKind::ospf,
                                         count-i-1,count-i,count-i,hops});
            }
            analysis::DestinationAnalysis long_graph(long_topology,long_state,fib,0);
            for (std::size_t i = 0; i < count; ++i) { require(!long_graph.check(i), "long chain fails delivery"); }
            fib.routers[count-2][0].next_hops = std::make_shared<const spf::NextHopSet>(spf::NextHopSet{
                {count-3,count-3,"back"+std::to_string(count-2)}});
            analysis::DestinationAnalysis cycle_graph(long_topology,long_state,fib,0);
            const auto finding = cycle_graph.check(0);
            require(finding && finding->kind == "loop" && finding->path.size() == count,
                    "long cycle witness wrong");
            analysis::validate_witness(long_topology,long_state,fib,0,0,*finding);
        }
        analysis::AnalysisLimits analysis_limit; analysis_limit.max_edges = 0;
        bool limited = false;
        try { analysis::DestinationAnalysis graph(topology, state, baseline, prefix, analysis_limit); }
        catch (const spf::ResourceLimit&) { limited = true; }
        require(limited, "analysis edge budget accepted");
        std::size_t snapshots = 0;
        engine::replay(topology, [&](const engine::Snapshot& snapshot) {
            forwarding::validate(topology, snapshot.state, snapshot.tables);
            ++snapshots;
            if (snapshot.event && snapshot.event->sequence == 5) {
                require(!snapshot.state.administratively_up_links[topology.link_index_by_id.at("cd")],
                        "router restoration revived administratively down link");
                const auto* route = forwarding::lookup(snapshot.tables, a, prefix);
                require(route && route->next_hops->size() == 1 && route->next_hops->front().neighbor == b,
                        "restored origin has wrong branch");
            }
        });
        require(snapshots == 6, "wrong snapshot count");
        auto limits = output::SimulationLimits{};
        limits.max_snapshots = 0;
        const auto incomplete = output::simulate(loaded, limits);
        require(incomplete.exit_code == 3 && incomplete.json.find("snapshot budget exceeded") != std::string::npos,
                "budget exhaustion did not return incomplete JSON");
        for (int budget = 0; budget < 8; ++budget) {
            limits = {};
            switch (budget) {
                case 0: limits.max_assertion_evaluations = 0; break;
                case 1: limits.max_destination_analyses = 0; break;
                case 2: limits.max_analyzed_vertices = 0; break;
                case 3: limits.max_analyzed_edges = 0; break;
                case 4: limits.max_retained_routes = 0; break;
                case 5: limits.max_retained_next_hops = 0; break;
                case 6: limits.max_output_bytes = 0; break;
                case 7: limits.routing.max_route_entries = 0; break;
            }
            require(output::simulate(loaded, limits).exit_code == 3, "simulation resource failure passed");
        }
        // Candidate routing failure never invokes the observer.
        forwarding::RoutingLimits routing_limit; routing_limit.max_route_entries = 0;
        snapshots = 0; limited = false;
        try { engine::replay(topology, [&](const auto&){ ++snapshots; }, routing_limit); }
        catch (const spf::ResourceLimit&) { limited = true; }
        require(limited && snapshots == 0, "incomplete routing snapshot was published");
        // Repeated operations are no-ops, and router changes preserve admin state.
        auto mutation = spf::initial_state(topology);
        const model::Event down{"down", 1, 0, model::EventType::link_down, topology.link_index_by_id.at("ab")};
        require(engine::apply(mutation, down) && !engine::apply(mutation, down), "link-down no-op wrong");
        require(engine::apply(mutation, {"r-down",2,0,model::EventType::router_down,b}), "router down wrong");
        require(engine::apply(mutation, {"r-up",3,0,model::EventType::router_up,b}), "router up wrong");
        require(!mutation.administratively_up_links[down.target_index], "router up changed admin state");
        std::cout << "PASS replay/checker: all branches, 64 exhaustive FIBs, 20000-router chain/cycle, bad ECMP branch, cycle with exit, drops, physical certificates, witness rejection, no-ops, restoration, atomic publication, resource budgets\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL replay/checker: " << error.what() << '\n'; return 1;
    }
}
