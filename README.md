# RouteProof

RouteProof is a C++20 tool for analyzing how routing changes affect forwarding.

Its central question is: **If a link, router, or routing rule changes, which traffic becomes unreachable, exposed, looped, or unexpectedly rerouted?**

The first release has five deliverables:

1. A C++20 engine with a defined single-area OSPF-style model, prefixes, shortest paths, and ECMP.
2. Link/router failures and restoration with deterministic replay.
3. Reachability analysis covering every modeled ECMP branch, with useful failure explanations.
4. Converged route-cost and next-hop comparisons against small FRRouting labs.
5. Reproducible scenario-processing time, memory, and scaling measurements.

Each event produces a converged forwarding snapshot. Lean, transient convergence, BGP, Prometheus, and visualization are optional follow-up work.

**Current status:** The tool validates and canonicalizes v1 scenarios and computes baseline prefix routes with directional costs, connected delivery, and complete ECMP interface sets. It replays ordered link/router failures and restorations, checks every ECMP branch, and emits validated partition/drop/cycle witnesses. Independent tiny-graph and replay oracles validate routing and findings. The FRR lab generator, five-profile matrix, capture/cleanup harness, and route adapters are implemented with offline tests. Frozen workload generation, fresh-process core/CLI timing, RSS collection, and bounded scaling sweeps are implemented. Native measurements and a clean source reproduction are published; live Linux FRR agreement and authoritative Linux memory evidence remain open.

## Build

Requirements: CMake 3.25.2+, Ninja 1.11.1+, GCC 12.5.0+, or upstream Clang 18.1.8+. Apple Clang 21.0.0+ is supported for native builds. The default acceptance checks require Python 3.9+. Configure fetches the pinned yaml-cpp, nlohmann/json, and PicoSHA2 dependencies when they are not already available.

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

Read the [model contract](docs/model.md), [v0.1 acceptance checklist](docs/acceptance.md), and [detailed implementation plan](docs/implementation-plan.md) for semantics, acceptance gates, validation strategy, and release scope. [Replay evidence](evidence/replay/replay-validation.md) records replay, witness, compiler, and sanitizer checks. The [FRR workflow](docs/validation.md) implements `tools/frr/run_lab.py` and
`run_matrix.py`. Review all five generated profiles without Linux access:

```sh
python3 tools/frr/run_matrix.py --generate-only --out results/frr-generated
```

This saves configs, mappings, and expected snapshots, reports `skipped`, and exits
3; it does not claim FRR agreement. Live runs require a Linux amd64
Docker/Containerlab host and an explicitly supplied FRR 10.2.1 image digest. The
[Phase 4 evidence](evidence/frr/frr-validation.md) records offline coverage and the
open live acceptance gate. The [benchmark workflow](docs/benchmarks.md) provides frozen profiles and raw measurements:

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
