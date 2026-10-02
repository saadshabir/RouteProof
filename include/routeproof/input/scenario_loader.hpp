#pragma once

#include "routeproof/model/topology.hpp"

#include <cstddef>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <string_view>

namespace routeproof::input {

struct InputLimits {
    std::size_t max_bytes{16U * 1024U * 1024U};
    std::size_t max_nodes{1'000'000U};
    std::size_t max_collection_entries{100'000U};
    std::size_t max_scalar_bytes{64U * 1024U};
    std::size_t max_nesting{128U};
};

class InputError final : public std::runtime_error {
public:
    InputError(std::string source, std::size_t line, std::size_t column,
               std::string message);
    explicit InputError(std::string message);

    [[nodiscard]] const std::string& source() const noexcept { return source_; }
    [[nodiscard]] std::size_t line() const noexcept { return line_; }
    [[nodiscard]] std::size_t column() const noexcept { return column_; }

private:
    std::string source_;
    std::size_t line_{};
    std::size_t column_{};
};

struct LoadedScenario {
    model::Topology topology;
    std::string normalized_json;
    std::string scenario_sha256;
};

[[nodiscard]] LoadedScenario load_scenario(const std::filesystem::path& path,
                                          const InputLimits& limits = {});
[[nodiscard]] LoadedScenario parse_scenario(std::string_view text,
                                            std::string source = "<input>",
                                            const InputLimits& limits = {});

}  // namespace routeproof::input
