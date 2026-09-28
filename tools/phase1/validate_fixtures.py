#!/usr/bin/env python3
"""Run the Phase 1 CLI acceptance fixtures and canonicalization checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "examples" / "phase1"


def invoke(binary: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(binary), *arguments],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "binary",
        nargs="?",
        type=Path,
        default=ROOT / "build" / "host-debug" / "routeproof",
        help="routeproof executable (default: build/host-debug/routeproof)",
    )
    args = parser.parse_args()
    binary = args.binary.resolve()
    if not binary.is_file():
        parser.error(f"routeproof executable does not exist: {binary}")

    failed = False
    valid_outputs: dict[str, str] = {}
    valid_documents: dict[str, dict[str, object]] = {}
    for fixture in sorted((FIXTURES / "valid").glob("*.yaml")):
        fixture_arg = str(fixture.relative_to(ROOT))
        result = invoke(binary, "validate", fixture_arg)
        if result.returncode != 0:
            print(f"FAIL valid {fixture.relative_to(ROOT)}: {result.stderr.strip()}")
            failed = True
            continue
        match = re.search(r"^scenario_sha256: ([0-9a-f]{64})$", result.stdout, re.MULTILINE)
        if match is None:
            print(f"FAIL valid {fixture.relative_to(ROOT)}: missing scenario hash")
            failed = True
            continue
        normalized = invoke(binary, "validate", fixture_arg, "--normalized")
        if normalized.returncode != 0:
            print(f"FAIL normalize {fixture.relative_to(ROOT)}: {normalized.stderr.strip()}")
            failed = True
            continue
        canonical = normalized.stdout.removesuffix("\n")
        try:
            document = json.loads(canonical)
        except json.JSONDecodeError as error:
            print(f"FAIL normalized JSON {fixture.relative_to(ROOT)}: {error}")
            failed = True
            continue
        actual_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if actual_hash != match.group(1):
            print(f"FAIL hash {fixture.relative_to(ROOT)}: CLI={match.group(1)} Python={actual_hash}")
            failed = True
            continue
        valid_outputs[fixture.name] = canonical
        valid_documents[fixture.name] = document
        print(f"PASS valid {fixture.relative_to(ROOT)} sha256={actual_hash}")

    equivalent = (
        "equivalent-a.yaml" in valid_outputs
        and "equivalent-b.yaml" in valid_outputs
        and valid_outputs["equivalent-a.yaml"] == valid_outputs["equivalent-b.yaml"]
    )
    print(f"{'PASS' if equivalent else 'FAIL'} equivalent declaration normalization")
    failed |= not equivalent

    physical = valid_documents.get("physical-state.yaml")
    physical_state_is_distinct = False
    if physical is not None:
        routers = {router["id"]: router["initial_state"] for router in physical["routers"]}
        links = {link["id"]: link for link in physical["links"]}
        physical_state_is_distinct = (
            routers == {"left": "up", "right": "down"}
            and set(links) == {"p2p-1", "p2p-2"}
            and links["p2p-1"]["cost_ab"] == 5
            and links["p2p-1"]["cost_ba"] == 17
            and links["p2p-1"]["initial_state"] == "up"
            and links["p2p-2"]["cost_ab"] == 7
            and links["p2p-2"]["cost_ba"] == 23
            and links["p2p-2"]["initial_state"] == "down"
        )
    print(f"{'PASS' if physical_state_is_distinct else 'FAIL'} normalized directional parallel links and independent router/link state")
    failed |= not physical_state_is_distinct

    for fixture in sorted((FIXTURES / "invalid").glob("*.yaml")):
        fixture_arg = str(fixture.relative_to(ROOT))
        result = invoke(binary, "validate", fixture_arg)
        diagnostic = result.stderr.strip()
        has_source_location = fixture.name in diagnostic and re.search(r":\d+:\d+:", diagnostic)
        # The out-of-order declaration must identify the offending event after
        # sorting; retaining YAML::Node aliases here previously changed its mark.
        correct_event_location = (
            fixture.name != "event-order.yaml" or f"{fixture_arg}:10:5:" in diagnostic
        )
        if result.returncode != 2 or not has_source_location or not correct_event_location:
            print(
                f"FAIL invalid {fixture.relative_to(ROOT)}: exit={result.returncode}; "
                f"{diagnostic or result.stdout.strip()}"
            )
            failed = True
        else:
            print(f"PASS invalid {fixture.relative_to(ROOT)}: {diagnostic}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
