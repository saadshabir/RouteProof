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
struct SimulationSummary {
    std::string status;
    std::string canonical_sha256;
    std::size_t completed_snapshots{}, applied_events{}, noop_events{};
    std::string analysis_mode; // empty for authored replay, "n-1" for a sweep
    std::size_t requested_cases{}, baseline_requirement_failures{}, network_requirement_failures{};
    std::size_t endpoint_outages{}, redundancy_reductions{};
};
struct SimulationOutput {
    std::string json;
    int exit_code{};
    SimulationSummary summary; // populated by simulate/n_minus_one; explain returns text only
};
struct SnapshotSample {
    std::string id;
    bool applied{};
    std::int64_t processing_ns{};
    std::size_t route_entries{}, next_hop_references{}, assertion_evaluations{}, destination_analyses{};
    std::size_t failed_assertions{}, incomplete_assertions{}, available_routers{};
    std::size_t retained_snapshots{};
    std::size_t max_ecmp_width{};
    std::uint64_t steady_rss_bytes{}; // zero means unavailable
};
struct SimulationMetrics {
    std::vector<SnapshotSample> snapshots;
    std::int64_t core_processing_ns{};
};
// Metrics exclude canonical JSON construction, hashing, retention, parsing and
// file writes. Enabling them leaves canonical output byte-identical.
[[nodiscard]] SimulationOutput simulate(const input::LoadedScenario&, const SimulationLimits& = {},
                                        SimulationMetrics* metrics = nullptr);
// Independent outages from the initial state. Endpoint outages are reported but
// excluded from the sweep's requirement status; baseline failures still fail.
// Redundancy compares ECMP first-hop counts for every baseline route.
[[nodiscard]] SimulationOutput n_minus_one(const input::LoadedScenario&, const SimulationLimits& = {});
// Noncanonical provenance; paths and monotonic samples never enter result.json.
[[nodiscard]] std::string run_manifest(const input::LoadedScenario&, const SimulationOutput&,
    const std::filesystem::path& source, std::int64_t simulation_ns);
// Bounded strict JSON read, digest/reference verification, concise explanations.
[[nodiscard]] SimulationOutput explain(const std::filesystem::path&, const std::string& assertion);
}
