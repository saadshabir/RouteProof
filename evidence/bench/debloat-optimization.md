# Debloat and output optimization, 2026-10-10

The changes preserve the v0.1 CLI, canonical result bytes, routing semantics and
resource limits. Existing working-tree documentation and historical evidence
were retained. The [implementation plan](../../docs/debloat-optimization-plan.md)
gives the scope and ordering.

## Changes

- Removed the unused Catch2 declaration and duplicate Python discovery. Catch2
  was never fetched, so this makes no dependency-download savings claim.
- Shortened the README to purpose, quick start, commands and navigation. Model,
  FRR, measurement and acceptance details remain in their dedicated documents.
- The launcher skips configuration when its configuration fingerprint matches.
  It still builds before every dispatch. Presets, CMake configuration, cached
  source/generator, tool identities, toolchain files and environment changes
  invalidate the fingerprint. Compiler/toolchain changes use a fresh
  configuration; initial flag changes refresh only their affected cache entries.
  External preset includes fall back to automatic configuration.
  Environment values are hashed rather than saved in plaintext.
- Simulation returns a small summary of status, canonical digest and published
  snapshot/event counts. Both manifest writers use it instead of parsing the
  canonical result. Incomplete traces describe only published coverage.
- Snapshot hashing records the serialized projection's size. Its byte charge
  combines that size with the small identity object's serialized size, preserving
  the prior exact conservative charge and avoiding a second route serialization.
  The temporary serialization buffer is released before identity publication.

Prefix formatting/sorting was deferred: the instrumented baseline measured less
than 3 ms on `ring-64`, versus about 50 ms for route JSON construction, 45 ms for
digest serialization and 71 ms for SHA-256. Run-manifest parsing took about 55 ms;
instrumented sample-manifest parsing added about 46 ms. These component timings
include instrumentation overhead and are exploratory, with nested boundaries.
No routing algorithm, Python oracle, FRR procedure, output schema or JSON library
changed. Further caches, streaming output and SPF changes need separate evidence.

## Measurement receipts

Raw runs, source snapshots, provenance, commands, validation logs and separate
maintenance/launcher/metadata/output patches are retained under
`results/debloat-20261010/`. Compact published samples and hashes are in
[debloat-optimization.json](debloat-optimization.json).

Measurements use Apple Clang Release on the same native macOS host. Each frozen
profile uses one warmup and five fresh processes per mode. Core, simulation and
complete executable time stay separate. Launcher timings include build startup;
CLI timings invoke the executable directly. Native RSS is provisional; this pass
makes no Linux memory improvement claim. Host boost and background load are
uncontrolled, so results describe this host and workload.

The full small/scaling bundles preserve all 15 completed cells and both
budget-skipped probes. Their raw samples and aggregates are validated with
`tools/bench/compare_runs.py`'s `validate_run`; input hashes, canonical bytes and
counters agree across revisions. Unpaired sweeps showed substantial host
variation. The final before/after timing check alternates execution order over
all completed cells with the same one-warmup/five-repetition policy.

Repeated launcher startup (`--version`, five measured runs) decreased from
1451.7 ms to 60.0 ms (95.9%). The first candidate invocation
is a retained warmup/configuration run and is excluded from the median.

Final paired complete-executable medians (milliseconds):

| Workload | Baseline | Metadata only | Final | Reduction |
| --- | ---: | ---: | ---: | ---: |
| sparse-small-16 | 5.307 | 4.925 | 4.654 | 12.3% |
| chain-256 | 37.698 | 33.084 | 31.377 | 16.8% |
| ring-64 | 255.601 | 204.816 | 187.681 | 26.6% |
| ring-all-assertions | 29.249 | 24.387 | 23.059 | 21.2% |
| ring-long-trace | 10.290 | 9.053 | 8.458 | 17.8% |

All 15 completed cells had lower paired CLI medians. No repeatable regression
appeared in this check. The receipt retains every warmup/sample and median, range
and MAD; the five priority workloads also improved in an earlier independent
paired pass. The full frozen profiles remain descriptive measurements with
uncontrolled host conditions. No p99, general capacity or network-convergence
claim follows from these samples.

## Validation and reproduction

- All 12 Release CTest groups passed. GCC, upstream Clang and ASan/UBSan full
  suites also passed; the final test-only warning fix was rebuilt and its replay
  checks rerun under every compiler/sanitizer configuration.
- Focused coverage checks launcher invalidation/dispatch/failure handling and
  summary agreement for pass, fail, empty incomplete and partially published
  traces, including a published no-op followed by a rejected candidate.
- Real launcher checks in the isolated source validate repeated launch without
  configuration, source rebuilding, preset changes, and initial CXXFLAGS changes
  and restoration. Build logs remain on stderr and CLI output stays intact.
- Before/after budget probes agree byte for byte just below, at and above
  publication boundaries for the diamond and `ring-64`, including incomplete
  diagnostics. Frozen diamond boundaries are now regression checks.
- Every final completed benchmark cell validates its raw bundle, workload hashes,
  canonical bytes and counters. Both existing budget-skipped rows are unchanged.
- A fresh clean final-source Release build reproduced the small workload;
  `tools/bench/compare_runs.py` returned `pass`. Routing/FRR behavior did not
  change, so fresh live FRR matrices were not required by the plan.

The source-input manifests and binary digests identify the measured source and
executables; historical benchmark results remain historical. The clean
reproduction is a separate committed snapshot outside the working checkout,
with identical final source-input hashes and the pinned dependency commits.
`compare_runs.py` validates final-source reproduction, rather than comparing
different revisions for performance.

## Artifact retention

The inventory records size, provenance paths and reproduction commands under
`results/debloat-20261010/local-inventory.json`. All existing build caches and raw
measurement bundles were retained. Duplicate evidence was inventoried with its
references: seven exact duplicate groups represent only 249,722 potential bytes.
Receipts and referenced history remain in Git.

Only `results/pycache` was removed: 48 regenerable Python bytecode files,
644,685 logical bytes (about 728 KiB allocated). No tracked evidence files or
unique measurements were deleted. The removal decision and regeneration command
are in `results/debloat-20261010/removed-artifacts.json`. The baseline source copy,
profiling build and new measurement bundles consume temporary local space; their
retention is deliberate for this comparison.

## Review follow-up

Flag-only launcher reconfiguration now preserves existing CMake options, compiler
selection and configuration-specific flags. A real CMake regression builds and
runs a small executable while adding, changing and removing `CXXFLAGS` and
`LDFLAGS`; it checks that `BUILD_TESTING=OFF`, the selected compiler and custom
Release flags survive each change.

The measurements and `sources.final` hashes above identify the optimization
snapshot before this follow-up. Recorded timing samples and source hashes were
retained without relabeling them as measurements of the revised launcher.
