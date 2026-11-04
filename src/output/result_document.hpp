#pragma once

#include <filesystem>
#include <nlohmann/json_fwd.hpp>

namespace routeproof::output::detail {
// Shared bounded read and digest/reference verification for result consumers.
[[nodiscard]] nlohmann::json read_result(const std::filesystem::path&);
}
