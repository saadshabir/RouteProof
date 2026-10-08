# Phase 5 benchmark evidence

Historical native validation date: 2026-10-07 (America/Toronto). Native
measurement/reproduction evidence is delivered. The Linux gates were open then;
[Linux acceptance](../release/linux/README.md) now records completed live FRR
reproduction and authoritative small-workload RSS. No optimization or network
convergence claim is made.

## Workloads and measured results

The [scaling report](scaling-report.md) contains 16 declared cells: **14 complete,
2 budget-skipped**. Each completed cell has one fresh-process warmup and five
measured fresh processes per mode (instrumented core and ordinary complete CLI):
140 measured processes and 28 warmup processes for the scaling sweep. Five shapes,
16/64/256-router executed cells, prefix density, ECMP width, assertion coverage,
sparse density and trace length are represented. The observed ladder widths are
2 and 4. The 1,024-router chain is screened out by the declared SPF work limit;
the 256-router/512-prefix ring is screened out by retained-route/output/RSS
estimates. Their frozen normalized inputs and exact reasons remain in the bundle.
These are budget decisions, not measured capacity ceilings or OOM results.

The separate [small profile report](small/report.md) publishes a seeded sparse
connected graph with 16 routers, 30 physical links/60 directed arcs, 2 prefixes,
8 events (6 effective/2 no-ops), 1 assertion and 1 analyzed destination. Baseline
materialization is 32 route entries and 38 logical next-hop references. Nine
snapshots include a partition, origin failure, and recovery. Its five-run core
median is **0.215665 ms**, range **0.204167–0.222957 ms**; complete CLI median is
**5.824833 ms**, range **5.741917–5.989708 ms**. Ordinary CLI peak RSS median is
**4,112,384 bytes**, provisional macOS evidence. All figures come from the raw
[small summary](small/summary.json), [timing CSV](small/scenario-timings.csv),
[memory CSV](small/memory.csv), and individual process/sample manifests.

The host is an Apple M4 with 10 CPU cores and 16 GB RAM, macOS 27.0.1 arm64.
Release builds use Apple Clang 21.0.0, C++20, `-O3 -DNDEBUG` and the repository's
warning flags; sanitizers are excluded from timings. CMake 4.4.4, Ninja 1.13.2,
and configured Python 3.13.16 are recorded in each manifest. CPU frequency/boost
and background load are uncontrolled. RSS includes full canonical JSON history,
not just tables. Section boundaries, memory semantics and instrumentation
limitations are specified in [benchmarks.md](../../docs/benchmarks.md).

The scaling run's diagnostic instrumented/ordinary simulation medians and their
ratios are in [scaling-summary.json](scaling-summary.json). They include host
variation and are not a calibrated probe-cost subtraction. No tail percentile,
throughput, bytes-per-route, authoritative Linux RSS or maximum-capacity claim is
published.

## Clean source reproduction

[Reproduction comparison](reproduction-comparison.json) passes using a distinct
fresh Release build in `/private/tmp/routeproof-phase5-clean`. The source archive
was unpacked into an isolated directory and committed locally; the recorded Git
status was clean. This is a clean frozen source snapshot of the uncommitted
implementation, not a claim that the original working tree was clean. The
[source-input manifest](source-inputs.json) covers code, profiles, tests, schemas,
and build configuration; its digest is
`7907c181f223d25d90c469771fd200c11804b13a41fe635b5acdd89e79b47741`.

Both runs use exactly the same pinned, verified-clean cached dependency sources:
yaml-cpp `56e3bb550c91fd7005566f19c079cb7a503223cf`, nlohmann/json
`55f93686c01528224f448c19128836e7df245f72`, and PicoSHA2
`161cb3fc4170fa7a3eca9e582cebd27cc4d1fe29`. Build outputs are freshly compiled;
dependency downloads were reused explicitly rather than reacquired. Source
revision, binary hash, compiler/cache flags, dependencies, CPU/RAM, kernel and
power settings are in [the original manifest](small/manifest.json) and
[the reproduction manifest](reproduction/manifest.json).

The reproduced core median is 0.227873 ms and complete CLI median is 5.809667 ms.
Both runs have identical canonical result-file SHA-256
`ff773b89a3298cc37f4d036a990abe6ae924c42b90eee78f66f81d9e09f35f2a`.
All warmups, instrumented runs and ordinary runs match these bytes. Raw
[reproduction samples](reproduction/summary.json) remain available; timing equality
or a performance threshold is not required.

## Verification and artifacts

The archived measurement source passes all **10 CTest groups**, including the independent
routing/replay oracles, offline FRR harness, and seven benchmark contract checks.
[Clean Release log](clean-release-tests.txt) records the complete measured-source run.
GCC 12.5.0 and upstream Clang 18.1.8 builds and benchmark checks pass; full suites
also passed during implementation. [GCC benchmark log](gcc-debug-tests.txt) and
[Clang benchmark log](clang-debug-tests.txt) record the follow-up checks.
[ASan/UBSan log](host-sanitizers-tests.txt) records all 10 groups passing separately
from measurements. The benchmark contract checks canonical byte identity,
actual route/next-hop/failure counters, frozen shapes/PRNG, strict profiles,
insufficient/altered evidence rejection, fresh repetitions, partial budget skips,
timeouts, memory guard failures, interrupted worker cleanup, and paths with spaces.
No live FRR result is inferred from the offline checks.

[Commands](commands.txt) record acquisition/reproduction/build/validation steps.
[Artifact checksums](artifact-sha256.txt) cover the selected bundle.
The [frozen source archive](source-snapshot.tar.gz) permits rebuilding these
uncommitted sources. The [complete compressed scaling bundle](scaling-raw.tar.gz)
contains all generated/normalized inputs, commands, raw process/run/sample
manifests, logs and retained canonical results; extract it with
`tar -xzf evidence/bench/scaling-raw.tar.gz -C results`.
The same scaling aggregates/CSVs are directly available as
[summary JSON](scaling-summary.json), [scenario CSV](scaling-scenario-timings.csv),
[event CSV](scaling-event-timings.csv), and [memory CSV](scaling-memory.csv).
Repeated canonical copies were deleted after hashing; one result per completed
cell is retained. The source archive predates this evidence index and contains the
exact measured code. Documentation added afterward does not change that code hash.

This historical bundle contains native measurements. `bench` implements both
Linux and macOS RSS; authoritative Linux samples and their clean reproduction
are now available in [the completed release receipts](../release/linux/README.md).

## Review fixes

[Review-fix evidence](review-fixes/README.md) records the subsequent corrections
to sweep completion, external-binary source provenance, counter/timing validation
and final timeout enforcement. The original source archive, measurements and
reproduction above are preserved as historical evidence. The stricter validator
rechecks all 14 completed scaling cells and the original small reproduction;
fresh source and clean reproduction artifacts cover the corrected harness.

[Follow-up verification](review-fixes/validation.md) records the shipping harness
fixes, expanded checks and current source hash separately from the original
measurement snapshot. All original raw measurements pass the strengthened verifier.
