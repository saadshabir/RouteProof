#pragma once

#include "routeproof/model/topology.hpp"

#include <compare>
#include <limits>
#include <stdexcept>

namespace routeproof::spf {
using Distance = std::uint64_t;
inline constexpr Distance infinity = std::numeric_limits<Distance>::max();

struct NextHop {
    model::RouterIndex neighbor{};
    model::LinkIndex link{};
    std::string outgoing_interface;
    auto operator<=>(const NextHop&) const = default;
};
using NextHopSet = std::vector<NextHop>;

struct PhysicalState {
    std::vector<bool> available_routers;
    std::vector<bool> administratively_up_links;
};
[[nodiscard]] PhysicalState initial_state(const model::Topology& topology);

class ResourceLimit final : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// Reused for each source; no all-pairs trees or complete paths are retained.
struct Workspace {
    std::vector<Distance> distances;
    std::vector<NextHopSet> first_hops;
    std::vector<model::RouterIndex> order;
};

// Requires the validated, positive-cost topology produced by the input module.
void compute(const model::Topology& topology, const PhysicalState& state,
             model::RouterIndex source, Workspace& workspace,
             std::size_t max_scratch_next_hops = 4'000'000U);
[[nodiscard]] Distance checked_add(Distance left, Distance right);
}  // namespace routeproof::spf
