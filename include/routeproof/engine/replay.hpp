#pragma once
#include "routeproof/forwarding/table.hpp"
#include <functional>

namespace routeproof::engine {
struct Snapshot {
    spf::PhysicalState state;
    forwarding::Tables tables;
    const model::Event* event{}; // null is the baseline
    bool applied{};
};
// Build a complete candidate before publishing it to the observer. Only the
// current and candidate routing tables coexist; observers control retention.
using Observer = std::function<void(const Snapshot&)>;
// Optional instrumentation boundary, invoked before baseline initialization or
// event mutation. It never affects routing semantics or canonical output.
using BeforeSnapshot = std::function<void()>;
void replay(const model::Topology& topology, const Observer& observe,
            const forwarding::RoutingLimits& limits = {}, const BeforeSnapshot& before = {});
// Baseline followed by one independent outage of each operational link and
// available router, in normalized link/router order. Authored events are ignored.
// The baseline remains alive throughout the sweep; generated event pointers and
// candidate snapshots are valid only during their observer invocation.
[[nodiscard]] std::size_t single_failure_count(const model::Topology& topology);
void single_failures(const model::Topology& topology, const Observer& observe,
                     const forwarding::RoutingLimits& limits = {}, const BeforeSnapshot& before = {});
// Idempotent state mutation; router events never change link administration.
[[nodiscard]] bool apply(spf::PhysicalState& state, const model::Event& event);
}
