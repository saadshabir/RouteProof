#include "baseline_document.hpp"
#include "routeproof/version.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <tuple>
#include <utility>

namespace routeproof::output {
nlohmann::json detail::baseline_document(const input::LoadedScenario& loaded, const spf::PhysicalState& state,
                                         const forwarding::Tables& tables) {
    using Json = nlohmann::json;
    const auto& scenario = loaded.topology.scenario;
    Json routers = Json::array(), links = Json::array(), rows = Json::array();
    std::vector<std::string> prefix_text;
    prefix_text.reserve(scenario.prefixes.size());
    for (const auto& prefix : scenario.prefixes) { prefix_text.push_back(prefix.network.to_string()); }
    struct Row { model::RouterIndex source; const forwarding::Route* route; };
    std::vector<Row> ordered;
    ordered.reserve(tables.route_entries);
    for (model::RouterIndex source = 0; source < tables.routers.size(); ++source) {
        if (state.available_routers[source]) {
            routers.push_back(scenario.routers[source].id);
        }
        for (const auto& route : tables.routers[source]) {
            ordered.push_back({source, &route});
        }
    }
    // Sort lightweight references before constructing JSON. Prefix indices use
    // numeric network order, which differs from the canonical text order.
    std::sort(ordered.begin(), ordered.end(), [&](const Row& left, const Row& right) {
        return std::tie(scenario.routers[left.source].id, prefix_text[left.route->prefix]) <
               std::tie(scenario.routers[right.source].id, prefix_text[right.route->prefix]);
    });
    rows.get_ref<Json::array_t&>().reserve(ordered.size());
    for (const auto& row : ordered) {
        const auto& route = *row.route;
        const auto& prefix = scenario.prefixes[route.prefix];
        Json hops = Json::array();
        hops.get_ref<Json::array_t&>().reserve(route.next_hops->size());
        for (const auto& hop : *route.next_hops) {
            hops.push_back(Json{{"neighbor", scenario.routers[hop.neighbor].id},
                {"link", scenario.links[hop.link].id}, {"interface", hop.outgoing_interface}});
        }
        Json entry{{"router", scenario.routers[row.source].id},
            {"prefix", prefix_text[route.prefix]}, {"origin", scenario.routers[prefix.origin].id},
            {"kind", route.kind == forwarding::RouteKind::connected ? "connected" : "ospf"},
            {"distance_to_origin", route.distance_to_origin}, {"metric", route.metric},
            {"protocol_cost", route.protocol_cost}};
        entry["next_hops"] = std::move(hops);
        rows.push_back(std::move(entry));
    }
    for (model::LinkIndex index = 0; index < scenario.links.size(); ++index) {
        if (state.administratively_up_links[index]) {
            links.push_back(scenario.links[index].id);
        }
    }
    Json document{{"schema_version", 1}, {"model", model_id}, {"kind", "baseline_routes"},
        {"scenario_sha256", loaded.scenario_sha256}, {"route_entries", tables.route_entries},
        {"next_hop_references", tables.next_hop_references}};
    document["available_routers"] = std::move(routers);
    document["administratively_up_links"] = std::move(links);
    document["routes"] = std::move(rows);
    return document;
}
std::string baseline_json(const input::LoadedScenario& loaded, const spf::PhysicalState& state,
                          const forwarding::Tables& tables) {
    return detail::baseline_document(loaded, state, tables).dump();
}
}
