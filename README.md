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

**Current status:** Phases 0 and 1 are complete. The tool strictly validates and canonicalizes v1 scenario input, builds an interface-aware physical topology, and reports canonical scenario hashes. The first-hop routing engine, replay, reachability analysis, FRR comparisons, and benchmark measurements are not implemented.

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
```

The validator rejects unsupported fields and semantic errors with source locations. It supports strict `.json` files, including escaped Unicode, and YAML with nonrecursive aliases. Input budgets cap source bytes, nodes, collection entries, scalar bytes, and nesting; defaults and library overrides are documented in the [model contract](docs/model.md#input-validation-and-unsupported-constructs). Text summaries and diagnostics escape terminal controls. `--normalized` prints canonical JSON; the summary form includes its SHA-256.

CTest runs the CLI fixtures, constructed physical-topology integration check, parser-limit boundaries, and regressions for JSON interoperability, safe output, aliases, prefix ownership, and larger input. The [input security fixes](evidence/phase1/security-fixes.md) record their validation.

Read the [model contract](docs/model.md), [v0.1 acceptance checklist](docs/acceptance.md), and [detailed implementation plan](docs/implementation-plan.md) for semantics, phase gates, validation strategy, and release scope. The simulator commands in the plan are planned interfaces.
