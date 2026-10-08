# Phase 5 review fixes

Validation date: 2026-10-07 (America/Toronto).

All four review findings are fixed:

- A sweep requires every declared cell before its checkpoint can say `complete`.
  Declared, attempted and completed counts remain visible between cells.
- Binary source revision, dirty state and hashes come from the checkout identified
  by its CMake cache. Harness provenance is recorded separately; unavailable binary
  metadata cannot qualify as published measurement evidence.
- Reproduction validation reconciles workload dimensions, all snapshot/aggregate
  counters, simulation samples/distributions and the instrumentation ratio with
  raw manifests and canonical results. Completed processes must satisfy budgets.
- Final elapsed time enforces the timeout even when a successful worker exits
  before the monitor observes the deadline.

The benchmark suite now has **10 checks**, including deterministic regressions for
the missed deadline, external checkout selection, interruption between cells,
altered counters/timings/diagnostics, and dirty/different harness provenance.
All **10 CTest groups** pass in both the [working-tree Release run](host-release-tests.txt)
and [fresh clean Release build](clean-release-tests.txt).

The [fresh comparison](reproduction-comparison.json) passes for `sparse-small-16`.
[Original raw samples](small/summary.json) and [clean reproduction samples](reproduction/summary.json)
use the corrected harness and identical source inputs. The clean source and
harness Git statuses are empty, and the binaries have distinct paths. Canonical
result-file SHA-256 remains
`ff773b89a3298cc37f4d036a990abe6ae924c42b90eee78f66f81d9e09f35f2a`.
These descriptive runs do not establish a performance regression threshold.

The [source-input manifest](source-inputs.json) has SHA-256
`9ccd95071b19708530f0e195d490d90be744764a2eda4809491a67a46eaa2aed`.
The [source archive](source-snapshot.tar.gz) freezes the corrected sources and tests;
[commands](commands.txt) document reconstruction and verification. The
[external-binary check](external-binary-provenance.json) also verifies a real clean
binary passed to the original dirty harness checkout, with both origins recorded
accurately.

The [historical validation](historical-validation.json) applies the stricter
validator to all 14 previously completed scaling cells and the original small
reproduction. The two declared budget skips remain skips. Original measurements
and archives are preserved; this follow-up supersedes their harness implementation.
The parent [artifact checksums](../artifact-sha256.txt) cover both bundles.
Authoritative Linux RSS and live FRR acceptance remain open.
