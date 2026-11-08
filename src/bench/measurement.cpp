#include "routeproof/bench/measurement.hpp"
#include "routeproof/version.hpp"
#include <nlohmann/json.hpp>
#include <fstream>
#include <set>
#include <sys/resource.h>
#if defined(__APPLE__)
#include <mach/mach.h>
#endif

namespace routeproof::bench {
std::uint64_t steady_rss_bytes() {
#if defined(__linux__)
    std::ifstream file("/proc/self/status");
    std::string key, line;
    while (file >> key) {
        if (key == "VmRSS:") { std::uint64_t kb{}; file >> kb; return kb * 1024U; }
        std::getline(file, line);
    }
#elif defined(__APPLE__)
    mach_task_basic_info_data_t info{};
    mach_msg_type_number_t count = MACH_TASK_BASIC_INFO_COUNT;
    if (task_info(mach_task_self(), MACH_TASK_BASIC_INFO,
                  reinterpret_cast<task_info_t>(&info), &count) == KERN_SUCCESS) {
        return info.resident_size;
    }
#endif
    return 0;
}
std::uint64_t peak_rss_bytes() {
    rusage usage{};
    if (getrusage(RUSAGE_SELF, &usage) != 0) { return 0; }
#if defined(__APPLE__)
    return static_cast<std::uint64_t>(usage.ru_maxrss);
#else
    return static_cast<std::uint64_t>(usage.ru_maxrss) * 1024U;
#endif
}
std::string sample_manifest(const input::LoadedScenario& loaded,
    const output::SimulationOutput& result, const output::SimulationMetrics& metrics,
    const std::uint64_t loaded_rss, const std::int64_t simulation_ns) {
    using Json = nlohmann::json;
    Json samples = Json::array();
    for (const auto& sample : metrics.snapshots) {
        samples.push_back(Json{{"id", sample.id}, {"applied", sample.applied},
            {"processing_ns", sample.processing_ns}, {"route_entries", sample.route_entries},
            {"next_hop_references", sample.next_hop_references},
            {"assertion_evaluations", sample.assertion_evaluations},
            {"destination_analyses", sample.destination_analyses},
            {"failed_assertions", sample.failed_assertions}, {"incomplete_assertions", sample.incomplete_assertions},
            {"available_routers", sample.available_routers}, {"retained_snapshots", sample.retained_snapshots},
            {"max_ecmp_width", sample.max_ecmp_width},
            {"steady_rss_bytes", sample.steady_rss_bytes ? Json(sample.steady_rss_bytes) : Json(nullptr)}});
    }
    std::set<model::PrefixIndex> destinations;
    for (const auto& assertion : loaded.topology.scenario.assertions) { destinations.insert(assertion.destination_prefix); }
    const auto peak = peak_rss_bytes();
    return Json{{"schema_version",1}, {"model",model_id}, {"version",version}, {"compiler",__VERSION__},
        {"build_type",ROUTEPROOF_BUILD_TYPE}, {"scenario_sha256",loaded.scenario_sha256},
        {"result_sha256",result.summary.canonical_sha256}, {"status",result.summary.status},
        {"core_processing_ns",metrics.core_processing_ns}, {"simulation_ns",simulation_ns},
        {"normalized_input_bytes",loaded.normalized_json.size()}, {"result_bytes",result.json.size() + 1},
        {"routers",loaded.topology.scenario.routers.size()}, {"physical_links",loaded.topology.scenario.links.size()},
        {"directed_arcs",loaded.topology.scenario.links.size() * 2}, {"prefixes",loaded.topology.scenario.prefixes.size()},
        {"events",loaded.topology.scenario.events.size()}, {"assertions",loaded.topology.scenario.assertions.size()},
        {"analyzed_destinations",destinations.size()}, {"retention","full canonical JSON history; current/candidate C++ tables"},
        {"loaded_rss_bytes",loaded_rss ? Json(loaded_rss) : Json(nullptr)},
        {"peak_rss_bytes",peak ? Json(peak) : Json(nullptr)},
#if defined(__linux__)
        {"rss_platform","linux"}, {"authoritative_memory",true},
#else
        {"rss_platform","macos"}, {"authoritative_memory",false},
#endif
        {"core_boundary","baseline/event physical mutation, routing and invariants, cached destination analysis, checks and witness validation; excludes parsing, canonical JSON, hashing, retention and file writes"},
        {"steady_rss_boundary","after routing/checks, before current snapshot JSON publication; previous JSON snapshots and destination cache retained"},
        {"snapshots",std::move(samples)}}.dump();
}
}
