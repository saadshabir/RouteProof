#include "routeproof/output/simulation.hpp"
#include "routeproof/output/baseline.hpp"
#include "routeproof/engine/replay.hpp"
#include "routeproof/version.hpp"
#include "routeproof/bench/measurement.hpp"
#include <chrono>
#include <nlohmann/json.hpp>
#include <picosha2.h>
#include <fstream>
#include <algorithm>
#include <map>
#include <memory>
#include <set>
#include <sstream>

namespace routeproof::output {
namespace {
using Json = nlohmann::json;
std::string digest(const Json& value) { return picosha2::hash256_hex_string(value.dump()); }
void charge(std::size_t& used, std::size_t count, std::size_t limit, const char* message) {
    if (used > limit || count > limit - used) { throw spf::ResourceLimit(message); }
    used += count;
}
Json hop_json(const model::Topology& topology, const spf::NextHop& hop) {
    return Json{{"neighbor", topology.scenario.routers.at(hop.neighbor).id},
        {"link", topology.scenario.links.at(hop.link).id}, {"interface", hop.outgoing_interface}};
}
Json finding_json(const input::LoadedScenario& loaded, const engine::Snapshot& snapshot,
                  const std::string& hash, const model::ReachabilityAssertion& assertion,
                  const analysis::Finding& finding) {
    const auto& topology = loaded.topology;
    const auto& scenario = topology.scenario;
    Json path = Json::array();
    for (const auto& step : finding.path) {
        const auto* route = forwarding::lookup(snapshot.tables, step.router, assertion.destination_prefix);
        Json decision = route ? Json{{"kind", route->kind == forwarding::RouteKind::connected ? "connected" : "ospf"},
                                     {"metric", route->metric}} : Json{{"kind", "absent"}};
        // Malformed out-of-domain hops are library-only incomplete findings.
        Json hop = step.hop && step.hop->neighbor < scenario.routers.size() && step.hop->link < scenario.links.size()
            ? hop_json(topology, *step.hop) : Json{{"action", finding.kind}};
        path.push_back(Json{{"router", scenario.routers[step.router].id},
                            {"next_hop", std::move(hop)}, {"route_decision", std::move(decision)}});
    }
    Json result{{"assertion_id", assertion.id}, {"kind", finding.kind},
        {"source", scenario.routers[assertion.source].id}, {"destination", assertion.destination.to_string()},
        {"destination_prefix", scenario.prefixes[assertion.destination_prefix].network.to_string()},
        {"destination_origin", scenario.routers[scenario.prefixes[assertion.destination_prefix].origin].id},
        {"ecmp_quantifier", "all"}, {"event_id", snapshot.event ? Json(snapshot.event->id) : Json(nullptr)},
        {"sequence", snapshot.event ? Json(snapshot.event->sequence) : Json(nullptr)},
        {"scenario_sha256", loaded.scenario_sha256}, {"snapshot_sha256", hash}, {"path", std::move(path)},
        {"message", "Universal ECMP delivery failed: " + finding.terminal_reason},
        {"terminal_reason", finding.terminal_reason},
        {"reproduction_argv", Json::array({"routeproof", "simulate", "<scenario>", "--out", "<output>"})}};
    if (finding.cycle_entry) { result["cycle_entry"] = *finding.cycle_entry; }
    if (finding.kind == "no_route") {
        const auto origin = scenario.prefixes[assertion.destination_prefix].origin;
        if (std::find(finding.component.begin(), finding.component.end(), origin) == finding.component.end()) {
            result["unreachable_origin"] = scenario.routers[origin].id;
        } else {
            result["message"] = "Forwarding action missing within a physically connected component";
        }
        result["reachable_component"] = Json::array(); result["frontier"] = Json::array();
        for (const auto router : finding.component) { result["reachable_component"].push_back(scenario.routers[router].id); }
        for (const auto& frontier : finding.frontier) {
            result["frontier"].push_back(Json{{"kind", "link"}, {"link", scenario.links[frontier.link].id},
                {"state", frontier.administratively_down ? "administratively_down" : "endpoint_unavailable"}});
        }
        for (const auto router : finding.unavailable_boundary_routers) {
            result["frontier"].push_back(Json{{"kind", "router"}, {"router", scenario.routers[router].id}, {"state", "unavailable"}});
        }
    }
    return result;
}
int status_code(const std::string& status) {
    if (status == "pass") { return 0; }
    if (status == "fail") { return 1; }
    if (status == "incomplete") { return 3; }
    throw input::InputError("invalid result status");
}
}
SimulationOutput simulate(const input::LoadedScenario& loaded, const SimulationLimits& limits,
                          SimulationMetrics* metrics) {
    using Clock = std::chrono::steady_clock;
    Clock::time_point start;
    if (metrics) { *metrics = {}; }
    const auto normalized = Json::parse(loaded.normalized_json);
    Json result{{"schema_version", 1}, {"model", model_id}, {"scenario_name", loaded.topology.scenario.name},
        {"scenario_sha256", loaded.scenario_sha256}, {"events_sha256", digest(normalized.at("events"))},
        {"assertions_sha256", digest(normalized.at("assertions"))}, {"status", "pass"},
        {"events", Json::array()}, {"snapshots", Json::array()}, {"assertions", Json::array()}};
    std::size_t evaluations = 0, analyses = 0, vertices = 0, edges = 0, routes = 0, hops = 0, bytes = result.dump().size() + 512;
    try {
        // Preflight the requested coverage rather than run an arbitrarily long
        // trace until its budget is exhausted. Missing coverage stays explicit.
        const auto count = loaded.topology.scenario.events.size();
        if (count >= limits.max_snapshots) { throw spf::ResourceLimit("snapshot budget exceeded"); }
        if (!loaded.topology.scenario.assertions.empty() &&
            count + 1 > limits.max_assertion_evaluations / loaded.topology.scenario.assertions.size()) {
            throw spf::ResourceLimit("assertion evaluation budget exceeded");
        }
        engine::replay(loaded.topology, [&](const engine::Snapshot& snapshot) {
            SnapshotSample sample;
            if (metrics) {
                sample.processing_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - start).count();
            }
            charge(routes, snapshot.tables.route_entries, limits.max_retained_routes, "retained route budget exceeded");
            charge(hops, snapshot.tables.next_hop_references, limits.max_retained_next_hops, "retained next-hop budget exceeded");
            auto baseline = Json::parse(baseline_json(loaded, snapshot.state, snapshot.tables));
            Json physical{{"available_routers", baseline.at("available_routers")},
                {"administratively_up_links", baseline.at("administratively_up_links")}, {"routes", baseline.at("routes")}};
            const auto hash = digest(physical);
            const auto id = snapshot.event ? "event-" + std::to_string(snapshot.event->sequence) : "baseline";
            if (metrics) {
                sample.id = id; sample.applied = snapshot.applied;
                sample.route_entries = snapshot.tables.route_entries;
                sample.next_hop_references = snapshot.tables.next_hop_references;
                for (const auto& table : snapshot.tables.routers) {
                    for (const auto& route : table) { sample.max_ecmp_width = std::max(sample.max_ecmp_width, route.next_hops->size()); }
                }
                sample.available_routers = std::count(snapshot.state.available_routers.begin(), snapshot.state.available_routers.end(), true);
            }
            physical["id"] = id; physical["sha256"] = hash;
            physical["sequence"] = snapshot.event ? Json(snapshot.event->sequence) : Json(nullptr);
            physical["event_id"] = snapshot.event ? Json(snapshot.event->id) : Json(nullptr);
            charge(bytes, physical.dump().size() + 256, limits.max_output_bytes, "canonical output byte budget exceeded");
            Json assertions = Json::array();
            std::map<model::PrefixIndex, std::unique_ptr<analysis::DestinationAnalysis>> cache;
            std::string status = "pass";
            for (const auto& assertion : loaded.topology.scenario.assertions) {
                const auto analysis_start = metrics ? Clock::now() : Clock::time_point{};
                charge(evaluations, 1, limits.max_assertion_evaluations, "assertion evaluation budget exceeded");
                auto& graph = cache[assertion.destination_prefix];
                if (!graph) {
                    charge(analyses, 1, limits.max_destination_analyses, "destination analysis budget exceeded");
                    charge(vertices, loaded.topology.scenario.routers.size(), limits.max_analyzed_vertices, "analyzed vertex budget exceeded");
                    // Conservative edge charge includes all prefixes; the graph
                    // also enforces its exact per-destination edge budget.
                    charge(edges, snapshot.tables.next_hop_references, limits.max_analyzed_edges, "analyzed edge budget exceeded");
                    graph = std::make_unique<analysis::DestinationAnalysis>(loaded.topology, snapshot.state,
                        snapshot.tables, assertion.destination_prefix, limits.analysis);
                }
                auto finding = graph->check(assertion.source);
                if (finding) {
                    analysis::validate_witness(loaded.topology, snapshot.state, snapshot.tables,
                                              assertion.destination_prefix, assertion.source, *finding);
                }
                if (metrics) {
                    sample.processing_ns += std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - analysis_start).count();
                    ++sample.assertion_evaluations;
                    if (finding) {
                        if (finding->kind == "incomplete") { ++sample.incomplete_assertions; }
                        else { ++sample.failed_assertions; }
                    }
                }
                Json record{{"assertion_id", assertion.id}, {"snapshot_id", id}, {"snapshot_sha256", hash},
                    {"status", "pass"}, {"findings", Json::array()}};
                if (finding) {
                    record["status"] = finding->kind == "incomplete" ? "incomplete" : "fail";
                    record["findings"].push_back(finding_json(loaded, snapshot, hash, assertion, *finding));
                    if (status != "incomplete") { status = record.at("status").get<std::string>(); }
                }
                charge(bytes, record.dump().size() + 128 + record.at("findings").size() * 128,
                       limits.max_output_bytes, "canonical output byte budget exceeded");
                assertions.push_back(std::move(record));
            }
            Json event;
            if (snapshot.event) {
                const auto& value = *snapshot.event;
                event = Json{{"id", value.id}, {"sequence", value.sequence}, {"at_ns", value.at_ns},
                    {"type", model::event_type_name(value.type)}, {"disposition", snapshot.applied ? "applied" : "noop"},
                    {"snapshot_sha256", hash}, {"route_entries", snapshot.tables.route_entries},
                    {"next_hop_references", snapshot.tables.next_hop_references}};
            }
            charge(bytes, event.dump().size(), limits.max_output_bytes, "canonical output byte budget exceeded");
            if (metrics) {
                sample.destination_analyses = cache.size();
                sample.retained_snapshots = result["snapshots"].size();
                sample.steady_rss_bytes = bench::steady_rss_bytes();
            }
            // Publish a snapshot and all of its assertions together. A failed
            // candidate contributes neither an event nor partial assertions.
            result["snapshots"].push_back(std::move(physical));
            if (snapshot.event) { result["events"].push_back(std::move(event)); }
            for (auto& record : assertions) { result["assertions"].push_back(std::move(record)); }
            if (status != "pass" && result["status"] != "incomplete") { result["status"] = status; }
            if (metrics) {
                metrics->core_processing_ns += sample.processing_ns;
                metrics->snapshots.push_back(std::move(sample));
            }
        }, limits.routing, metrics ? engine::BeforeSnapshot([&] { start = Clock::now(); }) : engine::BeforeSnapshot{});
    } catch (const std::exception& error) {
        result["status"] = "incomplete";
        result["incomplete_reason"] = error.what();
    }
    if (result["status"] == "incomplete") {
        if (!result.contains("incomplete_reason")) { result["incomplete_reason"] = "incomplete reachability analysis"; }
        result["completed_snapshots"] = result["snapshots"].size();
        result["requested_snapshots"] = loaded.topology.scenario.events.size() + 1;
    }
    const auto hash = digest(result);
    result["canonical_sha256"] = hash;
    for (auto& assertion : result["assertions"]) {
        for (auto& finding : assertion["findings"]) { finding["result_sha256"] = hash; }
    }
    return {result.dump(), status_code(result.at("status").get<std::string>())};
}
std::string run_manifest(const input::LoadedScenario& loaded, const SimulationOutput& output,
                         const std::filesystem::path& source, const std::int64_t simulation_ns) {
    const auto result = Json::parse(output.json);
    std::size_t applied = 0, noop = 0;
    for (const auto& event : result.at("events")) {
        if (event.at("disposition") == "applied") { ++applied; } else { ++noop; }
    }
    return Json{{"schema_version",1}, {"model",model_id}, {"version",version}, {"compiler",__VERSION__},
        {"scenario_sha256",loaded.scenario_sha256}, {"result_sha256",result.at("canonical_sha256")},
        {"source_path",source.string()}, {"simulation_ns",simulation_ns},
        {"status",result.at("status")}, {"completed_snapshots",result.at("snapshots").size()},
        {"applied_events",applied}, {"noop_events",noop},
        {"measurement_boundary","replay, routing, analysis, witness validation, canonical serialization; excludes parsing and file writes"}}.dump();
}
SimulationOutput explain(const std::filesystem::path& file, const std::string& assertion) {
    std::ifstream stream(file, std::ios::binary);
    if (!stream) { throw input::InputError("cannot read result file"); }
    std::string content;
    char buffer[8192];
    while (stream.read(buffer, sizeof(buffer)) || stream.gcount() != 0) {
        if (content.size() + static_cast<std::size_t>(stream.gcount()) > 64U * 1024U * 1024U) {
            throw input::InputError("result input byte budget exceeded");
        }
        content.append(buffer, static_cast<std::size_t>(stream.gcount()));
    }
    if (stream.bad()) { throw input::InputError("result read failed"); }
    try {
        std::vector<std::set<std::string>> keys;
        auto result = Json::parse(content, [&](int depth, Json::parse_event_t event, Json& parsed) {
            if (depth > 128) { throw input::InputError("result nesting budget exceeded"); }
            if (event == Json::parse_event_t::object_start) { keys.emplace_back(); }
            if (event == Json::parse_event_t::key && !keys.back().insert(parsed.get<std::string>()).second) {
                throw input::InputError("duplicate result JSON key");
            }
            if (event == Json::parse_event_t::object_end) { keys.pop_back(); }
            return true;
        });
        if (result.at("schema_version") != 1 || result.at("model") != model_id) {
            throw input::InputError("unsupported result schema/model");
        }
        const auto exit_code = status_code(result.at("status").get<std::string>());
        const auto hash = result.at("canonical_sha256").get<std::string>();
        auto projection = result; projection.erase("canonical_sha256");
        for (auto& record : projection.at("assertions")) {
            for (auto& finding : record.at("findings")) {
                if (finding.at("result_sha256") != hash) { throw input::InputError("finding result digest mismatch"); }
                finding.erase("result_sha256");
            }
        }
        if (digest(projection) != hash) { throw input::InputError("canonical result digest mismatch"); }
        if (!result.at("snapshots").is_array() || !result.at("assertions").is_array()) {
            throw input::InputError("result snapshots/assertions must be arrays");
        }
        if (exit_code == 3) {
            if (!result.at("incomplete_reason").is_string() || result.at("incomplete_reason").get<std::string>().empty()) {
                throw input::InputError("incomplete result must include a nonempty reason");
            }
            auto coverage_count = [&](const char* key) {
                const auto& value = result.at(key);
                if (!value.is_number_integer() || (!value.is_number_unsigned() && value.get<std::int64_t>() < 0)) {
                    throw input::InputError("incomplete coverage counts must be nonnegative integers");
                }
                return value.get<std::uint64_t>();
            };
            const auto completed = coverage_count("completed_snapshots");
            const auto requested = coverage_count("requested_snapshots");
            if (completed != result.at("snapshots").size() || requested == 0 || completed > requested) {
                throw input::InputError("incomplete result coverage mismatch");
            }
        } else if (result.at("snapshots").empty()) {
            throw input::InputError("complete result must contain a snapshot");
        }
        std::map<std::string, const Json*> snapshots;
        for (const auto& snapshot : result.at("snapshots")) {
            const auto id = snapshot.at("id").get<std::string>();
            const auto snapshot_hash = snapshot.at("sha256").get<std::string>();
            Json physical{{"available_routers", snapshot.at("available_routers")},
                {"administratively_up_links", snapshot.at("administratively_up_links")}, {"routes", snapshot.at("routes")}};
            if (digest(physical) != snapshot_hash || !snapshots.emplace(id, &snapshot).second) {
                throw input::InputError("snapshot digest/identity mismatch");
            }
        }
        std::ostringstream output;
        bool found = false;
        int assertion_status = 0;
        for (const auto& record : result.at("assertions")) {
            const auto snapshot = snapshots.find(record.at("snapshot_id").get<std::string>());
            if (snapshot == snapshots.end() || snapshot->second->at("sha256") != record.at("snapshot_sha256")) {
                throw input::InputError("assertion snapshot reference mismatch");
            }
            const auto record_status = status_code(record.at("status").get<std::string>());
            const auto& findings = record.at("findings");
            if (!findings.is_array() || (record_status == 0) != findings.empty()) {
                throw input::InputError("assertion status/findings mismatch");
            }
            int finding_status = 0;
            for (const auto& finding : findings) {
                const auto kind = finding.at("kind").get<std::string>();
                if (kind != "source_down" && kind != "destination_down" && kind != "no_route" &&
                    kind != "link_down" && kind != "next_hop_down" && kind != "loop" && kind != "incomplete") {
                    throw input::InputError("unsupported finding kind");
                }
                finding_status = std::max(finding_status, kind == "incomplete" ? 3 : 1);
                if (finding.at("assertion_id") != record.at("assertion_id") ||
                    finding.at("snapshot_sha256") != snapshot->second->at("sha256") ||
                    finding.at("scenario_sha256") != result.at("scenario_sha256") ||
                    finding.at("event_id") != snapshot->second->at("event_id") ||
                    finding.at("sequence") != snapshot->second->at("sequence")) {
                    throw input::InputError("finding assertion/snapshot/scenario/event reference mismatch");
                }
                if (finding.at("terminal_reason") != kind) { throw input::InputError("finding terminal reason mismatch"); }
            }
            if (record_status != finding_status) { throw input::InputError("assertion status/finding kind mismatch"); }
            assertion_status = std::max(assertion_status, record_status);
            if (record.at("assertion_id") != assertion) { continue; }
            found = true;
            output << record.at("snapshot_id").dump() << ": " << record.at("status").get<std::string>() << '\n';
            for (const auto& finding : record.at("findings")) {
                output << "  " << finding.at("kind").dump() << ": " << finding.at("source").dump()
                       << " -> " << finding.at("destination").dump() << " (all ECMP branches required)\n";
                output << "  path: ";
                for (const auto& step : finding.at("path")) {
                    output << step.at("router").dump();
                    const auto& hop = step.at("next_hop");
                    if (hop.contains("link")) { output << " --" << hop.at("interface").dump() << "--> "; }
                    else { output << " [" << hop.at("action").dump() << "]"; }
                }
                output << '\n';
                if (finding.contains("reachable_component")) {
                    output << "  component: " << finding.at("reachable_component").dump()
                           << "; origin: " << finding.at("destination_origin").dump()
                           << "; frontier: " << finding.at("frontier").dump() << '\n';
                }
                if (finding.contains("cycle_entry")) { output << "  cycle enters at step " << finding.at("cycle_entry") << '\n'; }
            }
        }
        if (exit_code != 3 && exit_code != assertion_status) {
            throw input::InputError("result status/assertion outcomes mismatch");
        }
        if (!found && result.at("status") != "incomplete") { throw input::InputError("unknown assertion in result"); }
        if (result.contains("incomplete_reason")) { output << "incomplete: " << result.at("incomplete_reason").dump() << '\n'; }
        return {output.str(), exit_code};
    } catch (const Json::exception& error) {
        throw input::InputError(std::string("invalid result JSON: ") + error.what());
    }
}
}
