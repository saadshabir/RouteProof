# Phase 1 input and topology evidence

**Run date:** 2026-09-28

**Scope:** canonical input, semantic validation, and physical topology. Routing calculations are not implemented in this phase.

## Build configurations

The implementation configured and built with the checked-in presets:

```sh
cmake --preset host-debug
cmake --build --preset host-debug
ROUTEPROOF_GCC_CXX=/opt/homebrew/bin/g++-12 cmake --preset gcc-debug
cmake --build --preset gcc-debug
ROUTEPROOF_CLANG_CXX=/opt/homebrew/opt/llvm@18/bin/clang++ cmake --preset clang-debug
cmake --build --preset clang-debug
```

Observed development tools were CMake 4.4.3, Ninja 1.13.2, Apple Clang 21.0.0, GCC 12.5.0, and upstream Clang 18.1.8. All configurations used the pinned yaml-cpp 0.9.0, nlohmann/json 3.12.0, and PicoSHA2 1.0.1 sources declared in `cmake/Dependencies.cmake`.

For the GCC and upstream Clang configurations, CMake FetchContent source overrides reused the dependency source trees populated by the host configure. A fresh online configure can omit those overrides and fetch the same pinned sources.

The corrected sources were also committed in a temporary repository, cloned into a fresh checkout, and built with CMake 3.25.2, Ninja 1.11.1, GCC 12.5.0, and upstream Clang 18.1.8. Both compilers passed the acceptance checks using Python 3.9.6. The checkout stayed clean before and after the builds. [minimum-toolchains.txt](minimum-toolchains.txt) records the temporary snapshot, commands, cached dependency overrides, build output, and verbose acceptance results. Checkout/tool/cache paths are labeled placeholders in that log. [source-inputs.sha256](source-inputs.sha256) records the checked build sources, schemas, tests, and YAML inputs; evidence and documentation are excluded so refreshing this report does not change the source identity.

## Input and constructed-topology gates

Run both acceptance checks for each configured build:

```sh
ctest --test-dir build/host-debug --output-on-failure
ctest --test-dir build/gcc-debug --output-on-failure
ctest --test-dir build/clang-debug --output-on-failure
```

Each build passed 2 CTest checks. `phase1.input_fixtures` passed 5 valid fixtures and 17 invalid fixtures. Its Python runner independently hashes normalized UTF-8 JSON, compares equivalent declarations byte-for-byte, checks normalized directional costs and initial state, and requires source locations on invalid input. `phase1.physical_topology` loads the physical-state fixture through the C++ loader and inspects the constructed adjacency, all four directional/interface arcs, distinct link/router indexes, independent state, and prefix ownership at both available and unavailable routers.

The raw input output is preserved in [fixture-validation.txt](fixture-validation.txt), the direct graph-check output in [topology-validation.txt](topology-validation.txt), and all three development CTest runs in [compiler-validation.txt](compiler-validation.txt). The valid-input hashes, rejection diagnostics, and graph-check output matched across Apple Clang, GCC, and upstream Clang.

Equivalent declarations `equivalent-a.yaml` and `equivalent-b.yaml` produced this identical canonical hash with all three compilers:

```text
606c53d0e6f93134c0948bff06854d71d474926a6d7a968d69ccd1db89d3d199
```

The pair changes declaration order for three routers, three links, three prefixes, two events, and three assertions. It reverses link endpoints while swapping directional costs and omits default `initial_state: up` in one input. The physical-state fixture retains two parallel links, asymmetric costs, one unavailable router, one administratively down link, and an attachment at each router. Valid fixtures exercise prefix lengths `/1` and `/32` and correctly typed explicit YAML tags.

The six added invalid fixtures expose default routes, unknown tags in the standard YAML namespace, three collection/tag mismatches, and a non-string mapping key. The pre-fix executable accepted all six; the corrected executable rejects each with exit 2 and a source location. The event-order regression also requires the exact offending event location (`event-order.yaml:10:5`): sortable validation records retain `YAML::Mark` values so YAML node alias assignments cannot change the diagnostic during sorting. Both schema prefix patterns reject `/0` and `/33` and permit `/1` and `/32`.

## Implemented contract

- The loader rejects duplicate keys, multiple YAML documents, unsupported or mismatched tags, non-string mapping keys, unknown fields, unsupported enum values, invalid scalar types, and recursive aliases.
- Semantic checks cover IDs, unique numeric router IDs, endpoint/origin/event/assertion resolution, self-links, canonical IPv4 and network prefixes in `1..32`, default-route rejection, disjoint prefix ownership, cost/timestamp/sequence ranges, event ordering, and the conservative OSPF cost bound.
- Canonical JSON sorts object keys and normalizes router, link, prefix, event, and assertion arrays. Link endpoint order is canonicalized with directional costs swapped together. Omitted initial state is emitted as `up`.
- The topology builder creates a directed arc per endpoint/interface, preserving parallel links, directional cost, physical link identity, and independent router/link state. Prefix indexes retain ownership by origin router.

This evidence closes Phase 1 only. SPF, forwarding tables, replay, and reachability remain unimplemented and have no performance claims.
