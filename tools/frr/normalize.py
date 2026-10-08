"""Strict adapters for FRR 10.2.1 default-VRF JSON and Linux iproute2 JSON.

Schema fields verified against FRRouting/frr tag frr-10.2.1, ospfd/ospf_vty.c
and zebra/zebra_vty.c plus lib/nexthop.c. Unsupported shapes are infrastructure
errors, never an empty successful observation. Tests include a recorded Linux
parallel-link withdrawal as well as synthetic contracts.
"""
import ipaddress


class ObservationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ObservationError(message)


def metric(value):
    require(type(value) is int and 0 <= value < 0xFFFFFF, f"invalid route cost: {value!r}")
    return value


def domain(mapping):
    return set(mapping["prefixes"])


def prefix_keys(raw, plane, mapping):
    require(isinstance(raw, dict), "FRR route output must be a default-VRF object")
    prefixes = []
    router_ids = {r["router_id"] for r in mapping["routers"].values()}
    # Validate the whole envelope before yielding any routes. Empty objects are
    # valid empty tables; unknown metadata/wrappers are not route absence.
    for key, value in raw.items():
        require(isinstance(key, str), "FRR route keys must be strings")
        if "/" in key:
            try:
                require(str(ipaddress.IPv4Network(key)) == key, f"noncanonical prefix {key}")
            except ValueError as error:
                raise ObservationError(f"invalid prefix {key}") from error
            prefixes.append(key)
        elif plane == "ospf" and key == "vrfName":
            require(value == "default", "OSPF route output must use the default VRF")
        elif plane == "ospf" and key == "vrfId":
            require(type(value) is int and value == 0, "OSPF route output must use VRF 0")
        elif plane == "ospf" and key in router_ids:
            require(isinstance(value, dict) and value.get("routeType") in ("R", "R "),
                    f"invalid OSPF router calculation row: {key}")
        else:
            raise ObservationError(f"unsupported {plane} route-output field/envelope: {key!r}")
    return prefixes


def hop(router, interface, gateway, mapping):
    info = mapping["routers"][router]["interfaces"].get(interface)
    require(info is not None, f"{router}: unmapped next-hop interface {interface!r}")
    require(gateway == info["peer_address"], f"{router}/{interface}: unexpected gateway {gateway!r}")
    return {key: info[key] for key in ("neighbor", "link", "interface")}


def hops_sorted(hops):
    keys = [tuple(h[key] for key in ("neighbor", "link", "interface")) for h in hops]
    require(len(keys) == len(set(keys)), "duplicate next-hop interface observation")
    return [dict(zip(("neighbor", "link", "interface"), key)) for key in sorted(keys)]


def row(router, prefix, kind, cost, hops):
    return {"router": router, "prefix": prefix, "kind": kind,
            "metric": metric(cost), "next_hops": hops_sorted(hops)}


def normalize_ospf(router, raw, mapping):
    rows = []
    transit = {link["subnet"] for link in mapping["links"].values()}
    for prefix in prefix_keys(raw, "ospf", mapping):
        value = raw[prefix]
        require(isinstance(value, dict), f"OSPF {prefix}: expected route object")
        if prefix not in domain(mapping):
            # Router calculation rows are outside the destination domain;
            # only generated transit network routes are explicitly excluded.
            require(prefix in transit or value.get("routeType") in ("R", "R "),
                    f"unexpected OSPF destination outside declared domain: {prefix}")
            continue
        require(value.get("routeType") == "N" and value.get("area") == "0.0.0.0",
                f"{prefix}: expected intra-area network route in area 0")
        attachment = mapping["prefixes"][prefix]
        raw_hops = value.get("nexthops")
        require(isinstance(raw_hops, list) and raw_hops and all(isinstance(h, dict) for h in raw_hops), f"{prefix}: missing OSPF next hops")
        if attachment["origin"] == router:
            require(len(raw_hops) == 1 and raw_hops[0].get("directlyAttachedTo") == attachment["interface"],
                    f"{prefix}: wrong local OSPF attachment")
            hops = []
        else:
            hops = [hop(router, h.get("via"), h.get("ip"), mapping) for h in raw_hops]
        # OSPF calculation includes the stub cost even at the origin.
        rows.append(row(router, prefix, "ospf", value.get("cost"), hops))
    return sorted(rows, key=lambda r: r["prefix"])


def normalize_zebra(router, raw, mapping):
    rows = []
    for prefix in prefix_keys(raw, "zebra", mapping):
        values = raw[prefix]
        require(isinstance(values, list) and all(isinstance(v, dict) for v in values),
                f"Zebra {prefix}: expected list of route objects")
        if prefix not in domain(mapping):
            # Preserve/report unexpected OSPF destinations as infrastructure
            # failures, including unselected rows outside the generated pool.
            transit = {link["subnet"] for link in mapping["links"].values()}
            require(prefix in transit or not any(v.get("protocol") == "ospf" for v in values),
                    f"unexpected Zebra OSPF destination: {prefix}")
            continue
        selected = [v for v in values if v.get("selected") is True]
        require(len(selected) <= 1, f"{prefix}: multiple selected Zebra routes")
        if not selected:
            continue  # Explicit absence in comparison, never fallback to an unselected route.
        value = selected[0]
        require(value.get("prefix") == prefix and value.get("vrfId") == 0,
                f"{prefix}: inconsistent Zebra prefix/VRF")
        kind = value.get("protocol")
        require(kind in ("ospf", "connected", "local"), f"{prefix}: unsupported selected protocol {kind!r}")
        require(value.get("installed") is True and not value.get("failed", False),
                f"{prefix}: selected route is not installed")
        raw_hops = value.get("nexthops")
        require(isinstance(raw_hops, list) and raw_hops and all(isinstance(h, dict) for h in raw_hops), f"{prefix}: no Zebra next hops")
        require(all(type(h[key]) is bool for h in raw_hops for key in ("active", "fib") if key in h),
                f"{prefix}: invalid Zebra next-hop state")
        if kind in ("connected", "local"):
            require(all(h.get("active") is True and h.get("fib") is True for h in raw_hops),
                    f"{prefix}: inactive/uninstalled Zebra attachment")
            attachment = mapping["prefixes"][prefix]
            require(attachment["origin"] == router and len(raw_hops) == 1
                    and raw_hops[0].get("interfaceName") == attachment["interface"]
                    and not raw_hops[0].get("ip") and value.get("metric") == 0,
                    f"{prefix}: incorrect connected delivery")
            require(kind != "local" or ipaddress.IPv4Network(prefix).prefixlen == 32,
                    f"{prefix}: local delivery requires a /32 destination")
            kind = "connected"
            hops = []
        else:
            # FRR 10.2.1 emits active/fib only when their independent flags are
            # set. Its selected RIB can retain an inactive hop with fib=true
            # after a parallel link fails. Validate every identity, but compare
            # only active forwarding branches; the kernel plane is independent.
            identities = [hop(router, h.get("interfaceName"), h.get("ip"), mapping) for h in raw_hops]
            hops_sorted(identities)  # Inactive records must not hide duplicates.
            active = [(h, identity) for h, identity in zip(raw_hops, identities) if h.get("active") is True]
            require(active, f"{prefix}: no active Zebra next hops")
            require(all(h.get("fib") is True for h, _ in active),
                    f"{prefix}: active/uninstalled Zebra ECMP branch")
            hops = [identity for _, identity in active]
        rows.append(row(router, prefix, kind, value.get("metric"), hops))
    return sorted(rows, key=lambda r: r["prefix"])


def normalize_kernel(router, raw, mapping):
    require(isinstance(raw, list), "kernel routes must be an ip -j route list")
    rows = []
    seen = {}
    for value in raw:
        require(isinstance(value, dict), "invalid kernel route row")
        destination = value.get("dst")
        # iproute2 prints host destinations without /32.
        if destination and destination != "default":
            destination = str(ipaddress.IPv4Network(destination))
        if destination not in domain(mapping):
            continue
        action = value.get("type", "unicast")
        table = value.get("table", "main")
        require(action in ("unicast", "local"), f"{destination}: non-unicast kernel action")
        require("nhid" not in value,
                f"{destination}: kernel nhid observed; generated labs require 'no zebra nexthop kernel enable'")
        attachment = mapping["prefixes"][destination]
        if attachment["origin"] == router:
            require(value.get("dev") == attachment["interface"] and not value.get("gateway")
                    and not value.get("nexthops")
                    and not set(value.get("flags", [])) & {"dead", "linkdown"},
                    f"{destination}: incorrect kernel attachment")
            if action == "local":
                require(ipaddress.IPv4Network(destination).prefixlen == 32 and table in ("local", 255),
                        f"{destination}: unexpected kernel-local destination/table")
            else:
                require(table in ("main", 254), f"{destination}: attachment is outside the main table")
            hops = []
            kind = "connected"
        else:
            require(action == "unicast" and table in ("main", 254), f"{destination}: remote route is not main-table unicast")
            raw_hops = value.get("nexthops", [value])
            require(isinstance(raw_hops, list) and raw_hops and all(isinstance(h, dict) for h in raw_hops), f"{destination}: missing kernel next hops")
            require(all(not set(h.get("flags", [])) & {"dead", "linkdown"} for h in raw_hops),
                    f"{destination}: dead kernel branch")
            hops = [hop(router, h.get("dev"), h.get("gateway"), mapping) for h in raw_hops]
            kind = "ospf"
        # A /32 origin can appear in both the local and main tables. Verify
        # each action, then collapse just this pair into one delivery row.
        if destination in seen:
            require(kind == "connected" and ipaddress.IPv4Network(destination).prefixlen == 32
                    and seen[destination] in ("unicast", "local") and action != seen[destination],
                    f"duplicate kernel route {destination}")
            seen[destination] = "both"
            continue
        seen[destination] = action
        # Linux metric is not an OSPF cost; compare forwarding identity only.
        rows.append({"router": router, "prefix": destination, "kind": kind, "next_hops": hops_sorted(hops)})
    return sorted(rows, key=lambda r: r["prefix"])


def expected_rows(snapshot, plane):
    rows = []
    for value in snapshot["routes"]:
        route = {key: value[key] for key in ("router", "prefix", "kind", "metric", "next_hops")}
        route["next_hops"] = hops_sorted(route["next_hops"])
        if plane == "ospf":
            route.update(kind="ospf", metric=value["protocol_cost"])
        if plane == "kernel":
            del route["metric"]
        rows.append(route)
    return rows


def compare(snapshot, observed, mapping):
    """Every router x declared prefix x plane slot, including explicit absence.

    Unavailable routers must carry an explicit unavailable record, not an empty
    observation. They are counted separately from comparable route slots.
    """
    available = set(snapshot["available_routers"])
    require(set(observed) == set(mapping["routers"]), "missing/extra router observation")
    mismatches, matched, slots, unavailable = [], 0, 0, []
    for router in sorted(mapping["routers"]):
        observation = observed[router]
        require(isinstance(observation, dict), "invalid router observation")
        if router not in available:
            require(observation == {"status": "unavailable"}, f"{router}: unavailable router must be explicit")
            unavailable.append(router)
            continue
        require(observation.get("status") == "available", f"{router}: available router was not observed")
        for plane in ("ospf", "zebra", "kernel"):
            expected = {r["prefix"]: r for r in expected_rows(snapshot, plane) if r["router"] == router}
            actual = {}
            for value in observation[plane]:
                require(value["router"] == router and value["prefix"] in domain(mapping), "out-of-domain normalized row")
                require(value["prefix"] not in actual, "duplicate normalized row")
                actual[value["prefix"]] = value
            for prefix in sorted(domain(mapping)):
                slots += 1
                want, got = expected.get(prefix), actual.get(prefix)
                if want == got:
                    matched += 1
                else:
                    mismatches.append({"router": router, "prefix": prefix, "plane": plane,
                                       "reason": "extra_route" if want is None else "missing_route" if got is None else "route_mismatch",
                                       "expected": want, "observed": got})
    return {"snapshot_id": snapshot["id"], "snapshot_sha256": snapshot["sha256"],
            "status": "pass" if not mismatches else "fail", "matched_slots": matched,
            "comparison_slots": slots, "unavailable_routers": unavailable, "mismatches": mismatches}
