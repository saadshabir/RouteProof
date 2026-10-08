# RouteProof

RouteProof is a C++20 tool for analyzing how routing changes affect forwarding.

Its central question is: **If a link, router, or routing rule changes, which traffic becomes unreachable, exposed, looped, or unexpectedly rerouted?**

RouteProof has five deliverables:

1. A C++20 engine with a defined single-area OSPF-style model, prefixes, shortest paths, and ECMP.
2. Link/router failures and restoration with deterministic replay.
3. Reachability analysis covering every modeled ECMP branch, with useful failure explanations.
4. Converged route-cost and next-hop comparisons against small FRRouting labs.
5. Reproducible scenario-processing time, memory, and scaling measurements.

Each event produces a converged forwarding snapshot. Lean, transient convergence, BGP, Prometheus, and visualization are optional follow-up work.

**Current status:** v0.1 implementation and acceptance are complete. RouteProof validates strict scenarios, computes directional SPF and complete ECMP sets, replays link/router failures, and checks every forwarding branch with validated explanations. Two fresh Linux FRR runs agree for all 27 snapshots and 687 slots each. [Native benchmark evidence](evidence/bench/benchmark-validation.md) records timing, scaling and clean source reproduction; [Linux acceptance](evidence/linux/README.md) records authoritative small-workload RSS.

The [first performance pass](evidence/performance/README.md) reduces measured
simulation medians by 21–40% across 14 completed frozen workloads on the native
host, with byte-identical results. It reuses SPF buffers and no-op tables and
removes repeated JSON serialization, parsing and copying.

## Clone and run

Clone this repository or download its ZIP, then run the launcher:

```sh
git clone https://github.com/saadshabir/RouteProof.git
cd RouteProof
python3 tools/run.py demo --out results/diamond-demo
```

The launcher builds a Release executable, fetching pinned dependencies on the
first run. Later builds are incremental. The checked demo exits 0 when all six
snapshots and the two expected reachability failures match.

Use the same command for your own scenarios, benchmarks and acceptance checks:

```sh
python3 tools/run.py simulate examples/diamond-failures.yaml --out results/diamond
python3 tools/run.py explain results/diamond/result.json --assertion a-to-d
python3 tools/run.py bench --profile benchmarks/profiles/sparse-small.json --out results/bench
python3 tools/run.py test
```

`simulate` and `explain` preserve the CLI exit codes; this diamond intentionally
exits 1 for its two broken requirements. Output directories must be fresh.
`python3 tools/run.py --help` lists launcher commands. The `frr` command wraps
the lab matrix; live labs still require Linux, Docker, Containerlab and a pinned
FRR image, as described in [validation.md](docs/validation.md).

## Build requirements and manual commands

Requirements: Git, Python 3.9+, CMake 3.25.2+, Ninja 1.11.1+, GCC 12.5.0+, or upstream Clang 18.1.8+. Apple Clang 21.0.0+ is supported for native builds. Configure fetches the pinned yaml-cpp, nlohmann/json, and PicoSHA2 dependencies when they are not already available.

```sh
cmake --preset host-debug
cmake --build --preset host-debug
build/host-debug/routeproof --version
ctest --test-dir build/host-debug --output-on-failure
```

The compiler-gate presets accept explicit compiler paths, so they also work on macOS when GCC and upstream Clang are installed:

```sh
ROUTEPROOF_GCC_CXX=/path/to/g++ cmake --preset gcc-debug
cmake --build --preset gcc-debug
ROUTEPROOF_CLANG_CXX=/path/to/clang++ cmake --preset clang-debug
cmake --build --preset clang-debug
```

On Linux, the convenience presets are `linux-gcc-debug` and `linux-clang-debug`. Validate and inspect a scenario with:

```sh
build/host-debug/routeproof validate examples/input/valid/diamond.yaml
build/host-debug/routeproof validate examples/input/valid/diamond.yaml --normalized
python3 tools/input/validate_fixtures.py
build/host-debug/routeproof routes examples/input/valid/diamond.yaml
build/host-debug/routeproof routes examples/routing/merged-ecmp.json --timing
build/host-debug/routeproof simulate examples/diamond-failures.yaml --out results/diamond
build/host-debug/routeproof explain results/diamond/result.json --assertion a-to-d
```

The validator rejects unsupported fields and semantic errors with source locations. It supports strict `.json` files, including escaped Unicode, and YAML with nonrecursive aliases. Input budgets cap source bytes, nodes, collection entries, scalar bytes, and nesting; defaults and library overrides are documented in the [model contract](docs/model.md#input-validation-and-unsupported-constructs). Text summaries and diagnostics escape terminal controls. `--normalized` prints canonical JSON; the summary form includes its SHA-256.

`routes` prints canonical baseline JSON described in [baseline-v1.schema.json](schemas/baseline-v1.schema.json). Events and assertions are validated but not executed by this command; exit 0 means baseline route calculation completed, not that reachability requirements passed. Unreachable prefixes have no route row, and unavailable routers have empty tables. Connected routes have metric 0 and empty next hops; `protocol_cost` preserves the stub advertisement calculation separately. Optional `--timing` writes `baseline_compute_ns` to stderr, covering only route computation and invariant validation after parsing/state initialization, before serialization. This diagnostic hook is not a scenario benchmark or network convergence measurement.

`simulate FILE --out DIR` saves canonical `result.json` and separate `run.json` provenance. Use a fresh output directory; existing result/run artifacts are preserved and rejected. Assertions run on the baseline and after every event, including recorded no-ops and separate equal-time events. Exit codes are 0 for complete passing traces, 1 for complete traces with reachability failures, 2 for invalid input, and 3 for incomplete analysis or output failure. The diamond deliberately exits 1 because its partition and origin-down snapshots violate `a-to-d`; restoration still runs. `explain RESULT --assertion ID` prints the recorded status, paths, and frontier evidence, verifies result/snapshot digests, and returns the overall result status.

CTest runs the CLI fixtures, constructed physical-topology integration check, parser-limit boundaries, and regressions for JSON interoperability, safe output, aliases, prefix ownership, and larger input. It also compares routing against an independent Python Floyd–Warshall oracle on named and generated tiny graphs, with input-order and repeat invariance checks. [Routing evidence](evidence/routing/routing-validation.md) records the routing coverage and toolchain checks. The [input security fixes](evidence/input/security-fixes.md) record their validation.

Read the [model contract](docs/model.md), [v0.1 acceptance checklist](docs/acceptance.md), and [detailed implementation plan](docs/implementation-plan.md) for semantics, acceptance gates, validation strategy, and implementation scope. [Replay evidence](evidence/replay/replay-validation.md) records replay, witness, compiler, and sanitizer checks. The [FRR workflow](docs/validation.md) implements `tools/frr/run_lab.py` and
`run_matrix.py`. Review all five generated profiles without Linux access:

```sh
python3 tools/frr/run_matrix.py --generate-only --out results/frr-generated
```

This saves configs, mappings, and expected snapshots, reports `skipped`, and exits
3; it does not claim FRR agreement. Live runs require a Linux amd64
Docker/Containerlab host and an explicitly supplied FRR 10.2.1 image digest. The
[Linux acceptance evidence](evidence/linux/README.md) records the passing live matrix, tested image digest and clean reproduction. The [benchmark workflow](docs/benchmarks.md) provides frozen profiles and raw measurements:

```sh
cmake --preset host-release
cmake --build --preset host-release
build/host-release/routeproof bench --profile benchmarks/profiles/sparse-small.json --out results/bench
```

The scaling profile preserves budget-skipped/failed probes and exits 3 for a partial
sweep. Core processing, complete CLI time, and RSS have separate boundaries; these
are converged-scenario measurements. macOS RSS is provisional. See the
[Phase 5 evidence](evidence/bench/benchmark-validation.md) for measured coverage,
raw samples and clean source reproduction.

## CI and validation evidence

[Core CI](.github/workflows/ci.yml) builds with GCC and upstream Clang on Linux and
Clang on macOS, runs all CTest acceptance groups, and checks sanitizers and the
generated graph corpus separately. A clean-checkout job checks the diamond demo,
the launcher and the small benchmark as a harness smoke check. CI smoke timings
are not published performance measurements.

Run the checked demo on a fresh output path:

```sh
python3 tools/demo.py --binary build/host-release/routeproof --out results/diamond-demo
```

The runner exits 0 only when all six snapshots match, the partition and origin
failure occur as expected, restoration preserves `cd`'s administrative failure,
and repeated canonical bytes agree. Its underlying `simulate` and `explain`
commands deliberately exit 1 for the two broken reachability requirements.

[Validation evidence](evidence/README.md) is grouped by capability. Linux summaries
remain in Git; full live captures are available as GitHub Actions artifacts for
90 days and can be regenerated with the [Linux workflow](.github/workflows/linux-acceptance.yml).
To check a fresh committed checkout, run `python3 tools/verify_checkout.py --out results/checkout-check`.
It requires a clean source tree and fresh build directories and checks builds,
CTest, the demo, the small benchmark and offline FRR generation.
