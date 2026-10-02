#!/usr/bin/env python3
"""Exercise safe CLI output, JSON interoperability, aliases, and bounded inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BASE = {
    "schema_version": 1,
    "name": "review",
    "model": "ospf_spf_v1",
    "routers": [{"id": "r1", "router_id": "192.0.2.1"}],
    "links": [],
    "prefixes": [{"prefix": "10.0.0.0/24", "origin": "r1", "stub_cost": 1}],
    "events": [],
    "assertions": [],
}


def main() -> int:
    binary = Path(sys.argv[1]).resolve()

    def invoke(path: Path, normalized: bool = False):
        arguments = [str(binary), "validate", str(path)]
        if normalized:
            arguments.append("--normalized")
        return subprocess.run(arguments, capture_output=True, timeout=15, cwd=ROOT)

    def reject(path: Path, rule: bytes = b""):
        result = invoke(path)
        assert result.returncode == 2, (path.name, result.returncode)
        assert rule in result.stderr, (path.name, repr(result.stderr))
        assert re.search(rb":\d+:\d+:", result.stderr), (path.name, repr(result.stderr))
        return result

    with tempfile.TemporaryDirectory(prefix="routeproof-regressions-") as temporary:
        directory = Path(temporary)

        def write(name: str, text: str | bytes) -> Path:
            path = directory / name
            path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
            return path

        emoji = dict(BASE, name="route \U0001f600 \\ \" /")
        escaped = write("escaped.json", json.dumps(emoji))
        literal = write("literal.json", json.dumps(emoji, ensure_ascii=False))
        automatic = write("automatic.yaml", escaped.read_bytes())
        bom = write("bom.json", b"\xef\xbb\xbf" + escaped.read_bytes())
        slash = write("slash.json", escaped.read_text(encoding="utf-8").replace("/", r"\/"))
        normalized = [invoke(path, True) for path in [escaped, literal, automatic, bom, slash]]
        assert all(result.returncode == 0 for result in normalized)
        assert all(result.stdout == normalized[0].stdout for result in normalized)
        canonical = normalized[0].stdout.rstrip(b"\n")
        assert json.loads(canonical)["name"] == emoji["name"]
        summary = invoke(escaped)
        assert hashlib.sha256(canonical).hexdigest().encode() in summary.stdout
        print("PASS JSON Unicode escapes, token cursor, BOM, automatic detection, canonical hashes")

        name = "safe\x1b[2J\x1b[Hforged\nrouters: 999\r\t\x00\x7f\u009b"
        controlled = write("controls.json", json.dumps(dict(BASE, name=name)))
        summary = invoke(controlled)
        assert summary.returncode == 0
        assert b"\x1b" not in summary.stdout and b"\x00" not in summary.stdout
        assert b"\x7f" not in summary.stdout and b"\xc2\x9b" not in summary.stdout
        assert summary.stdout.count(b"\n") == 10
        assert b"\\x1b[2J" in summary.stdout and b"\\nrouters: 999" in summary.stdout
        assert b"\\u009b" in summary.stdout
        assert json.loads(invoke(controlled, True).stdout)["name"] == name
        bad = dict(BASE)
        bad["unknown\x1b[2J\nforged\u009b"] = 1
        diagnostic = reject(write("unsafe\x1b[H\nsource.json", json.dumps(bad)), b"unsupported field")
        assert b"\x1b" not in diagnostic.stderr and b"\xc2\x9b" not in diagnostic.stderr
        assert diagnostic.stderr.count(b"\n") == 1
        invalid_bytes = json.dumps(BASE).encode().replace(b'"review"', b'"\x9b"')
        diagnostic = reject(write("invalid-utf8.json", invalid_bytes), b"invalid JSON")
        assert b"\x9b" not in diagnostic.stderr
        print("PASS escaped summary and diagnostics, including untrusted source paths")

        reject(write("duplicate.json", '{\n"name": 1,\n"n\\u0061me": 2\n}'), b"duplicate mapping key")
        nested_duplicate = json.dumps(BASE).replace('"id": "r1"', '"id": "r1", "i\\u0064": "r2"')
        reject(write("nested-duplicate.json", nested_duplicate), b"duplicate mapping key")
        reject(write("surrogate.json", json.dumps(BASE).replace('"review"', '"\\ud800"')), b"invalid JSON")
        reject(write("trailing-comma.json", json.dumps(BASE)[:-1] + ',}'), b"invalid JSON")
        reject(write("yaml-disguised.json", '{name: review}'), b"invalid JSON")
        typed = json.dumps(BASE).replace('"schema_version": 1', '"schema_version": "1"')
        location = reject(write("integer-string.json", typed), b"schema_version must be an integer")
        assert b":1:20:" in location.stderr
        marked = dict(BASE, name=emoji["name"])
        marked["prefixes"] = [dict(BASE["prefixes"][0], stub_cost="1")]
        marked_text = json.dumps(marked, indent=2)
        offset = marked_text.index('"1"', marked_text.index('"stub_cost"'))
        before = marked_text[:offset]
        line = before.count("\n") + 1
        column = len(before.rsplit("\n", 1)[-1]) + 1
        location = reject(write("marked.json", marked_text), b"stub_cost must be an integer")
        assert f":{line}:{column}:".encode() in location.stderr
        print("PASS strict JSON, duplicate decoded keys, numeric types, original source locations")

        alias_yaml = '''schema_version: 1
name: review
model: ospf_spf_v1
routers: [{id: &router r1, router_id: 192.0.2.1}]
links: &empty []
prefixes: [{prefix: 10.0.0.0/24, origin: *router, stub_cost: 1}]
events: *empty
assertions: *empty
'''
        alias = invoke(write("aliases.yaml", alias_yaml), True)
        plain = invoke(write("plain.json", json.dumps(BASE)), True)
        assert alias.returncode == 0 and alias.stdout == plain.stdout
        simple_flow = '{schema_version: 1, name: review, model: ospf_spf_v1, routers: [{id: r1, router_id: 192.0.2.1}], links: [], prefixes: [{prefix: 10.0.0.0/24, origin: r1, stub_cost: 1}], events: [], assertions: []}'
        assert invoke(write("simple-flow.yaml", simple_flow), True).stdout == plain.stdout
        reject(write("cycle.yaml", '&a {child: &b [*a]}'), b"recursive YAML aliases")
        print("PASS nonrecursive aliases, flow YAML, alias-cycle rejection")

        destinations = ["0.0.0.0", "127.255.255.255", "192.0.2.0", "192.0.2.255", "255.255.255.255"]
        ownership = dict(BASE)
        ownership["prefixes"] = [
            {"prefix": prefix, "origin": "r1", "stub_cost": 1}
            for prefix in ["255.255.255.255/32", "192.0.2.0/24", "0.0.0.0/1"]
        ]
        ownership["assertions"] = [
            {"id": f"reach{i}", "type": "must_reach", "source": "r1", "destination": address,
             "quantifier": "all", "scope": "every_snapshot"}
            for i, address in enumerate(destinations)
        ]
        assert invoke(write("ownership.json", json.dumps(ownership))).returncode == 0
        for address in ["128.0.0.0", "192.0.3.0", "255.255.255.254"]:
            invalid = dict(ownership)
            invalid["assertions"] = [dict(ownership["assertions"][0], destination=address)]
            reject(write("gap.json", json.dumps(invalid)), b"exactly one declared prefix")
        before_first = dict(BASE, assertions=[dict(ownership["assertions"][0], destination="9.255.255.255")])
        reject(write("before-first.json", json.dumps(before_first)), b"exactly one declared prefix")
        print("PASS sorted prefix lookup at network endpoints and address-space boundaries")

        large = dict(BASE)
        large["events"] = [{"id": f"e{i}", "seq": i + 1, "at_ns": i, "type": "router_down", "router": "r1"} for i in range(32_000)]
        result = invoke(write("large.json", json.dumps(large, separators=(",", ":"))))
        assert result.returncode == 0 and b"events: 32000\n" in result.stdout
        oversized = write("oversized.yaml", b" " * (16 * 1024 * 1024 + 1))
        result = invoke(oversized)
        assert result.returncode == 2 and b"byte limit" in result.stderr
        print("PASS large valid input and bounded file reads")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AssertionError, subprocess.TimeoutExpired) as error:
        print(f"FAIL regression: {error}", file=sys.stderr)
        sys.exit(1)
