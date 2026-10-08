#pragma once
#include "routeproof/output/simulation.hpp"

namespace routeproof::bench {
// Bytes on both supported POSIX platforms; zero is unavailable, never a sample.
[[nodiscard]] std::uint64_t steady_rss_bytes();
[[nodiscard]] std::uint64_t peak_rss_bytes();
[[nodiscard]] std::string sample_manifest(const input::LoadedScenario&,
    const output::SimulationOutput&, const output::SimulationMetrics&,
    std::uint64_t loaded_rss, std::int64_t simulation_ns);
// Launch the Python orchestrator with argv (no shell interpretation).
int run_harness(int argc, char* argv[]);
}
