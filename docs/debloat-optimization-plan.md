# RouteProof debloat and optimization plan

Reduce maintenance overhead, repeated startup work, and result-processing cost while preserving the v0.1 CLI, canonical bytes, routing semantics, and resource limits. Implement in the order below; each change should stand on its own.

Planning audit: 2026-10-10, HEAD `2e713d2`, with existing documentation/evidence edits. No implementation changes or new performance measurements were made for this plan.

**Execution completed: 2026-10-10.** Baseline and frozen profiles were captured;
maintenance cleanup, launcher invalidation, typed simulation metadata and one
measured serialization reduction were implemented. [Results and verification](../evidence/bench/debloat-optimization.md)
record canonical-byte agreement, compiler/sanitizer gates, clean reproduction,
timing distributions and artifact retention. Prefix caches and deeper changes
were deferred because the measured benefit did not justify their complexity.
The audit findings below describe the starting checkout.

**What the current checkout shows**

| Finding | Implication |
| --- | --- |
| Local `build/` occupies about 911 MB; `results/` about 287 MB. Both are ignored. | Local artifact retention is the main disk-space opportunity. These sizes are not clone size. |
| Present tracked evidence totals about 2.3 MB across 435 files. | Improve navigation before deleting evidence; disk savings would be modest. |
| SPF reuses scratch buffers, prefixes share immutable next-hop sets, and no-op replay already reuses tables. | Preserve these optimizations; they are implemented, not future tasks. |
| `run_manifest()` reparses the entire result; instrumented runs parse it again in `sample_manifest()`. | Carry a small typed summary out of simulation and eliminate redundant JSON parsing. |
| Every snapshot formats prefixes and sorts route references; simulation repeatedly serializes JSON for hashes, budgets, and final output. | Profile output construction, hashing, and retention before changing routing algorithms. |
| The launcher configures CMake on every invocation. Catch2 is declared but never made available or used. | Optimize repeated launcher startup; remove the unused declaration as housekeeping, without claiming download savings. |

The [benchmark documentation](benchmarks.md) records an earlier optimization pass. Its local comparison at `results/performance-support-20261008/comparison.json` reports a `ring-64` median of roughly 2.06 ms core, 200 ms simulation, and 255 ms complete CLI after that pass. These are historical measurements from different source, not a current baseline. They suggest investigating output work; the timing gap alone does not identify its exact cause.

**1. Establish a baseline**

- Record implementation, harness, dependency, compiler, and binary hashes before editing. Preserve the existing working-tree changes and use separate output directories for each run.
- Build Release and run the existing CTest suite. Measure the frozen small and scaling profiles with their existing warmup/repetition policy. Prioritize `sparse-small-16`, `chain-256`, `ring-64`, `ring-all-assertions`, and `ring-long-trace` when investigating individual changes.
- Profile loading, route computation, JSON construction/sorting, hashing, manifest creation, and writes. Measure launcher elapsed time separately: the current CLI benchmark starts the executable and excludes launcher builds.
- Keep core, simulation, complete CLI, and Linux RSS boundaries distinct. Preserve budget-skipped rows; raising a limit is not an optimization.

**2. Remove maintenance clutter**

- Remove the unused Catch2 declaration in [Dependencies.cmake](../cmake/Dependencies.cmake) and the duplicate Python discovery in [CMakeLists.txt](../CMakeLists.txt).
- Reduce [README.md](../README.md) to purpose, quick start, essential commands, and navigation. Keep model contracts in [model.md](model.md), FRR procedures in [validation.md](validation.md), measurement rules in [benchmarks.md](benchmarks.md), and acceptance status in [acceptance.md](acceptance.md). Replace repeated detail with links.
- Keep evidence receipts, reproducible inputs, regression fixtures, and source/binary provenance. Inventory duplicate generated bundles and their references before proposing removals. Historical measurement files remain historical.
- For local disk cleanup, list build/result directories with size, provenance, and reproduction commands. Preserve unique raw measurements and active build caches; remove only identified disposable directories. Avoid adding a cleanup framework for a one-time inventory.

Completion: less duplicated documentation and configuration, all affected links resolve, clean configuration still works, and any removed artifacts have an explicit retention decision.

**3. Reduce repeated startup work**

Target: [tools/run.py](../tools/run.py).

- Configure on first use or when configuration inputs change; otherwise run the incremental build directly. Always build before dispatch so source edits cannot leave the launcher running an old binary.
- Define invalidation for presets, toolchain/compiler selection, configuration environment, and cache/source-directory mismatch. Retain CMake/Ninja's dependency regeneration. If safe invalidation adds more complexity than measured benefit, keep automatic configuration and document direct-binary use for repeated runs.
- Preserve clean-checkout bootstrap, stderr build logs, argument forwarding, and exit codes.

Completion: repeated launcher use is measurably faster; missing builds, source edits, and configuration changes still produce the correct executable.

**4. Reduce result-processing overhead**

Targets: [simulation.hpp](../include/routeproof/output/simulation.hpp), [simulation.cpp](../src/output/simulation.cpp), [measurement.cpp](../src/bench/measurement.cpp), and [baseline.cpp](../src/output/baseline.cpp).

- First, return simulation status, canonical digest, completed snapshot count, and applied/no-op counts as a typed summary alongside canonical JSON. Use it in both manifest writers instead of parsing the full result. Derive counts from published snapshots so incomplete runs remain accurate.
- If profiling confirms sorting/formatting cost, compute immutable prefix text and lexical ordering once per simulation and reuse them. Preserve lexical `(router, prefix)` ordering, including the difference between numeric prefix indices and prefix text.
- Then address measured redundant serialization or temporary allocations with small local changes. Preserve exact digest projections, conservative output charging, atomic snapshot publication, and the diagnostic result on budget exhaustion. Measure added caches against peak RSS.
- Keep `explain` validation separate: it reads untrusted files and must still verify digests, references, statuses, and bounds.

Completion: canonical `result.json` is byte-identical across baseline/candidate runs, metadata agrees, and targeted CLI time or Linux peak RSS improves beyond observed run variation without a repeatable regression elsewhere.

**5. Make deeper changes only when profiles justify them**

- Consider sorted-set merging in [shortest_paths.cpp](../src/spf/shortest_paths.cpp) only if repeated ECMP insertion is a remaining hotspot. Preserve parallel-interface identity, deterministic ordering, and pre-allocation resource checks.
- Share Python helpers only where behavior is actually identical. FRR and benchmark manifests cover different files; process runners have different timeout, signal, cleanup, and RSS requirements. Keep those contracts explicit.
- Keep independent Python routing/replay oracles independent. Preserve parser checks, all-branch analysis, cycle detection, witness validation, and runtime forwarding invariants.
- Defer incremental SPF, threading, replacement JSON libraries, custom streaming output, schema changes, and new dependency frameworks to separate proposals backed by measurements.

**Verification and delivery**

Use affected existing checks while iterating. Add focused coverage for changed behavior such as launcher invalidation or incomplete-run metadata; avoid tests that merely mirror a refactor. Before delivery, run the full Release suite. Run ASan/UBSan and compiler gates for C++ changes; rerun the two fresh Linux FRR matrices if routing or FRR behavior changes.

For before/after comparisons, validate each benchmark bundle and compare identical workload hashes, canonical bytes, counters, time distributions, and RSS on the same host/toolchain. Use `tools/bench/compare_runs.py` for a separate clean reproduction of the final source: it intentionally rejects differing source hashes and is not a cross-revision performance comparator. Use Linux measurements for memory claims; native macOS RSS remains provisional.

Deliver separate changes for maintenance cleanup, launcher startup, simulation metadata, and any justified output optimization. Report removed bytes/files and measured improvements separately. Stop when the remaining work adds complexity without a repeatable benefit.
