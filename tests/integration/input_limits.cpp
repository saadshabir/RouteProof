#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>

#include "routeproof/input/scenario_loader.hpp"

namespace {

using routeproof::input::InputError;
using routeproof::input::InputLimits;
using routeproof::input::parse_scenario;

constexpr std::string_view scenario =
    R"({"schema_version":1,"name":"limit-check","model":"ospf_spf_v1","routers":[{"id":"r1","router_id":"192.0.2.1"}],"links":[],"prefixes":[{"prefix":"10.0.0.0/24","origin":"r1","stub_cost":1}],"events":[],"assertions":[]})";

void require(const bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

template <typename Action>
void rejected(Action action, const std::string_view rule, const std::size_t line = 0U,
              const std::size_t column = 0U) {
    try {
        action();
    } catch (const InputError& error) {
        require(std::string_view(error.what()).find(rule) != std::string_view::npos,
                "wrong rejection: " + std::string(error.what()));
        if (line != 0U) {
            require(error.line() == line, "wrong diagnostic line");
        }
        if (column != 0U) {
            require(error.column() == column, "wrong diagnostic column");
        }
        return;
    }
    throw std::runtime_error("input was accepted despite limit: " + std::string(rule));
}

void check_limits(const std::filesystem::path& fixture) {
    const auto baseline = parse_scenario(scenario);
    InputLimits limits;
    limits.max_bytes = scenario.size();
    limits.max_nodes = 29U;
    limits.max_collection_entries = 8U;
    limits.max_scalar_bytes = 14U;
    limits.max_nesting = 3U;
    require(
        parse_scenario(scenario, "exact.json", limits).normalized_json == baseline.normalized_json,
        "exact input limits must preserve canonical data");

    InputLimits bytes = limits;
    --bytes.max_bytes;
    rejected([&] { (void)parse_scenario(scenario, "bytes.json", bytes); }, "byte limit");
    InputLimits nodes = limits;
    --nodes.max_nodes;
    rejected([&] { (void)parse_scenario(scenario, "nodes.json", nodes); }, "node limit");
    InputLimits entries = limits;
    --entries.max_collection_entries;
    rejected([&] { (void)parse_scenario(scenario, "entries.json", entries); },
             "collection entry limit");
    entries.max_collection_entries = 1U;
    rejected([&] { (void)parse_scenario("[0,1]", "array.json", entries); },
             "collection entry limit", 1U, 4U);
    InputLimits scalars = limits;
    --scalars.max_scalar_bytes;
    rejected([&] { (void)parse_scenario(scenario, "scalar.json", scalars); }, "scalar byte limit",
             1U, 2U);
    InputLimits depth = limits;
    --depth.max_nesting;
    rejected([&] { (void)parse_scenario(scenario, "depth.json", depth); }, "input nesting");

    InputLimits yaml_nodes;
    yaml_nodes.max_nodes = 3U;
    rejected(
        [&] { (void)parse_scenario("[&empty [], *empty, *empty]", "aliases.yaml", yaml_nodes); },
        "node limit");
    InputLimits yaml_entries;
    yaml_entries.max_collection_entries = 1U;
    rejected([&] { (void)parse_scenario("[a, b]", "array.yaml", yaml_entries); },
             "collection entry limit");
    rejected([&] { (void)parse_scenario("{a: 1, b: 2}", "map.yaml", yaml_entries); },
             "collection entry limit");
    InputLimits yaml_scalar;
    yaml_scalar.max_scalar_bytes = 2U;
    rejected([&] { (void)parse_scenario("name: abc", "scalar.yaml", yaml_scalar); },
             "scalar byte limit");
    InputLimits yaml_depth;
    yaml_depth.max_nesting = 2U;
    rejected([&] { (void)parse_scenario("[[[0]]]", "deep.yaml", yaml_depth); }, "input nesting");

    InputLimits file_limits;
    file_limits.max_bytes = static_cast<std::size_t>(std::filesystem::file_size(fixture));
    const auto loaded = routeproof::input::load_scenario(fixture, file_limits);
    require(!loaded.scenario_sha256.empty(), "file at exact byte limit must load");
    --file_limits.max_bytes;
    rejected([&] { (void)routeproof::input::load_scenario(fixture, file_limits); }, "byte limit");

    rejected([&] { (void)parse_scenario("&a [*a]", "cycle.yaml"); }, "recursive YAML aliases", 1U,
             5U);
    rejected([&] { (void)parse_scenario("&a {child: &b [*a]}", "cycle.yaml"); },
             "recursive YAML aliases");
    rejected([&] { (void)parse_scenario("---\n{}\n---\n[", "multiple.yaml"); },
             "exactly one YAML document");
    rejected(
        [&] { (void)parse_scenario("{\n  \"name\":1,\n  \"n\\u0061me\":2\n}", "duplicate.json"); },
        "duplicate mapping key", 3U, 3U);
    rejected([&] { (void)parse_scenario("{\n  \"schema_version\": \"1\"\n}", "mark.json"); },
             "missing required field", 1U, 1U);
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc != 2) {
        return 2;
    }
    try {
        check_limits(argv[1]);
        std::cout << "PASS input budgets, exact boundaries, alias cycles, and JSON source marks\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL bounded input: " << error.what() << '\n';
        return 1;
    }
}
