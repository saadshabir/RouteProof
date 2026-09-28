#pragma once

#include "routeproof/model/scenario.hpp"

#include <map>
#include <string>
#include <vector>

namespace routeproof::model {

struct DirectedArc {
    RouterIndex neighbor{};
    LinkIndex link{};
    std::string outgoing_interface;
    std::uint16_t cost{};
};

struct Topology {
    Scenario scenario;
    std::vector<std::vector<DirectedArc>> adjacency;
    std::vector<std::vector<PrefixIndex>> prefixes_by_origin;
    std::map<std::string, RouterIndex, std::less<>> router_index_by_id;
    std::map<std::string, LinkIndex, std::less<>> link_index_by_id;
};

// Builds an interface-aware directed graph while retaining physical link and
// router administrative state independently in the owned scenario.
[[nodiscard]] Topology build_topology(Scenario scenario);

}  // namespace routeproof::model
