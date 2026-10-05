#pragma once
#include "routeproof/input/scenario_loader.hpp"
#include "routeproof/forwarding/table.hpp"
namespace routeproof::output {
// Diagnostic baseline format; events/assertions are not evaluated.
[[nodiscard]] std::string baseline_json(const input::LoadedScenario& loaded,
                                        const spf::PhysicalState& state,
                                        const forwarding::Tables& tables);
}
