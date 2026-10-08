#pragma once

#include "routeproof/output/baseline.hpp"
#include <nlohmann/json_fwd.hpp>

namespace routeproof::output::detail {
// Shared by the diagnostic CLI and replay; serialization happens at the caller.
[[nodiscard]] nlohmann::json baseline_document(const input::LoadedScenario& loaded,
    const spf::PhysicalState& state, const forwarding::Tables& tables);
}
