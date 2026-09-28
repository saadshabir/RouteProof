#include "routeproof/input/scenario_loader.hpp"

#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

namespace {

using routeproof::model::RouterIndex;
using routeproof::model::Topology;
using Arc = std::tuple<std::string, std::string, std::string, std::uint16_t>;
using Attachment = std::tuple<std::string, std::string, std::uint16_t>;

void require(const bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

std::vector<Arc> outgoing_arcs(const Topology& topology, const RouterIndex router) {
    std::vector<Arc> arcs;
    for (const auto& arc : topology.adjacency.at(router)) {
        arcs.emplace_back(topology.scenario.routers.at(arc.neighbor).id,
                          topology.scenario.links.at(arc.link).id,
                          arc.outgoing_interface, arc.cost);
    }
    return arcs;
}

std::vector<Attachment> attachments(const Topology& topology, const RouterIndex router) {
    std::vector<Attachment> owned;
    for (const auto prefix_index : topology.prefixes_by_origin.at(router)) {
        const auto& prefix = topology.scenario.prefixes.at(prefix_index);
        owned.emplace_back(prefix.network.to_string(),
                           topology.scenario.routers.at(prefix.origin).id,
                           prefix.stub_cost);
    }
    return owned;
}

void check_physical_topology(const Topology& topology) {
    require(topology.scenario.routers.size() == 2U &&
                topology.router_index_by_id.size() == 2U &&
                topology.adjacency.size() == 2U,
            "both routers must have indexed adjacency lists");
    const auto left = topology.router_index_by_id.at("left");
    const auto right = topology.router_index_by_id.at("right");
    require(left != right && topology.scenario.routers.at(left).id == "left" &&
                topology.scenario.routers.at(right).id == "right",
            "router indexes must identify distinct endpoints");
    require(topology.scenario.links.size() == 2U &&
                topology.link_index_by_id.size() == 2U,
            "parallel links must retain independent identities");
    const auto first = topology.link_index_by_id.at("p2p-1");
    const auto second = topology.link_index_by_id.at("p2p-2");
    require(first != second && topology.scenario.links.at(first).id == "p2p-1" &&
                topology.scenario.links.at(second).id == "p2p-2",
            "link indexes must identify distinct physical links");

    const std::vector<Arc> expected_left{
        {"right", "p2p-1", "p2p-1@left", 5},
        {"right", "p2p-2", "p2p-2@left", 7}};
    const std::vector<Arc> expected_right{
        {"left", "p2p-1", "p2p-1@right", 17},
        {"left", "p2p-2", "p2p-2@right", 23}};
    require(outgoing_arcs(topology, left) == expected_left,
            "left adjacency must retain both links, outbound costs, and interfaces");
    require(outgoing_arcs(topology, right) == expected_right,
            "right adjacency must retain both reverse costs and interfaces even while down");
    require(topology.scenario.routers.at(left).initially_available &&
                !topology.scenario.routers.at(right).initially_available &&
                topology.scenario.links.at(first).initially_admin_up &&
                !topology.scenario.links.at(second).initially_admin_up,
            "router availability and each link's administrative state must stay separate");

    require(topology.scenario.prefixes.size() == 2U &&
                topology.prefixes_by_origin.size() == 2U,
            "both attachments must be indexed by origin");
    const std::vector<Attachment> expected_left_attachments{
        {"203.0.113.7/32", "left", 3}};
    const std::vector<Attachment> expected_right_attachments{
        {"198.51.100.0/24", "right", 9}};
    require(attachments(topology, left) == expected_left_attachments &&
                attachments(topology, right) == expected_right_attachments,
            "prefix ownership must retain both origins and the unavailable router's attachment");
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc != 2) {
        std::cerr << "Usage: routeproof_topology_check <physical-state.yaml>\n";
        return 2;
    }
    try {
        const auto loaded = routeproof::input::load_scenario(argv[1]);
        check_physical_topology(loaded.topology);
        std::cout << "PASS constructed topology: directional parallel arcs, endpoint interfaces, "
                     "independent router/link state, and prefix ownership\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL constructed topology: " << error.what() << '\n';
        return 1;
    }
}
