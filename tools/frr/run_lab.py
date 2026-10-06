#!/usr/bin/env python3
"""Fresh, run-owned Linux FRR labs; no third-party Python dependencies."""
import argparse
import hashlib
import json
import math
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from generate import CANDIDATE_IMAGE, FRR_VERSION, generate, write_json
from normalize import (ObservationError, compare, normalize_kernel,
                       normalize_ospf, normalize_zebra, require)

ROOT = Path(__file__).resolve().parents[2]


class InfrastructureError(RuntimeError):
    pass


class CommandError(InfrastructureError):
    def __init__(self, message, returncode=None):
        super().__init__(message)
        self.returncode = returncode


class InvalidLabInput(ValueError):
    pass


class Commands:
    """Shell-free commands, bounded execution, and raw logs even on failure."""
    def __init__(self, directory, timeout=30):
        self.directory = Path(directory)
        self.directory.mkdir()
        self.timeout = timeout
        self.index = 0
        self.deadline = None

    def run(self, argv, allowed=(0,)):
        self.index += 1
        target = self.directory / f"{self.index:06d}.json"
        start = time.monotonic()
        timeout = self.timeout
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - start)
            if timeout <= 0:
                raise CommandError("snapshot deadline exceeded")
        record = {"argv": list(map(str, argv)), "timeout_seconds": timeout}
        try:
            process = subprocess.run(record["argv"], capture_output=True, text=True, timeout=timeout)
            record.update(returncode=process.returncode, stdout=process.stdout, stderr=process.stderr)
            if process.returncode not in allowed:
                raise CommandError(f"command exited {process.returncode}: {record['argv']!r}; see {target}", process.returncode)
            return process.stdout
        except subprocess.TimeoutExpired as error:
            record.update(error="timeout", stdout=decode(error.stdout), stderr=decode(error.stderr))
            raise CommandError(f"command timeout: {record['argv']!r}; see {target}") from error
        except OSError as error:
            record["error"] = str(error)
            raise CommandError(str(error)) from error
        finally:
            record["elapsed_seconds"] = time.monotonic() - start
            write_json(target, record)

    def json(self, argv):
        raw = self.run(argv)
        try:
            return json.loads(raw)
        except ValueError as error:
            raise CommandError(f"command returned invalid JSON: {argv!r}") from error


def decode(value):
    return value.decode(errors="replace") if isinstance(value, bytes) else value or ""


def load_scenario(binary, source, commands):
    try:
        return commands.json([binary, "validate", str(source), "--normalized"])
    except CommandError as error:
        if error.returncode == 2:
            raise InvalidLabInput(f"invalid scenario; {error}") from error
        raise


def initial_state(scenario):
    return ({r["id"] for r in scenario["routers"] if r["initial_state"] == "up"},
            {l["id"] for l in scenario["links"] if l["initial_state"] == "up"})


def mutate(event, routers, links):
    target = event.get("router", event.get("link"))
    active = routers if "router" in event else links
    up = event["type"].endswith("_up")
    changed = (target in active) != up
    if up:
        active.add(target)
    else:
        active.discard(target)
    return changed


def interface_states(mapping, routers, links):
    states = {}
    for link_id, link in mapping["links"].items():
        up = link_id in links and all(link[s]["router"] in routers for s in ("a", "b"))
        for side in ("a", "b"):
            endpoint = link[side]
            states[endpoint["router"], endpoint["interface"]] = up
    for attachment in mapping["prefixes"].values():
        states[attachment["origin"], attachment["interface"]] = attachment["origin"] in routers
    return states


def apply_state(mapping, routers, links, commands):
    # Router down removes *all* modeled links and passive attachments. Daemons
    # stay alive for management captures, but no modeled forwarding is possible.
    # Raising a router re-derives link states, preserving administrative failures.
    for (router, interface), up in sorted(interface_states(mapping, routers, links).items()):
        container = mapping["routers"][router]["container"]
        commands.run(["docker", "exec", container, "ip", "link", "set", "dev", interface, "up" if up else "down"])


def expected_neighbors(router, mapping, routers, links):
    result = set()
    for link_id, link in mapping["links"].items():
        if link_id not in links or not all(link[s]["router"] in routers for s in ("a", "b")):
            continue
        for side, peer in (("a", "b"), ("b", "a")):
            if link[side]["router"] == router:
                result.add((mapping["routers"][link[peer]["router"]]["router_id"],
                            link[side]["interface"], link[peer]["address"]))
    return result


def check_physical(raw, states, router):
    require(isinstance(raw, list), "ip link output must be a list")
    interfaces = {r["ifname"]: r for r in raw}
    for (owner, interface), up in states.items():
        if owner != router:
            continue
        require(interface in interfaces, f"{router}: missing physical interface {interface}")
        require(("UP" in interfaces[interface].get("flags", [])) == up,
                f"{router}/{interface}: physical state has not applied")


def check_neighbors(raw, expected):
    require(isinstance(raw, dict) and isinstance(raw.get("neighbors"), dict), "unsupported FRR neighbor JSON")
    actual = set()
    for rid, neighbors in raw["neighbors"].items():
        require(isinstance(neighbors, list), "unsupported neighbor rows")
        for neighbor in neighbors:
            require(isinstance(neighbor, dict), "invalid neighbor record")
            require(isinstance(neighbor.get("ifaceName"), str) and isinstance(neighbor.get("ifaceAddress"), str),
                    "missing neighbor interface/address")
            require(neighbor.get("converged") == "Full", "adjacency not Full/withdrawn yet")
            # FRR's IF_NAME can include the local interface address.
            identity = (rid, neighbor["ifaceName"].split(":", 1)[0], neighbor["ifaceAddress"])
            require(identity not in actual, "duplicate adjacency")
            actual.add(identity)
    require(actual == expected, f"adjacency set differs: expected {sorted(expected)}, observed {sorted(actual)}")


def capture(mapping, routers, links, commands, directory):
    """Capture all planes and physical/adjacency/LSDB evidence for each poll."""
    directory.mkdir()
    observations = {}
    states = interface_states(mapping, routers, links)
    for router, info in sorted(mapping["routers"].items()):
        container = info["container"]
        raw = {}
        router_dir = directory / info["node"]
        router_dir.mkdir()
        queries = {
            "physical": ["ip", "-j", "link", "show"],
            "neighbors": ["vtysh", "-c", "show ip ospf neighbor json"],
            "lsdb": ["vtysh", "-c", "show ip ospf database router json"],
            "ospf": ["vtysh", "-c", "show ip ospf route json"],
            "zebra": ["vtysh", "-c", "show ip route json"],
            "kernel": ["ip", "-j", "-4", "route", "show", "table", "all"]}
        # Save each completed capture immediately; a later command failure must
        # not erase earlier observations from an incomplete poll.
        for name, query in queries.items():
            raw[name] = commands.json(["docker", "exec", container, *query])
            write_json(router_dir / f"{name}.json", raw[name])
        check_physical(raw["physical"], states, router)
        check_neighbors(raw["neighbors"], expected_neighbors(router, mapping, routers, links))
        if router not in routers:
            observations[router] = {"status": "unavailable"}
            continue
        observations[router] = {
            "status": "available", "ospf": normalize_ospf(router, raw["ospf"], mapping),
            "zebra": normalize_zebra(router, raw["zebra"], mapping),
            "kernel": normalize_kernel(router, raw["kernel"], mapping)}
    return observations


def wait_stable(observe, directory, timeout, interval, window, polls,
                clock=time.monotonic, sleep=time.sleep):
    """Stability begins only after post-event physical/adjacency checks pass.

    Never require agreement with the simulator to select a capture. Stable
    mismatches are differential failures; command/readiness timeouts are
    infrastructure failures. Timers/LSA age are excluded from stability keys.
    """
    start = clock()
    last, stable_start, count, attempt = None, None, 0, 0
    while clock() - start < timeout:
        attempt += 1
        target = directory / f"poll-{attempt:04d}"
        try:
            observation = observe(target)
            signature = json.dumps(observation, sort_keys=True)
            now = clock()
            if now - start >= timeout:
                raise InfrastructureError("snapshot deadline exceeded during capture")
            if signature != last:
                last, stable_start, count = signature, now, 1
            else:
                count += 1
            write_json(target / "normalized.json", observation)
            if count >= polls and now - stable_start >= window:
                return observation, {"polls": attempt, "stable_polls": count,
                                     "stable_seconds": now - stable_start}
        except (CommandError, ObservationError) as error:
            target.mkdir(exist_ok=True)
            write_json(target / "error.json", {"error": str(error)})
            last, stable_start, count = None, None, 0
        sleep(min(interval, max(0, timeout - (clock() - start))))
    raise InfrastructureError(f"readiness/stability timeout after {attempt} polls; see {directory}")


def initialize(mapping, commands):
    for router, info in sorted(mapping["routers"].items()):
        container = info["container"]
        # Wait for daemon sockets before loading interfaces/configuration.
        while True:
            try:
                version = commands.run(["docker", "exec", container, "vtysh", "-c", "show version"])
                break
            except CommandError:
                if commands.deadline is None or time.monotonic() >= commands.deadline:
                    raise
                time.sleep(min(1, max(0, commands.deadline - time.monotonic())))
        require(re.search(r"\bFRRouting " + re.escape(FRR_VERSION) + r"(?:\s|_|\(|$)", version) is not None,
                f"normalizer supports FRR {FRR_VERSION} only")
        # Containers and veth links exist now. Passive destinations use dummy
        # interfaces, not loopbacks that would change /24 advertisements to /32.
        for prefix in mapping["prefixes"].values():
            if prefix["origin"] == router:
                commands.run(["docker", "exec", container, "ip", "link", "add", prefix["interface"], "type", "dummy"])
        commands.run(["docker", "exec", container, "vtysh", "-b"])


def environment(commands, image):
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
        raise InfrastructureError("live labs require a Linux amd64 Docker/Containerlab host; use --generate-only on macOS")
    for tool in ("docker", "containerlab"):
        if not shutil.which(tool):
            raise InfrastructureError(f"missing required Linux lab tool: {tool}")
    metadata = {"system": platform.system(), "host": platform.platform(),
                "architecture": platform.machine(), "kernel": platform.release(),
                "docker": commands.json(["docker", "version", "--format", "{{json .}}"]),
                "containerlab": commands.run(["containerlab", "version"])}
    commands.run(["docker", "pull", "--platform", "linux/amd64", image])
    inspect = commands.json(["docker", "image", "inspect", image])
    require(len(inspect) == 1 and inspect[0]["Architecture"] == "amd64"
            and inspect[0]["Os"] == "linux", "image must be Linux amd64")
    metadata["image"] = inspect[0]
    return metadata


def check_fresh(mapping, commands):
    # ps JSON emits one object per line, rather than a single JSON list.
    names = set(commands.run(["docker", "ps", "-a", "--format", "{{.Names}}"]).splitlines())
    require(not names & {r["container"] for r in mapping["routers"].values()}, "refuse to reuse an existing router container")
    networks = set(commands.run(["docker", "network", "ls", "--format", "{{.Name}}"]).splitlines())
    require(f"{mapping['lab_name']}-mgmt" not in networks, "refuse to reuse an existing management network")


def cleanup(mapping, topology, commands):
    # Verify run labels before Containerlab touches any surviving container.
    names = set(commands.run(["docker", "ps", "-a", "--format", "{{.Names}}"]).splitlines())
    for info in mapping["routers"].values():
        if info["container"] in names:
            value = commands.json(["docker", "inspect", info["container"]])[0]
            require(value["Config"]["Labels"].get("routeproof.run") == mapping["lab_name"],
                    "cleanup refused: container ownership label mismatch")
    commands.run(["containerlab", "destroy", "--topo", str(topology), "--cleanup"])
    remaining = set(commands.run(["docker", "ps", "-a", "--format", "{{.Names}}"]).splitlines())
    require(not remaining & {r["container"] for r in mapping["routers"].values()}, "cleanup left owned containers")
    networks = set(commands.run(["docker", "network", "ls", "--format", "{{.Name}}"]).splitlines())
    require(f"{mapping['lab_name']}-mgmt" not in networks, "cleanup left owned management network")


def execute_live(scenario, mapping, expected, output, commands, options):
    topology = output / "lab" / "topology.clab.json"
    report = {"schema_version": 1, "status": "incomplete", "requested_snapshots": len(expected["snapshots"]),
              "completed_snapshots": 0, "snapshots": [], "event_actions": [], "cleanup": "not_started"}
    attempted = False
    try:
        report["environment"] = environment(commands, mapping["image"])
        check_fresh(mapping, commands)
        # This is set before deploy so partially created labs also get cleaned.
        attempted = True
        commands.run(["containerlab", "deploy", "--topo", str(topology)])
        commands.deadline = time.monotonic() + options.timeout
        try:
            initialize(mapping, commands)
        finally:
            commands.deadline = None
        routers, links = initial_state(scenario)
        apply_state(mapping, routers, links, commands)
        events = {event["seq"]: event for event in scenario["events"]}
        for snapshot in expected["snapshots"]:
            event = events.get(snapshot["sequence"])
            if event:
                changed = mutate(event, routers, links)
                action = {"id": event["id"], "type": event["type"], "disposition": "applied" if changed else "noop",
                          "action": "disable/restore modeled endpoint and attachment interfaces"}
                report["event_actions"].append(action)
                apply_state(mapping, routers, links, commands)
            require(sorted(routers) == snapshot["available_routers"] and sorted(links) == snapshot["administratively_up_links"],
                    "harness physical replay disagrees with engine snapshot")
            directory = output / "captures" / snapshot["id"]
            directory.mkdir(parents=True)
            commands.deadline = time.monotonic() + options.timeout
            try:
                observation, stability = wait_stable(
                    lambda target: capture(mapping, routers, links, commands, target),
                    directory, options.timeout, options.poll_interval, options.stable_window, options.stable_polls)
            finally:
                commands.deadline = None
            comparison = compare(snapshot, observation, mapping)
            comparison["stability"] = stability
            write_json(directory / "comparison.json", comparison)
            report["snapshots"].append(comparison)
            report["completed_snapshots"] += 1
            write_json(output / "report.json", report)
        report["status"] = "pass" if all(s["status"] == "pass" for s in report["snapshots"]) else "fail"
    except (InfrastructureError, ObservationError, ValueError, KeyError, OSError) as error:
        report.update(status="incomplete", error=str(error))
    except KeyboardInterrupt:
        report.update(status="incomplete", error="interrupted")
    finally:
        commands.deadline = None
        if attempted:
            try:
                cleanup(mapping, topology, commands)
                report["cleanup"] = "complete"
            except (InfrastructureError, ObservationError, OSError, KeyError, KeyboardInterrupt) as error:
                report.update(status="incomplete", cleanup="failed", cleanup_error=str(error))
        report["matched_slots"] = sum(s["matched_slots"] for s in report["snapshots"])
        report["comparison_slots"] = sum(s["comparison_slots"] for s in report["snapshots"])
        report["passing_snapshots"] = sum(s["status"] == "pass" for s in report["snapshots"])
        write_json(output / "report.json", report)
    return report


def source_manifest():
    extensions = {".py", ".cpp", ".hpp", ".json", ".yaml", ".md", ".cmake", ".txt"}
    files = [ROOT / "CMakeLists.txt", ROOT / "CMakePresets.json", ROOT / "README.md"]
    for folder in ("tools", "labs", "include", "src", "app", "cmake", "schemas", "tests", "examples", "docs"):
        files.extend(p for p in (ROOT / folder).rglob("*") if p.is_file() and p.suffix in extensions)
    files = sorted(set(files))
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="fresh evidence directory")
    parser.add_argument("--routeproof", default=str(ROOT / "build/host-debug/routeproof"))
    parser.add_argument("--image", help="tested FRR 10.2.1 Linux amd64 repository@sha256:digest")
    parser.add_argument("--generate-only", action="store_true", help="save configs and engine snapshots without claiming FRR agreement")
    parser.add_argument("--timeout", type=float, default=90, help="per-snapshot readiness deadline in seconds")
    parser.add_argument("--command-timeout", type=float, default=30)
    parser.add_argument("--poll-interval", type=float, default=1)
    parser.add_argument("--stable-window", type=float, default=6)
    parser.add_argument("--stable-polls", type=int, default=3)
    options = parser.parse_args(argv)
    if not options.image:
        if not options.generate_only:
            parser.error("live runs require --image repository@sha256:digest")
        options.image = CANDIDATE_IMAGE
    for key in ("timeout", "command_timeout", "poll_interval", "stable_window"):
        value = getattr(options, key)
        if not math.isfinite(value) or value <= 0:
            parser.error(f"--{key.replace('_', '-')} must be finite and positive")
    if options.stable_polls < 2 or options.stable_window >= options.timeout:
        parser.error("require stable-polls >= 2 and stable-window < timeout")
    return options


def main(argv=None):
    options = parse_args(argv)
    output = options.out.resolve()
    # Reject any reuse, including failed runs, before touching their evidence.
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        print(f"FRR evidence directory must be fresh: {error}", file=sys.stderr)
        return 2
    commands = Commands(output / "commands", options.command_timeout)
    try:
        binary = str(Path(options.routeproof).resolve())
        source = options.scenario.resolve()
        scenario = load_scenario(binary, source, commands)
        write_json(output / "scenario.json", scenario)
        # Complete failing reachability traces (exit 1) remain valid comparisons.
        commands.run([binary, "simulate", str(source), "--out", str(output / "engine")], allowed=(0, 1))
        expected = json.loads((output / "engine/result.json").read_text())
        require(expected["status"] != "incomplete" and len(expected["snapshots"]) == len(scenario["events"]) + 1,
                "engine did not publish the complete snapshot domain")
        name = f"rp-{uuid.uuid4().hex[:12]}"
        try:
            mapping = generate(scenario, output / "lab", options.image, name, allow_unpinned=options.generate_only)
        except ValueError as error:
            raise InvalidLabInput(str(error)) from error
        manifest = {"schema_version": 1, "mode": "generate_only" if options.generate_only else "live",
                    "source_root": str(ROOT), "binary_path": binary,
                    "scenario_sha256": expected["scenario_sha256"], "result_sha256": expected["canonical_sha256"],
                    "binary_sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
                    "source_hashes": source_manifest(),
                    "generated_hashes": {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
                                         for p in sorted((output / "lab").rglob("*")) if p.is_file()},
                    "git_revision": commands.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).strip(),
                    "git_status": commands.run(["git", "-C", str(ROOT), "status", "--porcelain"]),
                    "image": options.image,
                    "image_pin_status": "unverified_candidate" if options.generate_only else "provided_digest",
                    "lab_name": name, "frr_version": FRR_VERSION, "platform": "linux/amd64",
                    "policy": {key: getattr(options, key) for key in
                               ("timeout", "command_timeout", "poll_interval", "stable_window", "stable_polls")},
                    "reproduction_argv": [sys.executable, *sys.argv]}
        write_json(output / "manifest.json", manifest)
        if options.generate_only:
            report = {"schema_version": 1, "status": "skipped", "reason": "generation only; no FRR observations",
                      "requested_snapshots": len(expected["snapshots"]), "completed_snapshots": 0,
                      "comparison_slots": 0, "matched_slots": 0, "cleanup": "not_needed"}
            write_json(output / "report.json", report)
        else:
            report = execute_live(scenario, mapping, expected, output, commands, options)
        print(json.dumps({key: report[key] for key in ("status", "requested_snapshots", "completed_snapshots", "comparison_slots", "matched_slots")}, sort_keys=True))
        return {"pass": 0, "fail": 1, "incomplete": 3, "skipped": 3}[report["status"]]
    except InvalidLabInput as error:
        save_failure(output, "invalid", error)
        return 2
    except (InfrastructureError, ObservationError, ValueError, OSError, KeyError, KeyboardInterrupt) as error:
        save_failure(output, "incomplete", error)
        return 3


def save_failure(output, status, error):
    message = str(error) or "interrupted"
    try:
        write_json(output / "report.json", {"schema_version": 1, "status": status, "error": message})
    except OSError as output_error:
        print(f"could not save infrastructure report: {output_error}", file=sys.stderr)
    print(message, file=sys.stderr)


def handle_termination(_signum, _frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    # SIGTERM follows the same finally/cleanup path as Ctrl-C.
    signal.signal(signal.SIGTERM, handle_termination)
    sys.exit(main())
