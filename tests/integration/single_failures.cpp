#include "routeproof/engine/replay.hpp"
#include "routeproof/output/simulation.hpp"
#include <nlohmann/json.hpp>
#include <iostream>

namespace {
void require(bool value, const char* message) { if (!value) { throw std::runtime_error(message); } }
}
int main(int argc, char** argv) {
    using namespace routeproof;
    using Json = nlohmann::json;
    try {
        require(argc == 2, "expected diamond fixture");
        const auto loaded = input::load_scenario(argv[1]);
        const auto& topology = loaded.topology;
        const auto initial = spf::initial_state(topology);
        std::size_t snapshots = 0, boundaries = 0;
        engine::single_failures(topology, [&](const engine::Snapshot& snapshot) {
            forwarding::validate(topology, snapshot.state, snapshot.tables);
            std::size_t changes = 0;
            for (std::size_t i = 0; i < initial.available_routers.size(); ++i) {
                changes += initial.available_routers[i] != snapshot.state.available_routers[i];
            }
            for (std::size_t i = 0; i < initial.administratively_up_links.size(); ++i) {
                changes += initial.administratively_up_links[i] != snapshot.state.administratively_up_links[i];
            }
            require(changes == (snapshot.event ? 1U : 0U), "failures accumulated instead of resetting to baseline");
            require(!snapshot.event || snapshot.applied, "sweep generated a no-op");
            ++snapshots;
        }, {}, [&] { ++boundaries; });
        require(snapshots == 9 && boundaries == snapshots && engine::single_failure_count(topology) == 8,
                "wrong independent failure coverage");
        require(topology.scenario.events.size() == 5 && spf::initial_state(topology).available_routers == initial.available_routers,
                "sweep changed input scenario");
        const auto output = output::n_minus_one(loaded);
        const auto result = Json::parse(output.json);
        require(output.exit_code == 0 && result.at("status") == "pass", "endpoint outages failed resilient diamond");
        require(output.summary.endpoint_outages == 2 && output.summary.network_requirement_failures == 0 &&
                output.summary.redundancy_reductions == 6, "wrong diamond failure classification");
        require(result.at("resilience").at("completed_cases") == 8 && result.at("events").size() == 8,
                "authored replay events were used as the N-1 plan");
        require(output.json == output::n_minus_one(loaded).json, "N-1 output is not repeatable");
        auto modified = Json::parse(loaded.normalized_json);
        modified["assertions"] = Json::array();
        modified["events"] = Json::array();
        const auto unasserted = output::n_minus_one(input::parse_scenario(modified.dump()));
        require(unasserted.exit_code == 0 && unasserted.summary.redundancy_reductions == 6 &&
                unasserted.summary.endpoint_outages == 0, "routes without requirements were not compared");
        modified = Json::parse(loaded.normalized_json);
        modified["routers"][1]["initial_state"] = "down";
        modified["links"][3]["initial_state"] = "down";
        const auto degraded = input::parse_scenario(modified.dump());
        const auto failed = output::n_minus_one(degraded);
        const auto failed_json = Json::parse(failed.json);
        require(failed.exit_code == 1 && failed_json.at("resilience").at("baseline_failed_requirements") == Json::array({"a-to-d"}),
                "preexisting requirement failure was concealed");
        require(engine::single_failure_count(degraded.topology) == 4 &&
                failed_json.at("resilience").at("excluded_components").size() == 4,
                "initially unavailable components were not excluded");
        for (auto& router : modified["routers"]) { router["initial_state"] = "down"; }
        const auto all_down = output::n_minus_one(input::parse_scenario(modified.dump()));
        const auto all_down_json = Json::parse(all_down.json);
        require(all_down.exit_code == 1 && all_down_json.at("snapshots").size() == 1 &&
                all_down_json.at("resilience").at("requested_cases") == 0 &&
                all_down_json.at("resilience").at("cases").empty(), "empty failure plan lost baseline requirement failure");
        for (int budget = 0; budget < 11; ++budget) {
            output::SimulationLimits limits;
            switch (budget) {
                case 0: limits.max_snapshots = 8; break; // nine required, irrespective of authored events
                case 1: limits.max_assertion_evaluations = 8; break;
                case 2: limits.max_destination_analyses = 2; break; // two complete snapshots
                case 3: limits.max_analyzed_vertices = 0; break;
                case 4: limits.max_analyzed_edges = 0; break;
                case 5: limits.max_retained_routes = 0; break;
                case 6: limits.max_retained_next_hops = 0; break;
                case 7: limits.max_output_bytes = 0; break;
                case 8: limits.routing.max_route_entries = 0; break;
                case 9: limits.analysis.max_edges = 0; break;
                case 10: limits.max_output_bytes = output.json.size() / 2; break;
            }
            const auto partial = output::n_minus_one(loaded, limits);
            const auto doc = Json::parse(partial.json);
            require(partial.exit_code == 3 && doc.at("requested_snapshots") == 9, "limited sweep claimed complete coverage");
            const auto completed = doc.at("snapshots").size();
            const auto cases = completed ? completed - 1 : 0;
            require(doc.at("resilience").at("completed_cases") == cases && doc.at("events").size() == cases &&
                    doc.at("resilience").at("cases").size() == cases && doc.at("assertions").size() == completed,
                    "partial failure case was published");
            if (budget == 2) { require(completed == 2, "did not retain complete prefix of sweep"); }
            if (budget == 10) { require(completed > 0 && completed < 9, "output budget did not interrupt partial sweep"); }
        }
        // A routing failure must not publish even the baseline.
        forwarding::RoutingLimits limits; limits.max_route_entries = 0;
        snapshots = 0;
        try {
            engine::single_failures(topology, [&](const auto&) { ++snapshots; }, limits);
            throw std::runtime_error("routing limit was ignored");
        } catch (const spf::ResourceLimit&) { require(snapshots == 0, "partial baseline was published"); }
        std::cout << "PASS N-1 engine: isolated failures, endpoint scope, baseline failures, exclusions, repeatability, atomic budgets\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL N-1 engine: " << error.what() << '\n'; return 1;
    }
}
