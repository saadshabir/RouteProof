"""Deterministic Containerlab inputs from RouteProof's validated canonical model."""
import ipaddress
import json
import re
from pathlib import Path

FRR_VERSION = "10.2.1"
CANDIDATE_IMAGE = "quay.io/frrouting/frr:" + FRR_VERSION
ECMP_LIMIT = 64


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def check_image(image):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./:_-]*@sha256:[0-9a-f]{64}", image):
        raise ValueError("--image must be an immutable repository@sha256:<64 lowercase hex> reference")


def generate(scenario, directory, image, lab_name, allow_unpinned=False):
    """Canonical scenario must come from routeproof validate --normalized.

    Native interface names are deliberately independent of user IDs, which may
    exceed Linux's 15-character limit. Save the reversible mapping explicitly.
    """
    if not (allow_unpinned and image == CANDIDATE_IMAGE):
        check_image(image)
    if not re.fullmatch(r"rp-[a-z0-9-]{1,40}", lab_name):
        raise ValueError("invalid run-owned lab name")
    if not scenario["prefixes"]:
        raise ValueError("FRR comparison requires at least one declared destination prefix")
    if len(scenario["routers"]) > 16 or len(scenario["links"]) > 64 or len(scenario["prefixes"]) > 64:
        raise ValueError("small-lab budget: at most 16 routers, 64 links, 64 prefixes")
    # Avoid a FRR cap silently truncating complete interface sets.
    for router in scenario["routers"]:
        if sum(router["id"] in (link["a"], link["b"]) for link in scenario["links"]) > ECMP_LIMIT:
            raise ValueError("router degree exceeds configured FRR ECMP capacity")
    if len(scenario["events"]) > 64:
        raise ValueError("small-lab budget: at most 64 events")
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    networks = [ipaddress.IPv4Network(p["prefix"]) for p in scenario["prefixes"]]
    transit = []
    # Choose numbered /30s disjoint from every modeled destination, including
    # arbitrary user fixtures. A bounded scan prevents giant-prefix hangs.
    for candidate in (ipaddress.IPv4Network("198.18.0.0/15").subnets(new_prefix=30) if scenario["links"] else []):
        if not any(candidate.overlaps(network) for network in networks):
            transit.append(candidate)
            if len(transit) == len(scenario["links"]):
                break
    if scenario["links"] and len(transit) != len(scenario["links"]):
        raise ValueError("no disjoint transit address space in reserved lab pool 198.18.0.0/15")
    management = next((network for network in
                       reversed(list(ipaddress.IPv4Network("198.18.0.0/15").subnets(new_prefix=24)))
                       if not any(network.overlaps(other) for other in networks + transit)), None)
    if management is None:
        raise ValueError("no disjoint management /24 in reserved lab pool")
    mapping = {"schema_version": 1, "lab_name": lab_name, "image": image,
               "platform": "linux/amd64", "frr_version": FRR_VERSION,
               "ecmp_limit": ECMP_LIMIT, "management_subnet": str(management), "routers": {}, "links": {}, "prefixes": {}}
    for index, router in enumerate(scenario["routers"]):
        node = f"r{index}"
        mapping["routers"][router["id"]] = {
            "node": node, "container": f"clab-{lab_name}-{node}",
            "router_id": router["router_id"], "interfaces": {}}
    counters = {r["id"]: 0 for r in scenario["routers"]}
    endpoints = []
    for index, link in enumerate(scenario["links"]):
        sides = {}
        for side, peer, offset in (("a", "b", 1), ("b", "a", 2)):
            router = link[side]
            counters[router] += 1
            interface = f"eth{counters[router]}"
            sides[side] = {"router": router, "interface": interface,
                           "address": str(transit[index].network_address + offset),
                           "model_interface": f"{link['id']}@{router}",
                           "cost": link[f"cost_{side}{peer}"]}
        mapping["links"][link["id"]] = {"subnet": str(transit[index]), **sides}
        endpoints.append({"endpoints": [f"{mapping['routers'][sides[s]['router']]['node']}:{sides[s]['interface']}"
                                        for s in ("a", "b")]})
        for side, peer in (("a", "b"), ("b", "a")):
            own, other = sides[side], sides[peer]
            mapping["routers"][own["router"]]["interfaces"][own["interface"]] = {
                "link": link["id"], "interface": own["model_interface"],
                "neighbor": other["router"], "peer_address": other["address"]}
    for index, prefix in enumerate(scenario["prefixes"]):
        network = ipaddress.IPv4Network(prefix["prefix"])
        address = network.network_address if network.prefixlen >= 31 else network.network_address + 1
        mapping["prefixes"][prefix["prefix"]] = {
            "origin": prefix["origin"], "interface": f"stub{index}",
            "address": f"{address}/{network.prefixlen}", "stub_cost": prefix["stub_cost"]}
    nodes = {}
    for router in scenario["routers"]:
        rid = router["id"]
        node = mapping["routers"][rid]["node"]
        config_dir = directory / node
        config_dir.mkdir()
        # Keep kernel routes self-contained for ip -j route inspection. FRR
        # otherwise installs nhid references on kernels with nexthop objects.
        config = ["frr defaults traditional", f"hostname {node}",
                  "service integrated-vtysh-config", "log stdout",
                  "no zebra nexthop kernel enable", "!"]
        for link in mapping["links"].values():
            for side in ("a", "b"):
                endpoint = link[side]
                if endpoint["router"] != rid:
                    continue
                config += [f"interface {endpoint['interface']}",
                           f" ip address {endpoint['address']}/30", " ip ospf area 0.0.0.0",
                           " ip ospf network point-to-point", f" ip ospf cost {endpoint['cost']}",
                           " ip ospf hello-interval 1", " ip ospf dead-interval 4", "!"]
        for prefix in mapping["prefixes"].values():
            if prefix["origin"] == rid:
                config += [f"interface {prefix['interface']}", f" ip address {prefix['address']}",
                           " ip ospf area 0.0.0.0", " ip ospf passive",
                           f" ip ospf cost {prefix['stub_cost']}", "!"]
        config += ["router ospf", f" ospf router-id {router['router_id']}",
                   f" maximum-paths {ECMP_LIMIT}", " timers throttle spf 100 200 1000", "!", "line vty", "!"]
        (config_dir / "frr.conf").write_text("\n".join(config) + "\n", encoding="utf-8")
        (config_dir / "daemons").write_text(
            "zebra=yes\nospfd=yes\nbgpd=no\nstaticd=no\nvtysh_enable=yes\n"
            'zebra_options=" -A 127.0.0.1 -s 90000000"\n'
            'ospfd_options=" -A 127.0.0.1"\n', encoding="utf-8")
        nodes[node] = {"kind": "linux", "image": image,
                       "binds": [f"{config_dir / 'frr.conf'}:/etc/frr/frr.conf:ro",
                                 f"{config_dir / 'daemons'}:/etc/frr/daemons:ro"],
                       "labels": {"routeproof.run": lab_name},
                       "sysctls": {"net.ipv4.ip_forward": "1", "net.ipv4.conf.all.rp_filter": "0",
                                   "net.ipv4.conf.default.rp_filter": "0"}}
    write_json(directory / "topology.clab.json", {"name": lab_name, "mgmt": {"network": f"{lab_name}-mgmt", "ipv4-subnet": str(management)},
                                                  "topology": {"nodes": nodes, "links": endpoints}})
    write_json(directory / "mapping.json", mapping)
    return mapping
