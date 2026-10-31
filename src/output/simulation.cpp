#include "routeproof/output/simulation.hpp"
#include "baseline_document.hpp"
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
// Result files are untrusted even when their unkeyed digests match. JSON's
// default UTF-8 output leaves C1 terminal controls and bidi overrides intact.
std::string display_json(const Json& value) { return value.dump(-1, ' ', true); }
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
Json resilience_plan(const model::Topology& topology) {
    const auto& scenario = topology.scenario;
    Json excluded = Json::array();
    for (const auto& link : scenario.links) {
        if (!link.initially_admin_up || !scenario.routers[link.a].initially_available ||
            !scenario.routers[link.b].initially_available) {
            excluded.push_back(Json{{"kind", "link"}, {"target", link.id},
                {"reason", !link.initially_admin_up ? "already_down" : "endpoint_unavailable"}});
        }
    }
    for (const auto& router : scenario.routers) {
        if (!router.initially_available) {
            excluded.push_back(Json{{"kind", "router"}, {"target", router.id}, {"reason", "already_down"}});
        }
    }
    return Json{{"redundancy_definition", "ecmp_first_hops"},
        {"requested_cases", engine::single_failure_count(topology)}, {"completed_cases", 0},
        {"authored_events_ignored", scenario.events.size()}, {"excluded_components", std::move(excluded)},
        {"baseline_failed_requirements", Json::array()}, {"cases", Json::array()}};
}
Json resilience_case(const model::Topology& topology, const forwarding::Tables& baseline,
                     const engine::Snapshot& snapshot, const Json& assertions, const std::string& id) {
    const auto& scenario = topology.scenario;
    const auto& event = *snapshot.event;
    const bool link = event.type == model::EventType::link_down;
    Json result{{"snapshot_id", id},
        {"failure", Json{{"kind", link ? "link" : "router"},
            {"target", link ? scenario.links[event.target_index].id : scenario.routers[event.target_index].id}}},
        {"failed_requirements", Json::array()}, {"preexisting_failures", Json::array()},
        {"endpoint_outages", Json::array()}, {"unreachable_routes", Json::array()},
        {"redundancy_reductions", Json::array()}};
    for (const auto& record : assertions) {
        const auto& scope = record.at("failure_scope");
        if (scope == "network") { result["failed_requirements"].push_back(record.at("assertion_id")); }
        else if (scope == "baseline") { result["preexisting_failures"].push_back(record.at("assertion_id")); }
        else if (scope == "source_outage" || scope == "destination_outage") {
            result["endpoint_outages"].push_back(Json{{"assertion_id", record.at("assertion_id")}, {"kind", scope}});
        }
    }
    for (model::RouterIndex source = 0; source < baseline.routers.size(); ++source) {
        if (!snapshot.state.available_routers[source]) { continue; }
        for (const auto& route : baseline.routers[source]) {
            const auto& prefix = scenario.prefixes[route.prefix];
            if (!snapshot.state.available_routers[prefix.origin]) { continue; }
            const auto* remaining = forwarding::lookup(snapshot.tables, source, route.prefix);
            const auto before = route.next_hops->size();
            const auto after = remaining ? remaining->next_hops->size() : 0;
            Json identity{{"source", scenario.routers[source].id}, {"prefix", prefix.network.to_string()},
                          {"origin", scenario.routers[prefix.origin].id}};
            if (!remaining) { result["unreachable_routes"].push_back(identity); }
            if (before > 1 && after < before) {
                identity.update(Json{{"baseline_next_hops", before}, {"remaining_next_hops", after},
                    {"redundancy_lost", after < 2}, {"reachable", remaining != nullptr}});
                result["redundancy_reductions"].push_back(std::move(identity));
            }
        }
    }
    return result;
}
SimulationOutput simulate_impl(const input::LoadedScenario& loaded, const SimulationLimits& limits,
                              SimulationMetrics* metrics, bool single_failures) {
    using Clock = std::chrono::steady_clock;
    Clock::time_point start;
    SimulationSummary summary;
    if (metrics) { *metrics = {}; }
    const auto normalized = Json::parse(loaded.normalized_json);
    Json result{{"schema_version", 1}, {"model", model_id}, {"scenario_name", loaded.topology.scenario.name},
        {"scenario_sha256", loaded.scenario_sha256}, {"events_sha256", digest(normalized.at("events"))},
        {"assertions_sha256", digest(normalized.at("assertions"))}, {"status", "pass"},
        {"events", Json::array()}, {"snapshots", Json::array()}, {"assertions", Json::array()}};
    const auto count = single_failures ? engine::single_failure_count(loaded.topology) : loaded.topology.scenario.events.size();
    if (single_failures) {
        result["analysis_mode"] = "n-1";
        result["resilience"] = resilience_plan(loaded.topology);
        summary.analysis_mode = "n-1";
        summary.requested_cases = count;
    }
    // single_failures retains its baseline for the duration of all callbacks.
    const forwarding::Tables* baseline_tables = nullptr;
    std::set<std::string> baseline_failures;
    std::size_t evaluations = 0, analyses = 0, vertices = 0, edges = 0, routes = 0, hops = 0, bytes = result.dump().size() + 512;
    try {
        // Preflight the requested coverage rather than run an arbitrarily long
        // trace until its budget is exhausted. Missing coverage stays explicit.
        if (count >= limits.max_snapshots) { throw spf::ResourceLimit("snapshot budget exceeded"); }
        if (!loaded.topology.scenario.assertions.empty() &&
            count + 1 > limits.max_assertion_evaluations / loaded.topology.scenario.assertions.size()) {
            throw spf::ResourceLimit("assertion evaluation budget exceeded");
        }
        const auto run = single_failures ? engine::single_failures : engine::replay;
        run(loaded.topology, [&](const engine::Snapshot& snapshot) {
            SnapshotSample sample;
            if (metrics) {
                sample.processing_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - start).count();
            }
            charge(routes, snapshot.tables.route_entries, limits.max_retained_routes, "retained route budget exceeded");
            charge(hops, snapshot.tables.next_hop_references, limits.max_retained_next_hops, "retained next-hop budget exceeded");
            auto baseline = detail::baseline_document(loaded, snapshot.state, snapshot.tables);
            Json physical = Json::object();
            physical["available_routers"] = std::move(baseline.at("available_routers"));
            physical["administratively_up_links"] = std::move(baseline.at("administratively_up_links"));
            physical["routes"] = std::move(baseline.at("routes"));
            std::string hash;
            std::size_t physical_bytes;
            {
                const auto serialized = physical.dump();
                physical_bytes = serialized.size();
                hash = picosha2::hash256_hex_string(serialized);
            }
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
            Json identity{{"id", id}, {"sha256", hash},
                {"sequence", snapshot.event ? Json(snapshot.event->sequence) : Json(nullptr)},
                {"event_id", snapshot.event ? Json(snapshot.event->id) : Json(nullptr)}};
            // The two objects have disjoint keys. Joining them replaces the
            // adjacent braces with a comma: exactly the previous byte charge,
            // without serializing every route a second time for its size.
            charge(bytes, physical_bytes + identity.dump().size() - 1 + 256,
                   limits.max_output_bytes, "canonical output byte budget exceeded");
            physical.update(identity);
            Json assertions = Json::array();
            Json baseline_failed_requirements = Json::array();
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
                if (single_failures) {
                    std::string scope = "none";
                    if (finding) {
                        if (!snapshot.event) {
                            scope = "baseline";
                            baseline_failed_requirements.push_back(assertion.id);
                        } else if (snapshot.event->type == model::EventType::router_down &&
                                   snapshot.event->target_index == assertion.source) {
                            scope = "source_outage";
                        } else if (finding->kind == "destination_down" && snapshot.event->type == model::EventType::router_down && snapshot.event->target_index ==
                                   loaded.topology.scenario.prefixes[assertion.destination_prefix].origin) {
                            scope = "destination_outage";
                        } else { scope = baseline_failures.contains(assertion.id) ? "baseline" : "network"; }
                        record["findings"][0]["reproduction_argv"][1] = "n-1";
                    }
                    record["failure_scope"] = scope;
                }
                charge(bytes, record.dump().size() + 128 + record.at("findings").size() * 128,
                       limits.max_output_bytes, "canonical output byte budget exceeded");
                assertions.push_back(std::move(record));
            }
            Json failure_case;
            if (single_failures) {
                // Endpoint shutdown is expected in a router sweep. Only the
                // baseline and failures with surviving endpoints affect status.
                status = "pass";
                for (const auto& record : assertions) {
                    const bool endpoint = record.at("failure_scope") == "source_outage" ||
                                          record.at("failure_scope") == "destination_outage";
                    if (!endpoint && status_code(record.at("status").get<std::string>()) > status_code(status)) {
                        status = record.at("status").get<std::string>();
                    }
                }
                if (snapshot.event) {
                    failure_case = resilience_case(loaded.topology, *baseline_tables, snapshot, assertions, id);
                    charge(bytes, failure_case.dump().size() + 128, limits.max_output_bytes,
                           "canonical output byte budget exceeded");
                } else {
                    charge(bytes, baseline_failed_requirements.dump().size(), limits.max_output_bytes,
                           "canonical output byte budget exceeded");
                }
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
            if (single_failures) {
                if (snapshot.event) {
                    summary.network_requirement_failures += failure_case.at("failed_requirements").size();
                    summary.endpoint_outages += failure_case.at("endpoint_outages").size();
                    summary.redundancy_reductions += failure_case.at("redundancy_reductions").size();
                    result["resilience"]["cases"].push_back(std::move(failure_case));
                    result["resilience"]["completed_cases"] = result["resilience"]["cases"].size();
                } else {
                    baseline_tables = &snapshot.tables;
                    for (const auto& assertion : baseline_failed_requirements) {
                        baseline_failures.insert(assertion.get<std::string>());
                    }
                    summary.baseline_requirement_failures = baseline_failed_requirements.size();
                    result["resilience"]["baseline_failed_requirements"] = std::move(baseline_failed_requirements);
                }
            }
            if (snapshot.event) {
                result["events"].push_back(std::move(event));
                if (snapshot.applied) { ++summary.applied_events; }
                else { ++summary.noop_events; }
            }
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
        result["requested_snapshots"] = count + 1;
    }
    const auto hash = digest(result);
    result["canonical_sha256"] = hash;
    for (auto& assertion : result["assertions"]) {
        for (auto& finding : assertion["findings"]) { finding["result_sha256"] = hash; }
    }
    summary.status = result.at("status").get<std::string>();
    summary.canonical_sha256 = hash;
    summary.completed_snapshots = result.at("snapshots").size();
    const auto code = status_code(summary.status);
    return {result.dump(), code, std::move(summary)};
}
}
SimulationOutput simulate(const input::LoadedScenario& loaded, const SimulationLimits& limits,
                          SimulationMetrics* metrics) {
    return simulate_impl(loaded, limits, metrics, false);
}
SimulationOutput n_minus_one(const input::LoadedScenario& loaded, const SimulationLimits& limits) {
    return simulate_impl(loaded, limits, nullptr, true);
}
std::string run_manifest(const input::LoadedScenario& loaded, const SimulationOutput& output,
                         const std::filesystem::path& source, const std::int64_t simulation_ns) {
    const auto& summary = output.summary;
    Json result{{"schema_version",1}, {"model",model_id}, {"version",version}, {"compiler",__VERSION__},
        {"scenario_sha256",loaded.scenario_sha256}, {"result_sha256",summary.canonical_sha256},
        {"source_path",source.string()}, {"simulation_ns",simulation_ns},
        {"status",summary.status}, {"completed_snapshots",summary.completed_snapshots},
        {"applied_events",summary.applied_events}, {"noop_events",summary.noop_events},
        {"measurement_boundary","replay, routing, analysis, witness validation, canonical serialization; excludes parsing and file writes"}};
    if (!summary.analysis_mode.empty()) { result["analysis_mode"] = summary.analysis_mode; }
    return result.dump();
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
        const bool single_failures = result.contains("analysis_mode");
        if ((single_failures && result.at("analysis_mode") != "n-1") ||
            single_failures != result.contains("resilience")) {
            throw input::InputError("unsupported result analysis mode");
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
        std::map<std::string, const Json*> failure_cases;
        std::set<std::string> baseline_failures;
        if (single_failures) {
            const auto& resilience = result.at("resilience");
            const auto& cases = resilience.at("cases");
            const auto& completed = resilience.at("completed_cases");
            const auto& requested = resilience.at("requested_cases");
            if (!cases.is_array() || !completed.is_number_unsigned() || !requested.is_number_unsigned() ||
                completed != cases.size() || completed.get<std::uint64_t>() > requested.get<std::uint64_t>() ||
                (exit_code != 3 && completed != requested) ||
                cases.size() != result.at("events").size() ||
                snapshots.size() != (snapshots.empty() ? 0 : cases.size() + 1) ||
                resilience.at("redundancy_definition") != "ecmp_first_hops" ||
                (exit_code == 3 && result.at("requested_snapshots") != requested.get<std::uint64_t>() + 1)) {
                throw input::InputError("N-1 coverage mismatch");
            }
            for (const auto& id : resilience.at("baseline_failed_requirements")) {
                if (!baseline_failures.insert(id.get<std::string>()).second) {
                    throw input::InputError("duplicate N-1 baseline failure");
                }
            }
            std::set<std::string> observed_baseline_failures;
            for (const auto& record : result.at("assertions")) {
                if (record.at("snapshot_id") == "baseline" && status_code(record.at("status").get<std::string>()) != 0) {
                    observed_baseline_failures.insert(record.at("assertion_id").get<std::string>());
                }
            }
            if (baseline_failures != observed_baseline_failures) {
                throw input::InputError("N-1 baseline failure summary mismatch");
            }
            std::set<std::pair<std::string, std::string>> targets;
            for (std::size_t index = 0; index < cases.size(); ++index) {
                const auto& value = cases[index];
                const auto id = value.at("snapshot_id").get<std::string>();
                const auto snapshot = snapshots.find(id);
                const auto kind = value.at("failure").at("kind").get<std::string>();
                const auto target = value.at("failure").at("target").get<std::string>();
                const auto& event = result.at("events")[index];
                if (snapshot == snapshots.end() || !failure_cases.emplace(id, &value).second ||
                    (kind != "link" && kind != "router") || !targets.emplace(kind, target).second ||
                    event.at("type") != kind + "_down" || event.at("disposition") != "applied" ||
                    event.at("sequence") != index + 1 || event.at("id") != snapshot->second->at("event_id") ||
                    event.at("sequence") != snapshot->second->at("sequence") ||
                    event.at("snapshot_sha256") != snapshot->second->at("sha256")) {
                    throw input::InputError("N-1 failure/snapshot reference mismatch");
                }
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
            bool endpoint = false;
            if (single_failures) {
                const auto scope = record.at("failure_scope").get<std::string>();
                const bool baseline = baseline_failures.contains(record.at("assertion_id").get<std::string>());
                const bool initial = record.at("snapshot_id") == "baseline";
                const auto failure_case = failure_cases.find(record.at("snapshot_id").get<std::string>());
                if (!initial && failure_case == failure_cases.end()) {
                    throw input::InputError("N-1 assertion scope mismatch");
                }
                std::string expected_scope = "none";
                if (record_status != 0) {
                    expected_scope = initial || baseline ? "baseline" : "network";
                    const auto& finding = findings.at(0);
                    if (!initial) {
                        const auto& failure = failure_case->second->at("failure");
                        if (failure.at("kind") == "router") {
                            if (finding.at("kind") == "source_down" && failure.at("target") == finding.at("source")) {
                                expected_scope = "source_outage";
                            } else if (finding.at("kind") == "destination_down" && failure.at("target") == finding.at("destination_origin")) {
                                expected_scope = "destination_outage";
                            }
                        }
                    }
                }
                if (scope != expected_scope) { throw input::InputError("N-1 assertion scope mismatch"); }
                endpoint = expected_scope == "source_outage" || expected_scope == "destination_outage";
                if (endpoint && findings.size() != 1) { throw input::InputError("N-1 endpoint outage mismatch"); }
            } else if (record.contains("failure_scope")) { throw input::InputError("unexpected assertion failure scope"); }
            if (!endpoint) { assertion_status = std::max(assertion_status, record_status); }
            if (record.at("assertion_id") != assertion) { continue; }
            found = true;
            output << display_json(record.at("snapshot_id")) << ": " << record.at("status").get<std::string>();
            if (single_failures) { output << " (" << display_json(record.at("failure_scope")) << ')'; }
            output << '\n';
            for (const auto& finding : record.at("findings")) {
                output << "  " << display_json(finding.at("kind")) << ": " << display_json(finding.at("source"))
                       << " -> " << display_json(finding.at("destination")) << " (all ECMP branches required)\n";
                output << "  path: ";
                for (const auto& step : finding.at("path")) {
                    output << display_json(step.at("router"));
                    const auto& hop = step.at("next_hop");
                    if (hop.contains("link")) { output << " --" << display_json(hop.at("interface")) << "--> "; }
                    else { output << " [" << display_json(hop.at("action")) << "]"; }
                }
                output << '\n';
                if (finding.contains("reachable_component")) {
                    output << "  component: " << display_json(finding.at("reachable_component"))
                           << "; origin: " << display_json(finding.at("destination_origin"))
                           << "; frontier: " << display_json(finding.at("frontier")) << '\n';
                }
                if (finding.contains("cycle_entry")) { output << "  cycle enters at step " << display_json(finding.at("cycle_entry")) << '\n'; }
            }
        }
        if (exit_code != 3 && exit_code != assertion_status) {
            throw input::InputError("result status/assertion outcomes mismatch");
        }
        if (!found && result.at("status") != "incomplete") { throw input::InputError("unknown assertion in result"); }
        if (result.contains("incomplete_reason")) { output << "incomplete: " << display_json(result.at("incomplete_reason")) << '\n'; }
        return {output.str(), exit_code, {}};
    } catch (const Json::exception& error) {
        throw input::InputError(std::string("invalid result JSON: ") + error.what());
    }
}
}
