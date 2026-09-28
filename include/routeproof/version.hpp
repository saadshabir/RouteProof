#pragma once

#include <string_view>

#ifndef ROUTEPROOF_VERSION
#define ROUTEPROOF_VERSION "0.1.0"
#endif

namespace routeproof {

inline constexpr std::string_view version = ROUTEPROOF_VERSION;
inline constexpr std::string_view model_id = "ospf_spf_v1";
inline constexpr int scenario_schema_version = 1;
inline constexpr int result_schema_version = 1;

}  // namespace routeproof
