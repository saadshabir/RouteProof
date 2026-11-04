#include "routeproof/output/comparison.hpp"
#include "result_document.hpp"
#include "routeproof/output/simulation.hpp"
#include "routeproof/version.hpp"

#include <algorithm>
#include <array>
#include <iterator>
#include <map>
#include <optional>
#include <set>
#include <tuple>
#include <utility>
#include <vector>
#include <nlohmann/json.hpp>

namespace routeproof::output {
namespace {
using Json = nlohmann::json;
using Text = std::string_view;
using RouteKey = std::pair<Text, Text>;
using Routes = std::map<RouteKey, const Json*>;
using Assertions = std::map<Text, const Json*>;
using Hop = std::tuple<Text, Text, Text>;
using Hops = std::set<Hop>;

constexpr std::array route_categories{
    "added_routes", "withdrawn_routes", "metric_changes", "ecmp_changes", "route_attribute_changes"
};
enum RouteChange { added, withdrawn, metric, ecmp, attributes };

Text field(const Json& value, const char* key) {
    return value.at(key).get_ref<const std::string&>();
}

const Json& array(const Json& value, const char* key) {
    const auto& items = value.at(key);
    if (!items.is_array()) { throw input::InputError(std::string(key) + " must be an array"); }
    return items;
}

struct Snapshot {
    const Json* document;
    Assertions assertions;
};

struct Run {
    const Json& document;
    std::vector<Snapshot> snapshots;
    std::map<Text, std::size_t> indices;

    explicit Run(const Json& result) : document(result) {
        for (const auto& snapshot : array(result, "snapshots")) {
            if (!indices.emplace(field(snapshot, "id"), snapshots.size()).second) {
                throw input::InputError("duplicate snapshot ID");
            }
            snapshots.push_back({&snapshot, {}});
        }
        for (const auto& record : array(result, "assertions")) {
            auto& assertions = snapshots.at(indices.at(field(record, "snapshot_id"))).assertions;
            if (!assertions.emplace(field(record, "assertion_id"), &record).second) {
                throw input::InputError("duplicate assertion in snapshot");
            }
        }
        if (!snapshots.empty()) {
            const auto& baseline = snapshots.front().assertions;
            for (const auto& snapshot : snapshots) {
                if (snapshot.assertions.size() != baseline.size() ||
                    !std::equal(baseline.begin(), baseline.end(), snapshot.assertions.begin(),
                        [](const auto& left, const auto& right) { return left.first == right.first; })) {
                    throw input::InputError("assertion coverage differs across snapshots");
                }
            }
        }
    }

    const Snapshot& select(Text id) const {
        const auto it = indices.find(id);
        if (it == indices.end()) {
            if (incomplete()) {
                throw spf::ResourceLimit("snapshot " + std::string(id) + " unavailable in incomplete result: " +
                    std::string(field(document, "incomplete_reason")));
            }
            throw input::InputError("unknown snapshot ID: " + std::string(id));
        }
        return snapshots[it->second];
    }

    Json identity() const {
        Json value{{"scenario_name", document.at("scenario_name")}, {"scenario_sha256", document.at("scenario_sha256")},
            {"assertions_sha256", document.at("assertions_sha256")},
            {"result_sha256", document.at("canonical_sha256")}, {"status", document.at("status")},
            {"analysis_mode", document.value("analysis_mode", "replay")},
            {"completed_snapshots", snapshots.size()},
            {"requested_snapshots", document.value("requested_snapshots", snapshots.size())}};
        if (document.contains("incomplete_reason")) { value["incomplete_reason"] = document.at("incomplete_reason"); }
        return value;
    }

    Json selection(const Snapshot& snapshot) const {
        auto value = identity();
        value["run_status"] = value.at("status");
        value.erase("status");
        value["snapshot_id"] = snapshot.document->at("id");
        value["snapshot_sha256"] = snapshot.document->at("sha256");
        value["event_id"] = snapshot.document->at("event_id");
        return value;
    }

    bool incomplete() const { return document.at("status") == "incomplete"; }
};

Routes index_routes(const Snapshot& snapshot) {
    Routes routes;
    for (const auto& route : array(*snapshot.document, "routes")) {
        const RouteKey key{field(route, "router"), field(route, "prefix")};
        if (!routes.emplace(key, &route).second) {
            throw input::InputError("duplicate router/prefix route in snapshot");
        }
    }
    return routes;
}

template<typename Map, typename Visit>
void visit_union(const Map& before, const Map& after, Visit visit) {
    auto left = before.begin(), right = after.begin();
    while (left != before.end() || right != after.end()) {
        if (right == after.end() || (left != before.end() && left->first < right->first)) {
            visit(left->first, left->second, nullptr);
            ++left;
        } else if (left == before.end() || right->first < left->first) {
            visit(right->first, nullptr, right->second);
            ++right;
        } else {
            visit(left->first, left->second, right->second);
            ++left;
            ++right;
        }
    }
}

Hops hop_set(const Json& rows) {
    Hops hops;
    for (const auto& row : rows) {
        hops.emplace(field(row, "neighbor"), field(row, "link"), field(row, "interface"));
    }
    return hops;
}

Json hop_difference(const Hops& before, const Hops& after) {
    std::vector<Hop> difference;
    std::set_difference(before.begin(), before.end(), after.begin(), after.end(), std::back_inserter(difference));
    Json rows = Json::array();
    for (const auto& [neighbor, link, interface] : difference) {
        rows.push_back({{"neighbor", neighbor}, {"link", link}, {"interface", interface}});
    }
    return rows;
}

struct RouteBudget {
    // A baseline may be revisited for every N-1 case. Bound the total
    // number of route and next-hop references inspected in one report.
    std::size_t remaining = 64'000'000U;

    void charge(std::size_t count) {
        if (count > remaining) { throw spf::ResourceLimit("comparison work budget exceeded"); }
        remaining -= count;
    }
};

struct RouteImpact {
    std::array<std::size_t, route_categories.size()> counts{};
    std::set<Text> routers, prefixes;

    void record(RouteChange change, const RouteKey& key) {
        ++counts[change];
        routers.insert(key.first);
        prefixes.insert(key.second);
    }

    Json count_json() const {
        Json value = Json::object();
        for (std::size_t i = 0; i < counts.size(); ++i) { value[route_categories[i]] = counts[i]; }
        return value;
    }

    void accumulate(const RouteImpact& impact) {
        for (std::size_t i = 0; i < counts.size(); ++i) { counts[i] += impact.counts[i]; }
        routers.insert(impact.routers.begin(), impact.routers.end());
        prefixes.insert(impact.prefixes.begin(), impact.prefixes.end());
    }
};

void compare_routes(const Routes& before, const Routes& after, RouteBudget& budget,
                    RouteImpact& impact, Json* details = nullptr) {
    budget.charge(before.size() + after.size());
    if (details) {
        for (const auto* category : route_categories) { (*details)[category] = Json::array(); }
    }
    visit_union(before, after, [&](const RouteKey& key, const Json* left, const Json* right) {
        const auto record = [&](RouteChange change, auto fields) {
            impact.record(change, key);
            if (details) {
                auto row = fields();
                row["router"] = key.first;
                row["prefix"] = key.second;
                (*details)[route_categories[change]].push_back(std::move(row));
            }
        };
        if (!left || !right) {
            const auto& route = left ? *left : *right;
            record(left ? withdrawn : added, [&] {
                return Json{{"origin", route.at("origin")}, {"kind", route.at("kind")}, {"metric", route.at("metric")}};
            });
            return;
        }
        const auto metric_fields = [](const Json& row) {
            return Json{{"metric", row.at("metric")}, {"distance_to_origin", row.at("distance_to_origin")},
                {"protocol_cost", row.at("protocol_cost")}};
        };
        if (left->at("metric") != right->at("metric") ||
            left->at("distance_to_origin") != right->at("distance_to_origin") ||
            left->at("protocol_cost") != right->at("protocol_cost")) {
            record(metric, [&] { return Json{{"before", metric_fields(*left)}, {"after", metric_fields(*right)}}; });
        }
        if (left->at("origin") != right->at("origin") || left->at("kind") != right->at("kind")) {
            const auto route_attributes = [](const Json& row) {
                return Json{{"origin", row.at("origin")}, {"kind", row.at("kind")}};
            };
            record(attributes, [&] {
                return Json{{"before", route_attributes(*left)}, {"after", route_attributes(*right)}};
            });
        }
        const auto& left_hops = array(*left, "next_hops");
        const auto& right_hops = array(*right, "next_hops");
        budget.charge(left_hops.size() + right_hops.size());
        if (left_hops == right_hops) { return; }
        const auto old_set = hop_set(left_hops), new_set = hop_set(right_hops);
        if (old_set != new_set) {
            record(ecmp, [&] {
                return Json{{"before_count", old_set.size()}, {"after_count", new_set.size()},
                    {"removed", hop_difference(old_set, new_set)}, {"added", hop_difference(new_set, old_set)}};
            });
        }
    });
}

Json finding_context(const Json& record) {
    const auto& finding = record.at("findings").at(0);
    Json value{{"source", finding.at("source")}, {"destination", finding.at("destination")},
        {"destination_prefix", finding.at("destination_prefix")}, {"kind", finding.at("kind")}};
    if (record.contains("failure_scope")) { value["failure_scope"] = record.at("failure_scope"); }
    return value;
}

struct AssertionChanges {
    Json newly_failing = Json::array();
    Json recovered = Json::array();
    Json other = Json::array();
};

AssertionChanges compare_assertions(const Snapshot& before, const Snapshot& after, bool detailed) {
    AssertionChanges changes;
    visit_union(before.assertions, after.assertions, [&](Text id, const Json* left, const Json* right) {
        const Text old_status = left ? field(*left, "status") : "absent";
        const Text new_status = right ? field(*right, "status") : "absent";
        if (old_status == new_status) { return; }
        if (old_status == "pass" && new_status == "fail") {
            if (detailed) {
                auto failure = finding_context(*right);
                failure["assertion_id"] = id;
                changes.newly_failing.push_back(std::move(failure));
            } else {
                changes.newly_failing.push_back(id);
            }
        } else if (old_status == "fail" && new_status == "pass") {
            changes.recovered.push_back(id);
        } else {
            changes.other.push_back({{"assertion_id", id}, {"before", old_status}, {"after", new_status}});
        }
    });
    return changes;
}

Json load(const std::filesystem::path& path, bool scenarios) {
    return scenarios ? Json::parse(simulate(input::load_scenario(path)).json) : detail::read_result(path);
}

Report finish(const Json& report, bool incomplete) {
    auto bytes = report.dump(-1, ' ', true);
    bytes += '\n';
    return {std::move(bytes), incomplete ? 3 : 0};
}

struct AssertionImpact {
    const Json* first_issue{};
    Text first_failure, last_failure;
    std::size_t failed{}, incomplete{};
};

Json timeline_event(const Run& run, std::size_t index, bool sweep) {
    const auto& events = array(run.document, "events");
    const auto& event = events.at(index - 1);
    const auto& sequence = event.at("sequence");
    if (!sequence.is_number_unsigned() || sequence == 0 ||
        (index > 1 && sequence <= events.at(index - 2).at("sequence"))) {
        throw input::InputError("event sequences must be positive and strictly increasing");
    }
    const auto& snapshot = *run.snapshots[index].document;
    if (event.at("id") != snapshot.at("event_id") || sequence != snapshot.at("sequence") ||
        event.at("snapshot_sha256") != snapshot.at("sha256")) {
        throw input::InputError("event/snapshot order mismatch");
    }
    Json identity{{"id", event.at("id")}, {"type", event.at("type")}, {"sequence", sequence},
        {"at_ns", event.at("at_ns")}, {"disposition", event.at("disposition")}};
    if (sweep) { identity["failure"] = run.document.at("resilience").at("cases").at(index - 1).at("failure"); }
    return identity;
}
}  // namespace

Report compare(const std::filesystem::path& before, const std::filesystem::path& after,
               Text from, Text to, bool scenarios) {
    try {
        const auto first = load(before, scenarios);
        const auto second = before == after ? std::nullopt : std::optional{load(after, scenarios)};
        const Run left(first);
        const auto other = second ? std::optional<Run>{std::in_place, *second} : std::nullopt;
        const auto& right = other ? *other : left;
        const auto& old_snapshot = left.select(from);
        const auto& new_snapshot = right.select(to);
        Json report{{"schema_version", 1}, {"model", model_id}, {"kind", "semantic_comparison"},
            {"before", left.selection(old_snapshot)}, {"after", right.selection(new_snapshot)}};
        RouteImpact impact;
        RouteBudget budget;
        compare_routes(index_routes(old_snapshot), index_routes(new_snapshot), budget, impact, &report);
        report["route_counts"] = impact.count_json();
        auto changes = compare_assertions(old_snapshot, new_snapshot, true);
        report["newly_failing_assertions"] = std::move(changes.newly_failing);
        report["recovered_assertions"] = std::move(changes.recovered);
        report["other_assertion_changes"] = std::move(changes.other);
        return finish(report, left.incomplete() || right.incomplete());
    } catch (const Json::exception& error) {
        throw input::InputError(std::string("invalid comparison input: ") + error.what());
    }
}

Report summarize(const std::filesystem::path& file) {
    try {
        const auto document = detail::read_result(file);
        const Run run(document);
        const bool sweep = document.contains("analysis_mode");
        if (array(document, "events").size() != (run.snapshots.empty() ? 0 : run.snapshots.size() - 1) ||
            (!run.snapshots.empty() && run.snapshots.front().document->at("id") != "baseline")) {
            throw input::InputError("result timeline is missing its baseline or events");
        }
        Json report = run.identity();
        report.update(Json{{"schema_version", 1}, {"model", model_id}, {"kind", "run_summary"},
            {"comparison_basis", sweep ? "baseline" : "previous_snapshot"}});
        Json timeline = Json::array();
        Json evaluations{{"pass", 0}, {"fail", 0}, {"incomplete", 0}};
        std::map<Text, std::size_t> failure_scopes;
        std::map<Text, AssertionImpact> affected_assertions;
        std::size_t regressions = 0, recoveries = 0;
        RouteImpact total;
        RouteBudget budget;
        Routes reference;
        for (std::size_t i = 0; i < run.snapshots.size(); ++i) {
            const auto& snapshot = run.snapshots[i];
            const auto snapshot_id = field(*snapshot.document, "id");
            for (const auto& [id, record] : snapshot.assertions) {
                const auto status = field(*record, "status");
                auto& count = evaluations.at(status);
                count = count.get<std::size_t>() + 1;
                if (status == "pass") { continue; }
                if (sweep) { ++failure_scopes[field(*record, "failure_scope")]; }
                auto& impact = affected_assertions[id];
                if (!impact.first_issue) { impact.first_issue = record; }
                if (status == "fail") {
                    if (impact.failed++ == 0) { impact.first_failure = snapshot_id; }
                    impact.last_failure = snapshot_id;
                } else {
                    ++impact.incomplete;
                }
            }
            auto current = index_routes(snapshot);
            if (i != 0) {
                const auto& previous = run.snapshots[sweep ? 0 : i - 1];
                auto event = timeline_event(run, i, sweep);
                RouteImpact impact;
                compare_routes(reference, current, budget, impact);
                total.accumulate(impact);
                auto changes = compare_assertions(previous, snapshot, false);
                regressions += changes.newly_failing.size();
                recoveries += changes.recovered.size();
                timeline.push_back({{"before_snapshot_id", previous.document->at("id")},
                    {"after_snapshot_id", snapshot_id}, {"event", std::move(event)},
                    {"route_counts", impact.count_json()}, {"newly_failing_assertions", std::move(changes.newly_failing)},
                    {"recovered_assertions", std::move(changes.recovered)},
                    {"other_assertion_changes", std::move(changes.other)}});
            }
            if (!sweep || i == 0) { reference = std::move(current); }
        }
        report["route_counts"] = total.count_json();
        report["affected_routers"] = total.routers;
        report["affected_prefixes"] = total.prefixes;
        report["assertion_evaluations"] = std::move(evaluations);
        if (sweep) { report["assertion_failure_scopes"] = failure_scopes; }
        report["newly_failing_assertion_transitions"] = regressions;
        report["recovered_assertion_transitions"] = recoveries;
        report["affected_assertions"] = Json::array();
        for (const auto& [id, impact] : affected_assertions) {
            auto issue = finding_context(*impact.first_issue);
            issue["snapshot_id"] = impact.first_issue->at("snapshot_id");
            report["affected_assertions"].push_back({{"assertion_id", id},
                {"first_issue", std::move(issue)}, {"failed_snapshots", impact.failed},
                {"incomplete_snapshots", impact.incomplete},
                {"first_failure_snapshot_id", impact.failed ? Json(impact.first_failure) : Json(nullptr)},
                {"last_failure_snapshot_id", impact.failed ? Json(impact.last_failure) : Json(nullptr)}});
        }
        report["timeline"] = std::move(timeline);
        return finish(report, run.incomplete());
    } catch (const Json::exception& error) {
        throw input::InputError(std::string("invalid summary input: ") + error.what());
    }
}
}  // namespace routeproof::output
