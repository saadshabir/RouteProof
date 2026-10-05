#include "routeproof/output/baseline.hpp"
#include "routeproof/version.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <utility>

namespace routeproof::output {
std::string baseline_json(const input::LoadedScenario& loaded, const spf::PhysicalState& state,
                          const forwarding::Tables& tables) {
    using Json = nlohmann::json;
    const auto& scenario = loaded.topology.scenario;
    Json routers = Json::array(), links = Json::array(), rows = Json::array();
    for (model::RouterIndex source = 0; source < tables.routers.size(); ++source) {
        if (state.available_routers[source]) {
            routers.push_back(scenario.routers[source].id);
        }
        for (const auto& route : tables.routers[source]) {
            const auto& prefix = scenario.prefixes[route.prefix];
            Json hops = Json::array();
            for (const auto& hop : *route.next_hops) {
                hops.push_back(Json{{"neighbor", scenario.routers[hop.neighbor].id},
                    {"link", scenario.links[hop.link].id}, {"interface", hop.outgoing_interface}});
            }
            rows.push_back(Json{{"router", scenario.routers[source].id},
                {"prefix", prefix.network.to_string()}, {"origin", scenario.routers[prefix.origin].id},
                {"kind", route.kind == forwarding::RouteKind::connected ? "connected" : "ospf"},
                {"distance_to_origin", route.distance_to_origin}, {"metric", route.metric},
                {"protocol_cost", route.protocol_cost}, {"next_hops", std::move(hops)}});
        }
    }
    for (model::LinkIndex index = 0; index < scenario.links.size(); ++index) {
        if (state.administratively_up_links[index]) {
            links.push_back(scenario.links[index].id);
        }
    }
    std::sort(rows.begin(), rows.end(), [](const Json& left, const Json& right) {
        return std::make_pair(left.at("router").get<std::string>(), left.at("prefix").get<std::string>()) <
               std::make_pair(right.at("router").get<std::string>(), right.at("prefix").get<std::string>());
    });
    return Json{{"schema_version", 1}, {"model", model_id}, {"kind", "baseline_routes"},
        {"scenario_sha256", loaded.scenario_sha256}, {"available_routers", std::move(routers)},
        {"administratively_up_links", std::move(links)}, {"routes", std::move(rows)},
        {"route_entries", tables.route_entries}, {"next_hop_references", tables.next_hop_references}}.dump();
}
}
