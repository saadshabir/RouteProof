#include "routeproof/engine/replay.hpp"
#include <utility>

namespace routeproof::engine {
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
        candidate.tables = forwarding::compute(topology, candidate.state, limits);
        current = std::move(candidate);
        observe(current);
    }
}
}
