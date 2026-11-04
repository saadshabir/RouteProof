#pragma once

#include <filesystem>
#include <string>
#include <string_view>

namespace routeproof::output {
struct Report {
    std::string json;
    int exit_code{};
};

// Compare saved results, or replay two scenario inputs before selecting snapshots.
[[nodiscard]] Report compare(const std::filesystem::path& before, const std::filesystem::path& after,
                             std::string_view from, std::string_view to, bool scenarios);
[[nodiscard]] Report summarize(const std::filesystem::path& result);
}
