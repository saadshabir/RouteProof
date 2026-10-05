#pragma once
#include "routeproof/spf/shortest_paths.hpp"
#include <memory>

namespace routeproof::forwarding {
enum class RouteKind { connected, ospf };
struct Route {
    model::PrefixIndex prefix{};
    RouteKind kind{};
    spf::Distance distance_to_origin{};
    spf::Distance metric{};
    spf::Distance protocol_cost{};
    std::shared_ptr<const spf::NextHopSet> next_hops;
};
struct Tables {
    // Per-router entries sorted by prefix index for deterministic lookup.
    std::vector<std::vector<Route>> routers;
    std::size_t route_entries{};
    std::size_t next_hop_references{};
};
struct RoutingLimits {
    std::size_t max_route_entries{1'000'000U};
    std::size_t max_next_hop_references{4'000'000U};
    std::size_t max_scratch_next_hops{4'000'000U};
};
[[nodiscard]] const Route* lookup(const Tables& tables, model::RouterIndex router,
                                  model::PrefixIndex prefix);
[[nodiscard]] const Route* lookup(const model::Topology& topology, const Tables& tables,
                                  model::RouterIndex router, model::IPv4Address destination);
[[nodiscard]] Tables compute(const model::Topology& topology, const spf::PhysicalState& state,
                             const RoutingLimits& limits = {});
// Checks every selected edge for strict rank decrease and shortest-path equality.
void validate(const model::Topology& topology, const spf::PhysicalState& state,
              const Tables& tables);
}  // namespace routeproof::forwarding
