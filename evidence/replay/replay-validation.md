# Failure replay and reachability validation

Validated October 5, 2026, on macOS arm64. The tested implementation provides all four availability events, atomic converged snapshots, universal ECMP analysis, validated drop/partition/cycle witnesses, canonical simulation output, and CLI explanation. FRR differential labs and published time/memory/scaling measurements remain open.

## Observable behavior

`engine::replay` computes a baseline and a complete candidate after each sequence-ordered event. Timestamps annotate the trace without sleeping. Equal-time events remain separate snapshots. Idempotent operations are recorded as `noop`. Router restoration changes no link administrative state. Incomplete routing candidates never reach the observer; simulation retains only snapshots whose entire assertion set completed.

`analysis::DestinationAnalysis` checks physical link/interface identity and availability, finds cyclic SCCs with iterative Kosaraju traversals, and propagates failed terminals/edges/cycles backwards. Any possible failed branch rejects universal delivery, including a cycle with a delivery exit. Destination graphs are cached within a snapshot. Witness selection follows the first sorted failed/unsafe alternative and stops at a drop or repeated vertex. No recursion or complete-path enumeration is used. No-route certificates identify the exact available component and unavailable boundary links/routers.

Every emitted witness passes a separate C++ validator for FIB membership, physical state, terminal/cycle closure, and exact component/frontier evidence. The independent Python reference checks these again using serialized snapshots and independently replayed physical state. Result, event-array, assertion-array, and snapshot hashes are also checked independently.

`simulate FILE --out DIR` produces canonical `result.json` and separate `run.json` provenance; existing output artifacts are rejected and preserved. `explain RESULT --assertion ID` verifies digests and references before displaying paths/frontiers. Exit codes are 0 passing, 1 complete with failed requirements, 2 invalid input/result, and 3 incomplete analysis/output failure. Limit failures return incomplete JSON with explicit requested/completed coverage, including zero completed snapshots when preflight fails. Earlier passing snapshots never turn an incomplete trace into a pass.

## Diamond acceptance artifact

[diamond-result.json](diamond-result.json) is the full canonical result; [diamond-explanation.txt](diamond-explanation.txt) is the CLI explanation. No host paths or timing samples enter the canonical result.

| Snapshot | a's next-hop links | a-to-d |
| --- | --- | --- |
| baseline | ab, ac | pass, metric 3 |
| fail-bd | ac | pass |
| fail-cd | absent | no_route; component a/b/c, frontier bd/cd administratively down |
| restore-bd | ab | pass |
| fail-d | absent | destination_down |
| restore-d | ab | pass; cd remains administratively down |

This deliberately failing trace exits 1, continues through restoration, and evaluates all six snapshots.

## Independent acceptance checks

[check_replay.py](../../tests/reference/check_replay.py) independently mutates physical state and compares the full route domain after every event with the existing Python Floyd–Warshall oracle, including absent/extra routes, metrics, protocol costs, and complete interface sets. It independently computes physical components/frontiers, validates every failure's current path and route decision, verifies all digests and references, checks statuses, and compares canonical bytes for original declarations, reversed declarations/endpoints/events/assertions, and repeat runs.

The corpus has **42 traces, 373 snapshots, and 4,830 validated failed assertion records**: the diamond, two restoration fixtures, seven named routing graphs, and 32 generated tiny graphs. Each of the latter 39 graphs receives eight generated availability events and every router/prefix source-destination assertion. Generation uses a 32-bit LCG with seed `0x52504633`, recurrence `state = (1664525 * state + 1013904223) mod 2^32`, and selection `(state >> 8) mod bound`; input graph generation is the existing fixed baseline routing corpus. `parallel-restoration` covers asymmetric/parallel links, actual link-up while an endpoint is disabled, link-down while disabled, restoration, equal timestamps, and no-ops. `initial-down-restoration` checks initial source/origin/link failures and local attachment delivery.

SHA-256 of concatenated original canonical result files, each including its trailing newline in corpus order:

```text
54d3222c07f6a1bc7fc3671d256cca71262c1397ffe4d36d432ad9f5909fec0c
```

[compiler-determinism.txt](compiler-determinism.txt) checks the entire replay corpus against Apple Clang, GCC, and upstream Clang in one invocation. All result bytes agree. The same digest appears in sanitizer and fresh-build logs. The existing 87-case baseline oracle retains its baseline routing digest `9439e765869a1a636f240a55a4ddd01adf743795bef376587f883e8d56e3d505`.

[replay_analysis.cpp](../../tests/integration/replay_analysis.cpp) supplies malformed FIBs directly to the checker: one bad ECMP branch despite another delivery branch, a cycle with a delivery exit, an empty remote action, an invalid interface, and a connected action at the wrong router. It checks stale-FIB link/next-hop failures, source/destination unavailability, deterministic witness selection under reversed next-hop order and repeat calls, rejection of corrupt source/component/cycle witnesses, no-op/restoration state semantics, and atomic publication. All 64 combinations of outgoing FIB edge subsets at the diamond's three transit/source routers match an independent three-color traversal reference for all four sources. A 20,000-router supplied chain and cycle protect iterative analysis/witness validation from stack exhaustion. These fixtures exercise checker behavior independently of correct SPF-generated tables; malformed FIBs are not public scenario events.

Resource checks cover graph edges, snapshots, assertion evaluations, destination analyses, analyzed vertices/edges, retained routes/next-hop references, canonical output, and routing exhaustion. CLI checks cover explanation, unknown assertions, invalid scenarios, corrupted digests, duplicate result JSON keys, unsupported schemas, excessive result nesting, and preservation of existing output artifacts.

## Toolchain and sanitizer evidence

Exact tool versions, dependency tags/commits, compiler flags, and host details are in [toolchains.json](toolchains.json). Native commands use CMake 4.4.4 and Ninja 1.13.2. CTest uses Python 3.13.16; the manual cross-compiler replay invocation also passed with Python 3.9.6. Debug core/test/application code uses C++20 and `-Wall -Wextra -Wpedantic`.

| Configuration | Result | Build / validation log |
| --- | --- | --- |
| Apple Clang 21.0.0 | 8/8 checks pass | [host-build.txt](host-build.txt), [host-validation.txt](host-validation.txt) |
| GCC 12.5.0 | 8/8 checks pass | [gcc-build.txt](gcc-build.txt), [gcc-validation.txt](gcc-validation.txt) |
| Clang 18.1.8 | 8/8 checks pass | [clang-build.txt](clang-build.txt), [clang-validation.txt](clang-validation.txt) |
| Apple Clang 21, ASan + UBSan | 8/8 checks pass, no findings | [sanitizer-build.txt](sanitizer-build.txt), [sanitizer-validation.txt](sanitizer-validation.txt) |
| Fresh source copy, GCC 12.5.0 | configure/build and 8/8 checks pass | [fresh-gcc.txt](fresh-gcc.txt) |
| Fresh source copy, Clang 18.1.8 | configure/build and 8/8 checks pass | [fresh-clang.txt](fresh-clang.txt) |

Fresh builds used a temporary copy of the replay implementation source, no existing objects/build cache, and locally cached sources at the verified pinned dependency tags. They validate the working implementation rather than claim a committed release checkout. [source-inputs.sha256](source-inputs.sha256) identifies source/docs/fixtures excluding evidence and generated files. Logs replace the workspace and temporary source roots with `<repo>` and `<fresh>` placeholders. No new upstream-Clang sanitizer-runtime pass is claimed; the older baseline routing startup limitation remains documented there. The verified sanitizer configuration here uses Apple Clang.

## Reproduction

```sh
cmake --preset host-debug
cmake --build --preset host-debug
ctest --test-dir build/host-debug --verbose --timeout 60
python3 tests/reference/check_replay.py build/host-debug/routeproof
build/host-debug/routeproof simulate examples/diamond-failures.yaml --out results/diamond
build/host-debug/routeproof explain results/diamond/result.json --assertion a-to-d
```

Use a fresh output directory for each simulation. The last two commands intentionally return 1 for the diamond's failed requirements. Set `ROUTEPROOF_GCC_CXX=/opt/homebrew/bin/g++-12` or `ROUTEPROOF_CLANG_CXX=/opt/homebrew/opt/llvm@18/bin/clang++` and build the corresponding presets to reproduce compiler checks. Run all three together with:

```sh
python3 tests/reference/check_replay.py \
  build/host-debug/routeproof build/gcc-debug/routeproof build/clang-debug/routeproof
```

The sanitizer build reuses `build/host-sanitizers` configured with `/usr/bin/c++`, `-fsanitize=address,undefined -fno-omit-frame-pointer`, and executable link flags `-fsanitize=address,undefined`. Configure it as documented in [routing-validation.md](../routing/routing-validation.md), then rebuild and run CTest after these source changes. Fresh-build logs contain the exact configure/build/test commands and cached dependency overrides.

No FRR agreement, Linux RSS, throughput, scaling, or network-convergence-time claim is made by this evidence. `run.json` contains a diagnostic monotonic simulation-processing sample; published measurements remain an open acceptance gate.

## Review fixes

[review-fixes.md](review-fixes.md) records the follow-up fixes for cycle-entry overflow, explanation status/reference consistency, and required incomplete-result diagnostics, with refreshed compiler/sanitizer checks. The original logs and `source-inputs.sha256` above identify the initial replay validation; `review-fix-inputs.sha256` identifies the source after these fixes.
