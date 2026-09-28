#include "routeproof/input/scenario_loader.hpp"
#include "routeproof/version.hpp"

#include <iostream>
#include <string_view>

namespace {

void print_help(std::ostream& output) {
    output << "RouteProof " << routeproof::version << "\n"
           << "Usage: routeproof --help | --version | validate <scenario.yaml> [--normalized]\n\n"
           << "Commands:\n"
           << "  validate FILE              Validate and summarize a scenario\n"
           << "  validate FILE --normalized Print canonical normalized scenario JSON\n";
}

void print_version(std::ostream& output) {
    output << "RouteProof " << routeproof::version << "\n"
           << "model: " << routeproof::model_id << "\n"
           << "scenario schema: " << routeproof::scenario_schema_version << "\n"
           << "result schema: " << routeproof::result_schema_version << "\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string_view{argv[1]} == "--version") {
        print_version(std::cout);
        return 0;
    }

    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        print_help(std::cout);
        return 0;
    }

    if (argc == 1) {
        print_help(std::cerr);
        return 2;
    }

    if (std::string_view{argv[1]} == "validate") {
        if ((argc != 3 && argc != 4) ||
            (argc == 4 && std::string_view{argv[3]} != "--normalized")) {
            print_help(std::cerr);
            return 2;
        }
        try {
            const routeproof::input::LoadedScenario loaded =
                routeproof::input::load_scenario(argv[2]);
            if (argc == 4) {
                std::cout << loaded.normalized_json << '\n';
                return 0;
            }
            std::cout << "valid\n"
                      << "name: " << loaded.topology.scenario.name << '\n'
                      << "model: " << routeproof::model_id << '\n'
                      << "schema_version: " << routeproof::scenario_schema_version << '\n'
                      << "routers: " << loaded.topology.scenario.routers.size() << '\n'
                      << "links: " << loaded.topology.scenario.links.size() << '\n'
                      << "prefixes: " << loaded.topology.scenario.prefixes.size() << '\n'
                      << "events: " << loaded.topology.scenario.events.size() << '\n'
                      << "assertions: " << loaded.topology.scenario.assertions.size() << '\n'
                      << "scenario_sha256: " << loaded.scenario_sha256 << '\n';
            return 0;
        } catch (const routeproof::input::InputError& error) {
            std::cerr << "routeproof: " << error.what() << '\n';
            return 2;
        } catch (const std::exception& error) {
            std::cerr << "routeproof: validation failed: " << error.what() << '\n';
            return 2;
        }
    }

    std::cerr << "routeproof: command not implemented in Phase 1: "
              << argv[1] << "\n";
    return 3;
}
