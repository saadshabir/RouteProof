#include "routeproof/input/scenario_loader.hpp"
#include "routeproof/forwarding/table.hpp"
#include "routeproof/output/baseline.hpp"
#include "routeproof/output/simulation.hpp"
#include <chrono>
#include <iostream>

int main(int argc, char** argv) {
    if (argc != 2) { return 2; }
    const auto loaded = routeproof::input::load_scenario(argv[1]);
    const auto& topology = loaded.topology;
    const auto state = routeproof::spf::initial_state(topology);
    const auto tables = routeproof::forwarding::compute(topology, state);
    std::size_t sink = 0;
    auto measure = [&](const char* name, auto work) {
        work();
        const auto start = std::chrono::steady_clock::now();
        for (int repeat = 0; repeat < 20; ++repeat) { work(); }
        const auto elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now() - start).count();
        std::cout << name << "=" << elapsed / 20 << " ns\n";
    };
    measure("all_source_spf", [&] {
        routeproof::spf::Workspace workspace;
        for (std::size_t source = 0; source < tables.routers.size(); ++source) {
            routeproof::spf::compute(topology, state, source, workspace);
            sink += workspace.order.size();
        }
    });
    measure("table_compute", [&] { sink += routeproof::forwarding::compute(topology, state).route_entries; });
    measure("table_validation", [&] { routeproof::forwarding::validate(topology, state, tables); });
    measure("baseline_serialization", [&] { sink += routeproof::output::baseline_json(loaded, state, tables).size(); });
    measure("simulation", [&] { sink += routeproof::output::simulate(loaded).json.size(); });
    std::cout << "sink=" << sink << '\n';
}
