#!/usr/bin/env python3
"""Check semantic comparison and summary through the public CLI."""
import hashlib
import json
from pathlib import Path
import resource
import signal
import subprocess
import sys
import tempfile


def cli(binary, *args, code=0):
    result = subprocess.run([binary, *map(str, args)], capture_output=True, text=True, timeout=20)
    assert result.returncode == code, (args, result.returncode, result.stdout, result.stderr)
    return result.stdout


def write_json(path, document):
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def rehash(document):
    # Update the saved result digest using the canonical projection.
    document.pop("canonical_sha256")
    for record in document["assertions"]:
        for finding in record["findings"]:
            finding.pop("result_sha256")
    data = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(data.encode()).hexdigest()
    document["canonical_sha256"] = digest
    for record in document["assertions"]:
        for finding in record["findings"]:
            finding["result_sha256"] = digest


def check_write_failure(binary, result, directory):
    def limit_output():
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024, 1024))

    output = directory / "truncated.json"
    for args in [("summary", result), ("compare", result, result, "--to", "event-2")]:
        with output.open("wb") as stream:
            process = subprocess.run([binary, *map(str, args)], stdout=stream, stderr=subprocess.PIPE,
                                     text=True, timeout=20, preexec_fn=limit_output)
        assert output.stat().st_size == 1024
        assert process.returncode == 3, (args, process.returncode, process.stderr)
        assert "could not write report to stdout" in process.stderr


def run(binary, diamond, directory):
    replay = directory / "replay"
    cli(binary, "simulate", diamond, "--out", replay, code=1)
    result = replay / "result.json"
    check_write_failure(binary, result, directory)

    def compare(old, new):
        return json.loads(cli(binary, "compare", result, result, "--from", old, "--to", new))

    delta = compare("baseline", "event-1")
    ecmp = {row["router"]: row for row in delta["ecmp_changes"]}
    # A shrinks to one branch, while B swaps its only next hop and pays more.
    assert ecmp["a"]["before_count"] == 2 and ecmp["a"]["after_count"] == 1
    assert ecmp["a"]["removed"][0]["link"] == "ab" and ecmp["a"]["added"] == []
    assert ecmp["b"]["before_count"] == ecmp["b"]["after_count"] == 1
    assert ecmp["b"]["removed"][0]["link"] == "bd" and ecmp["b"]["added"][0]["link"] == "ab"
    metric, = delta["metric_changes"]
    assert (metric["router"], metric["before"]["metric"], metric["after"]["metric"]) == ("b", 2, 4)

    delta = compare("event-1", "event-2")
    assert [route["router"] for route in delta["withdrawn_routes"]] == ["a", "b", "c"]
    failure, = delta["newly_failing_assertions"]
    assert (failure["assertion_id"], failure["source"], failure["kind"]) == ("a-to-d", "a", "no_route")
    reverse = compare("event-2", "event-1")
    assert reverse["added_routes"] == delta["withdrawn_routes"]
    assert reverse["recovered_assertions"] == ["a-to-d"]
    assert not any(compare("event-2", "event-2")["route_counts"].values())

    summary = json.loads(cli(binary, "summary", result))
    assert summary["status"] == "fail" and summary["completed_snapshots"] == summary["requested_snapshots"] == 6
    assert summary["comparison_basis"] == "previous_snapshot"
    assert summary["affected_routers"] == ["a", "b", "c", "d"]
    assert summary["affected_prefixes"] == ["10.10.4.0/24"]
    assert summary["assertion_evaluations"] == {"pass": 4, "fail": 2, "incomplete": 0}
    assert summary["newly_failing_assertion_transitions"] == summary["recovered_assertion_transitions"] == 2
    issue, = summary["affected_assertions"]
    assert issue["failed_snapshots"] == 2 and issue["first_failure_snapshot_id"] == "event-2"
    assert issue["last_failure_snapshot_id"] == "event-4"
    for transition in summary["timeline"]:
        delta = compare(transition["before_snapshot_id"], transition["after_snapshot_id"])
        assert transition["route_counts"] == delta["route_counts"]
        assert transition["newly_failing_assertions"] == [a["assertion_id"] for a in delta["newly_failing_assertions"]]
    assert summary["route_counts"] == {
        key: sum(step["route_counts"][key] for step in summary["timeline"]) for key in summary["route_counts"]
    }

    sweep = directory / "sweep"
    cli(binary, "n-1", diamond, "--out", sweep)
    summary = json.loads(cli(binary, "summary", sweep / "result.json"))
    assert summary["comparison_basis"] == "baseline" and summary["status"] == "pass"
    assert len(summary["timeline"]) == 8
    assert all(step["before_snapshot_id"] == "baseline" for step in summary["timeline"])
    assert summary["assertion_failure_scopes"] == {"source_outage": 1, "destination_outage": 1}

    scenario = json.loads(cli(binary, "validate", diamond, "--normalized"))
    assert scenario["events"][0]["id"] == "fail-bd"
    scenario["events"] = scenario["events"][:2] + [
        {**scenario["events"][1], "id": "fail-cd-again", "seq": 5},
    ]
    before = write_json(directory / "before.json", scenario)
    repeated = directory / "repeated"
    cli(binary, "simulate", before, "--out", repeated, code=1)
    summary = json.loads(cli(binary, "summary", repeated / "result.json"))
    noop = summary["timeline"][-1]
    assert noop["event"]["sequence"] == 5
    assert noop["event"]["disposition"] == "noop" and not any(noop["route_counts"].values())
    assert noop["newly_failing_assertions"] == []
    assert summary["newly_failing_assertion_transitions"] == 1
    assert summary["affected_assertions"][0]["failed_snapshots"] == 2

    scenario["events"] = []
    for link in scenario["links"]:
        if link["id"] in {"bd", "cd"}:
            link["initial_state"] = "down"
    scenario["assertions"].append({**scenario["assertions"][0], "id": "new-check"})
    after = write_json(directory / "after.json", scenario)
    delta = json.loads(cli(binary, "compare", before, after, "--scenarios"))
    assert delta["after"]["snapshot_id"] == "baseline"
    assert len(delta["withdrawn_routes"]) == 3
    assert [a["assertion_id"] for a in delta["newly_failing_assertions"]] == ["a-to-d"]
    assert delta["other_assertion_changes"] == [{"assertion_id": "new-check", "before": "absent", "after": "fail"}]
    delta = json.loads(cli(binary, "compare", before, after, "--scenarios", "--from", "event-2"))
    assert delta["newly_failing_assertions"] == [] and not any(delta["route_counts"].values())
    baseline_only = directory / "baseline-only"
    cli(binary, "simulate", after, "--out", baseline_only, code=1)
    summary = json.loads(cli(binary, "summary", baseline_only / "result.json"))
    assert summary["timeline"] == [] and summary["newly_failing_assertion_transitions"] == 0
    assert all(issue["first_failure_snapshot_id"] == "baseline" for issue in summary["affected_assertions"])

    parallel = json.loads(cli(binary, "validate", diamond, "--normalized"))
    parallel["events"] = []
    primary = next(link for link in parallel["links"] if link["id"] == "bd")
    alternate = {**primary, "id": "bd-alt", "initial_state": "down"}
    parallel["links"].append(alternate)
    write_json(before, parallel)
    primary["initial_state"], alternate["initial_state"] = "down", "up"
    write_json(after, parallel)
    delta = json.loads(cli(binary, "compare", before, after, "--scenarios"))
    swap, = delta["ecmp_changes"]
    assert swap["router"] == "b" and swap["before_count"] == swap["after_count"] == 1
    assert swap["removed"] == [{"neighbor": "d", "link": "bd", "interface": "bd@b"}]
    assert swap["added"] == [{"neighbor": "d", "link": "bd-alt", "interface": "bd-alt@b"}]
    assert delta["metric_changes"] == []
    assert not cli(binary, "compare", result, result, "--to", "unknown", code=2)

    document = json.loads(result.read_text())
    for completed in (0, 3):
        partial = {**document, "status": "incomplete", "incomplete_reason": "test budget reached",
                   "completed_snapshots": completed, "requested_snapshots": len(document["snapshots"]),
                   "snapshots": document["snapshots"][:completed], "events": document["events"][:max(0, completed - 1)],
                   "assertions": json.loads(json.dumps(document["assertions"][:completed]))}
        rehash(partial)
        path = write_json(directory / "partial.json", partial)
        summary = json.loads(cli(binary, "summary", path, code=3))
        assert summary["completed_snapshots"] == completed and summary["requested_snapshots"] == 6
        assert len(summary["timeline"]) == max(0, completed - 1)
        if completed:
            delta = json.loads(cli(binary, "compare", result, path, "--to", "event-2", code=3))
            assert delta["after"]["incomplete_reason"] == "test budget reached"
        assert not cli(binary, "compare", result, path, "--to", "event-5", code=3)

    bad = write_json(directory / "tampered.json", {**document, "scenario_name": "tampered"})
    assert not cli(binary, "summary", bad, code=2)
    assert not cli(binary, "compare", result, bad, code=2)

    # Keep event/snapshot references intact while putting the pairs out of order.
    document["events"][1], document["events"][3] = document["events"][3], document["events"][1]
    document["snapshots"][2], document["snapshots"][4] = document["snapshots"][4], document["snapshots"][2]
    rehash(document)
    out_of_order = write_json(directory / "out-of-order.json", document)
    assert not cli(binary, "summary", out_of_order, code=2)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temporary:
        run(sys.argv[1], Path(sys.argv[2]), Path(temporary))
