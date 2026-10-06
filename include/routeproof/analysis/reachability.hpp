#pragma once
#include "routeproof/forwarding/table.hpp"
#include <optional>

namespace routeproof::analysis {
struct Step {
    model::RouterIndex router{};
    std::optional<spf::NextHop> hop;
    bool operator==(const Step&) const = default;
};
struct Frontier {
    model::LinkIndex link{};
    bool administratively_down{};
    bool operator==(const Frontier&) const = default;
};
struct Finding {
    std::string kind;
    std::string terminal_reason;
    std::vector<Step> path;
    std::optional<std::size_t> cycle_entry;
    std::vector<model::RouterIndex> component;
    std::vector<Frontier> frontier;
    std::vector<model::RouterIndex> unavailable_boundary_routers;
    bool operator==(const Finding&) const = default;
};
struct AnalysisLimits {
    std::size_t max_vertices{1'000'000U};
    std::size_t max_edges{4'000'000U};
};
// One destination graph and universal termination classification, reused for
// every source assertion for that destination in a snapshot.
class DestinationAnalysis {
public:
    DestinationAnalysis(const model::Topology&, const spf::PhysicalState&,
                        const forwarding::Tables&, model::PrefixIndex, const AnalysisLimits& = {});
    [[nodiscard]] std::optional<Finding> check(model::RouterIndex source) const;
private:
    struct Edge { spf::NextHop hop; std::string failure; };
    struct Node { std::string terminal; std::vector<Edge> edges; };
    const model::Topology& topology_;
    const spf::PhysicalState& state_;
    model::PrefixIndex prefix_;
    std::vector<Node> nodes_;
    std::vector<bool> safe_;
};
// Independently checks hop membership, physical state, terminal/cycle closure,
// and exact physical component/frontier evidence. Throws on invalid witnesses.
void validate_witness(const model::Topology&, const spf::PhysicalState&,
                      const forwarding::Tables&, model::PrefixIndex,
                      model::RouterIndex source, const Finding&);
}
