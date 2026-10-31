#include "routeproof/engine/replay.hpp"
#include <utility>

namespace routeproof::engine {
namespace {
bool operational(const model::Scenario& scenario, const model::Link& link) {
    return link.initially_admin_up && scenario.routers[link.a].initially_available &&
           scenario.routers[link.b].initially_available;
}
}
bool apply(spf::PhysicalState& state, const model::Event& event) {
    const bool up = event.type == model::EventType::link_up || event.type == model::EventType::router_up;
    auto& values = event.type == model::EventType::link_up || event.type == model::EventType::link_down
                       ? state.administratively_up_links : state.available_routers;
    const bool changed = values.at(event.target_index) != up;
    values[event.target_index] = up;
    return changed;
}
void replay(const model::Topology& topology, const Observer& observe,
            const forwarding::RoutingLimits& limits, const BeforeSnapshot& before) {
    if (before) { before(); }
    Snapshot current;
    current.state = spf::initial_state(topology);
    current.tables = forwarding::compute(topology, current.state, limits);
    observe(current);
    for (const auto& event : topology.scenario.events) {
        if (before) { before(); }
        Snapshot candidate;
        candidate.state = current.state;
        candidate.applied = apply(candidate.state, event);
        candidate.event = &event;
        if (!candidate.applied) {
            // State and tables are unchanged, but the observer still evaluates
            // and publishes this event's distinct snapshot and assertions.
            current.event = &event;
            current.applied = false;
            observe(current);
            continue;
        }
        candidate.tables = forwarding::compute(topology, candidate.state, limits);
        current = std::move(candidate);
        observe(current);
    }
}
std::size_t single_failure_count(const model::Topology& topology) {
    std::size_t count = 0;
    for (const auto& link : topology.scenario.links) { count += operational(topology.scenario, link); }
    for (const auto& router : topology.scenario.routers) { count += router.initially_available; }
    return count;
}
void single_failures(const model::Topology& topology, const Observer& observe,
                     const forwarding::RoutingLimits& limits, const BeforeSnapshot& before) {
    if (before) { before(); }
    Snapshot baseline;
    baseline.state = spf::initial_state(topology);
    baseline.tables = forwarding::compute(topology, baseline.state, limits);
    observe(baseline);
    std::uint64_t sequence = 0;
    auto fail = [&](model::EventType type, std::size_t target) {
        if (before) { before(); }
        const model::Event event{"n-1-" + std::to_string(++sequence), sequence, 0, type, target};
        Snapshot candidate;
        candidate.state = baseline.state;
        candidate.event = &event;
        candidate.applied = apply(candidate.state, event);
        candidate.tables = forwarding::compute(topology, candidate.state, limits);
        observe(candidate);
    };
    for (model::LinkIndex link = 0; link < topology.scenario.links.size(); ++link) {
        if (operational(topology.scenario, topology.scenario.links[link])) {
            fail(model::EventType::link_down, link);
        }
    }
    for (model::RouterIndex router = 0; router < topology.scenario.routers.size(); ++router) {
        if (baseline.state.available_routers[router]) { fail(model::EventType::router_down, router); }
    }
}
}
