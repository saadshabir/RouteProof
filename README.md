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

**Current status:** Phases 0–2 are complete. The tool validates and canonicalizes v1 scenarios and computes baseline prefix routes with directional costs, connected delivery, and complete ECMP interface sets. An independent tiny-graph oracle validates the routing engine. Failure replay, reachability analysis, FRR comparisons, and benchmark measurements remain future phases.

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
build/host-debug/routeproof validate examples/phase1/valid/diamond.yaml
build/host-debug/routeproof validate examples/phase1/valid/diamond.yaml --normalized
python3 tools/phase1/validate_fixtures.py
build/host-debug/routeproof routes examples/phase1/valid/diamond.yaml
build/host-debug/routeproof routes examples/phase2/merged-ecmp.json --timing
```

The validator rejects unsupported fields and semantic errors with source locations. It supports strict `.json` files, including escaped Unicode, and YAML with nonrecursive aliases. Input budgets cap source bytes, nodes, collection entries, scalar bytes, and nesting; defaults and library overrides are documented in the [model contract](docs/model.md#input-validation-and-unsupported-constructs). Text summaries and diagnostics escape terminal controls. `--normalized` prints canonical JSON; the summary form includes its SHA-256.

`routes` prints canonical baseline JSON described in [baseline-v1.schema.json](schemas/baseline-v1.schema.json). Events and assertions are validated but not executed by this command; exit 0 means baseline route calculation completed, not that reachability requirements passed. Unreachable prefixes have no route row, and unavailable routers have empty tables. Connected routes have metric 0 and empty next hops; `protocol_cost` preserves the stub advertisement calculation separately. Optional `--timing` writes `baseline_compute_ns` to stderr, covering only route computation and invariant validation after parsing/state initialization, before serialization. This diagnostic hook is not a scenario benchmark or network convergence measurement.

CTest runs the CLI fixtures, constructed physical-topology integration check, parser-limit boundaries, and regressions for JSON interoperability, safe output, aliases, prefix ownership, and larger input. It also compares routing against an independent Python Floyd–Warshall oracle on named and generated tiny graphs, with input-order and repeat invariance checks. [Phase 2 evidence](evidence/phase2/routing-validation.md) records the routing coverage and toolchain checks. The [input security fixes](evidence/phase1/security-fixes.md) record their validation.

Read the [model contract](docs/model.md), [v0.1 acceptance checklist](docs/acceptance.md), and [detailed implementation plan](docs/implementation-plan.md) for semantics, phase gates, validation strategy, and release scope. The simulator commands in the plan are planned interfaces.
