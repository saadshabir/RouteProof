#pragma once

#include "routeproof/model/topology.hpp"

#include <filesystem>
#include <stdexcept>
#include <string>
#include <string_view>

namespace routeproof::input {

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

[[nodiscard]] LoadedScenario load_scenario(const std::filesystem::path& path);
[[nodiscard]] LoadedScenario parse_scenario(std::string_view text,
                                            std::string source = "<input>");

}  // namespace routeproof::input
