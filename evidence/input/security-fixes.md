# Input security fixes

**Run date:** 2026-10-02. Tested working-tree changes based on commit `df79206982742018259f93476ec9662901dfc394`.

All three issues from the input review are fixed:

- CLI summaries, validation errors, and unknown-command diagnostics escape terminal controls and malformed UTF-8 bytes. Canonical JSON and scenario string values retain their original semantics.
- JSON SAX parsing handles valid surrogate pairs, rejects duplicate keys after escape decoding, preserves original token locations, and shares semantic validation with YAML. `.json` sources require strict JSON; content detection also accepts JSON under other names while retaining flow-style YAML.
- YAML events build a bounded arena directly. Anchor IDs identify aliases; references to active containers are rejected as cycles. No global scan of previously visited nodes remains. Reads and parse events enforce byte, node, collection, scalar, and depth budgets. Assertion prefix resolution uses binary search over the validated disjoint prefix set.

The [model contract](../../docs/model.md#input-validation-and-unsupported-constructs) documents the default limits and `InputLimits` overrides. Existing supported model/schema versions are unchanged.

## Acceptance results

All four CTest checks passed in each build:

| Build | Compiler | Checks |
| --- | --- | --- |
| `host-debug` | Apple Clang 21.0.0 | 4/4 passed |
| `gcc-debug` | GCC 12.5.0 | 4/4 passed |
| `clang-debug` | upstream Clang 18.1.8 | 4/4 passed |
| `build/security-review/asan` | Apple Clang 21.0.0, ASan and UBSan | 4/4 passed |

The original 5 valid and 17 invalid fixtures still pass. The constructed physical-topology test remains unchanged. Added checks cover exact budget boundaries, bounded file reads, aliases and cycles, decoded duplicate keys, JSON syntax and Unicode, token source locations, safe stdout/stderr, prefix/address-space endpoints, and a 32,000-event input.

The equivalent-declaration fixture retains its existing SHA-256:

```text
606c53d0e6f93134c0948bff06854d71d474926a6d7a968d69ccd1db89d3d199
```

A deterministic 1,000-case mutation check ran under ASan/UBSan, alternating YAML and strict JSON sources. It produced no crashes, sanitizer findings, timeouts, malformed UTF-8 output, or unescaped terminal controls. The seed was `20261002`; this bounded mutation check does not establish exhaustive fuzz coverage.

## Diagnostic scaling measurements

Single samples from the native **Debug** build, using the review's one-router, one-prefix workload:

| Format | Events | Source bytes | Seconds |
| --- | ---: | ---: | ---: |
| JSON | 16,000 | 1,198,883 | 0.483 |
| JSON | 32,000 | 2,430,883 | 0.944 |
| JSON | 64,000 | 4,894,883 | 1.914 |
| YAML | 64,000 | 4,702,858 | 5.040 |

The original Debug validator took 6.093 seconds for 32,000 JSON events and exceeded a 12-second timeout for 64,000. The new 64,000-event YAML and JSON inputs produced identical hashes. These are local diagnostic samples, not release benchmarks or portable performance claims.

## Reproduction and raw evidence

```sh
cmake --build --preset host-debug
ctest --test-dir build/host-debug --output-on-failure
cmake --build --preset gcc-debug
ctest --test-dir build/gcc-debug --output-on-failure
cmake --build --preset clang-debug
ctest --test-dir build/clang-debug --output-on-failure
```

The compiler presets need the compiler paths described in the README when configuring a new build. The sanitizer build used cached dependency source overrides and these flags:

```text
-fsanitize=address,undefined -fno-omit-frame-pointer -fno-sanitize-recover=all
```

The ignored `build/security-fixes/` directory contains build/test logs for all configurations, `malformed_probe.py`, `malformed-results.json`, `scaling-results.json`, and a SHA-256 manifest of tested source inputs. The tracked regression checks are [input_limits.cpp](../../tests/integration/input_limits.cpp) and [validate_regressions.py](../../tools/input/validate_regressions.py).
