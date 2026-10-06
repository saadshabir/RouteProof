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
void replay(const model::Topology& topology, const Observer& observe,
            const forwarding::RoutingLimits& limits = {});
// Idempotent state mutation; router events never change link administration.
[[nodiscard]] bool apply(spf::PhysicalState& state, const model::Event& event);
}
