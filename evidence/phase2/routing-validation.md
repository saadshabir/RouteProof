# Phase 2 routing validation

Validated on October 4, 2026, on macOS arm64. Phase 2 is complete: baseline SPF, prefix routes, connected delivery, complete interface-aware ECMP, an independent oracle, and a baseline timing hook are implemented. Failure replay, reachability analysis, FRR comparison, and published scenario/memory/scaling measurements remain open.

## Implemented behavior

- Per-source priority-queue Dijkstra over effective directed arcs, followed by first-hop propagation over the shortest-path DAG in settled distance order.
- Unavailable sources/origins and physical partitions produce absent routes. Administrative link state is independent of router state.
- Prefix routes use source-to-origin distance plus stub cost. Local connected delivery has metric 0, no next hops, and a separate protocol calculation cost equal to the stub cost.
- Complete first-hop tuples preserve parallel physical link/interface identities. Prefixes sharing a source/origin share immutable next-hop sets; source scratch storage is reused.
- Deterministic prefix lookup, output ordering, checked cost arithmetic, and budgets for route entries, logical next-hop references, and per-source scratch next hops.
- Runtime validation of every selected interface's availability, shortest-path equality, and strict distance decrease toward its destination origin.
- `routeproof routes FILE [--timing]` prints baseline diagnostic JSON. It validates but does not execute events/assertions. Exit 0 means routing completed, not that reachability passed. Parsing errors exit 2; incomplete calculation exits 3 without a partial route document.

The output contract is [baseline-v1.schema.json](../../schemas/baseline-v1.schema.json). Optional stderr timing uses `steady_clock` and includes only routing computation and invariant validation, excluding parsing, state initialization, and serialization. Timing never changes route JSON. No performance claim is made here.

## Independent oracle and fixtures

[check_routing.py](../../tests/reference/check_routing.py) uses Python Floyd–Warshall, independently deriving each first-hop interface from outgoing cost plus neighbor-to-origin distance. It does not reuse Dijkstra or DAG propagation. It compares the entire expected route domain, including absent and extra rows, local metadata, distances, costs, and every next-hop tuple.

Seven named fixtures in [examples/phase2](../../examples/phase2):

| Fixture | Coverage |
| --- | --- |
| merged-ecmp | Diamond alternatives survive a merge and two more hops; multiple prefixes at one origin |
| unequal-depth-ecmp | Equal-cost alternatives with different hop counts, including a direct and indirect first-hop tie |
| parallel-asymmetric | Equal forward costs over parallel links; distinct reverse costs and interfaces |
| disconnected | Two physical components and absent routes between them |
| initial-unavailability | Unavailable transit/origin routers and independently down links |
| single-router | Connected-only delivery without physical links |
| cost-bound | Maximum directional costs, asymmetric reverse costs, and distances exceeding 16-bit range |

Another 80 cases contain 1–8 routers, directional/parallel links, and initial state variations. Generation uses a 32-bit LCG with seed `0x52504632`, recurrence `state = (1664525 * state + 1013904223) mod 2^32`, and choice `(state >> 8) mod bound`. The checked-in script fixes generation order.

All **87 cases, 1,044 route rows, and 781 logical next-hop references** match. Each case runs in original and reversed declaration/endpoint order, then repeats with timing enabled. All three outputs must match byte for byte. The SHA-256 of concatenated original baseline outputs, including trailing newlines in corpus order, is:

```text
9439e765869a1a636f240a55a4ddd01adf743795bef376587f883e8d56e3d505
```

The same digest appears for GCC, upstream Clang, Apple Clang, host sanitizers, and both fresh source builds. [routing.cpp](../../tests/integration/routing.cpp) additionally checks sharing, address/prefix lookup, connected metadata, nondecreasing distances on link removal, origin unavailability, restoration counters, exact route/reference budget boundaries, scratch exhaustion, mismatched state dimensions, arithmetic overflow, and rejection of corrupted distance ranks.

## Build and acceptance evidence

CMake 4.4.4, Ninja 1.13.2, Python 3.13.16. Debug builds use C++20 without language extensions and core/application warnings `-Wall -Wextra -Wpedantic`.

| Configuration | Result | Log |
| --- | --- | --- |
| Apple Clang 21.0.0.21000334, host-debug | 6/6 CTest checks pass | [host-validation.txt](host-validation.txt) |
| GCC 12.5.0, gcc-debug | 6/6 CTest checks pass | [gcc-validation.txt](gcc-validation.txt) |
| Upstream Clang 18.1.8, clang-debug | 6/6 CTest checks pass | [clang-validation.txt](clang-validation.txt) |
| Apple Clang 21, ASan + UBSan | 6/6 CTest checks pass, no sanitizer findings | [sanitizer-validation.txt](sanitizer-validation.txt) |
| Fresh source copy, GCC 12.5.0 | Configure/build and 6/6 checks pass | [fresh-gcc.txt](fresh-gcc.txt) |
| Fresh source copy, Clang 18.1.8 | Configure/build and 6/6 checks pass | [fresh-clang.txt](fresh-clang.txt) |

Fresh builds used a temporary source copy of the original Phase 2 working files, before the unavailable-source review fix below, no existing objects or build cache, and locally cached dependency sources at the pinned tags `yaml-cpp-0.9.0`, `v3.12.0`, and `v1.0.1`. This validates that uncommitted implementation; it is not a claim of a new committed clean-checkout release. [source-inputs.sha256](source-inputs.sha256) identifies those copied files excluding evidence. Logs replace workspace/temp roots with `<repo>`, `<source>`, and `<build>` placeholders.

Upstream Clang 18 ASan/UBSan executables stalled during startup on this host, including `routeproof --version`, both inside and outside the sandbox. The owned processes were stopped after approximately two minutes; no test pass is claimed for that sanitizer runtime. [clang-sanitizer-startup.txt](clang-sanitizer-startup.txt) retains the failure. Rebuilding with host Apple Clang 21 passed the full sanitizer suite. The root cause of the older runtime startup stall has not been established.

## Unavailable-source review fix

Forwarding calculation now checks both physical-state dimensions once before routing and skips unavailable sources before SPF workspace resets, sharing-cache allocation, and prefix scanning. This removes quadratic work for an all-down topology while preserving an empty table for every router.

The routing integration test constructs 100,000 unavailable routers and one prefix, verifies empty tables and zero route/next-hop counts with zero routing budgets, rejects mismatched router and link state dimensions even when all routers are down, then restores the origin and checks its connected route. The routing contract has a 60-second CTest timeout to catch the previous quadratic work without a host-specific timing assertion.

Rebuilt Apple Clang, GCC, upstream Clang, and host ASan/UBSan configurations each pass all six CTest checks, including the larger regression. The independent 87-case oracle retains the corpus digest above. [unavailable-sources-fix.txt](unavailable-sources-fix.txt) records commands and results; [unavailable-sources-fix.sha256](unavailable-sources-fix.sha256) identifies the updated source files excluding evidence. The original fresh-build logs and source manifest remain evidence for the implementation before this fix.

## Reproduction

```sh
cmake --preset host-debug
cmake --build --preset host-debug
ctest --test-dir build/host-debug --output-on-failure
python3 tests/reference/check_routing.py build/host-debug/routeproof
build/host-debug/routeproof routes examples/phase1/valid/diamond.yaml
build/host-debug/routeproof routes examples/phase2/merged-ecmp.json --timing
```

Set `ROUTEPROOF_GCC_CXX` or `ROUTEPROOF_CLANG_CXX` to the installed compiler and use the corresponding `gcc-debug`/`clang-debug` presets to reproduce those checks. Fresh-build logs retain exact configure arguments, including cached dependency overrides.

The sanitizer configuration used:

```sh
cmake -S . -B build/phase2-host-sanitizers -G Ninja \
  -DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_COMPILER=/usr/bin/c++ \
  -DCMAKE_CXX_FLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer' \
  -DCMAKE_EXE_LINKER_FLAGS='-fsanitize=address,undefined'
cmake --build build/phase2-host-sanitizers
ctest --test-dir build/phase2-host-sanitizers --verbose --timeout 60
```

Local cached dependency overrides were supplied as in the fresh-build logs. [diamond-baseline.json](diamond-baseline.json) records the declared diamond's initial routing snapshot: router `a` reaches `10.10.4.0/24` at metric 3 through both `ab@a` and `ac@a`; router `d` delivers locally. Its five events and reachability assertion are not executed by the Phase 2 command.
