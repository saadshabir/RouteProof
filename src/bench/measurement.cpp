#include "routeproof/bench/measurement.hpp"
#include "routeproof/version.hpp"
#include <nlohmann/json.hpp>
#include <fstream>
#include <set>
#include <sys/resource.h>
#include <sys/wait.h>
#include <spawn.h>
#include <cerrno>
#include <cstring>
#include <csignal>
#include <stdexcept>
#if defined(__APPLE__)
#include <mach/mach.h>
#endif

extern char** environ;
namespace routeproof::bench {
namespace {
volatile std::sig_atomic_t harness_child = 0;
void forward_signal(int value) {
    if (harness_child > 0) { kill(static_cast<pid_t>(harness_child), value); }
}
}
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
    const auto canonical = Json::parse(result.json);
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
        {"result_sha256",canonical.at("canonical_sha256")}, {"status",canonical.at("status")},
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
int run_harness(int argc, char* argv[]) {
    std::vector<std::string> args{ROUTEPROOF_PYTHON, ROUTEPROOF_BENCH_SCRIPT, "--binary", argv[0]};
    for (int index = 2; index < argc; ++index) { args.emplace_back(argv[index]); }
    std::vector<char*> pointers;
    for (auto& arg : args) { pointers.push_back(arg.data()); }
    pointers.push_back(nullptr);
    struct sigaction handler{}, old_interrupt{}, old_terminate{};
    handler.sa_handler = forward_signal;
    sigemptyset(&handler.sa_mask);
    sigaction(SIGINT, &handler, &old_interrupt);
    sigaction(SIGTERM, &handler, &old_terminate);
    auto restore = [&] {
        harness_child = 0;
        sigaction(SIGINT, &old_interrupt, nullptr);
        sigaction(SIGTERM, &old_terminate, nullptr);
    };
    pid_t child{};
    const auto error = posix_spawn(&child, ROUTEPROOF_PYTHON, nullptr, nullptr, pointers.data(), environ);
    if (error != 0) { restore(); throw std::runtime_error(std::string("benchmark harness launch failed: ") + std::strerror(error)); }
    harness_child = child;
    int status{};
    while (waitpid(child, &status, 0) < 0) {
        if (errno != EINTR) { restore(); throw std::runtime_error("benchmark harness wait failed"); }
    }
    restore();
    return WIFEXITED(status) ? WEXITSTATUS(status) : 3;
}
}
