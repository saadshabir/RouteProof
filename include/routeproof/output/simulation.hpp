#pragma once
#include "routeproof/input/scenario_loader.hpp"
#include "routeproof/analysis/reachability.hpp"

namespace routeproof::output {
struct SimulationLimits {
    forwarding::RoutingLimits routing;
    analysis::AnalysisLimits analysis;
    std::size_t max_snapshots{10'000U};
    std::size_t max_assertion_evaluations{1'000'000U};
    std::size_t max_destination_analyses{100'000U};
    std::size_t max_analyzed_vertices{10'000'000U};
    std::size_t max_analyzed_edges{40'000'000U};
    std::size_t max_retained_routes{2'000'000U};
    std::size_t max_retained_next_hops{8'000'000U};
    std::size_t max_output_bytes{64U * 1024U * 1024U};
};
struct SimulationOutput { std::string json; int exit_code{}; };
[[nodiscard]] SimulationOutput simulate(const input::LoadedScenario&, const SimulationLimits& = {});
// Noncanonical provenance; paths and monotonic samples never enter result.json.
[[nodiscard]] std::string run_manifest(const input::LoadedScenario&, const SimulationOutput&,
    const std::filesystem::path& source, std::int64_t simulation_ns);
// Bounded strict JSON read, digest/reference verification, concise explanations.
[[nodiscard]] SimulationOutput explain(const std::filesystem::path&, const std::string& assertion);
}
