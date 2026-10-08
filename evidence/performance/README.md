# First performance pass

Measured on 2026-10-08 (America/Toronto). Simulation medians fell by **21–40%**
across all 14 completed frozen workloads. The 256-router chain's core median
fell from **17.396 ms to 6.493 ms** (63%); complete CLI median fell from
**57.964 ms to 38.865 ms** (33%). Every completed workload's canonical result
bytes, snapshot/assertion counters and normalized input match the baseline.

## Changes and profiling

- SPF reuses Dijkstra heap storage, creates direct first hops only at the source,
  and copies an already sorted/unique first-hop set when a DAG successor is empty.
  The per-source scratch reference budget remains unchanged. Source/origin sharing
  caches also reuse their storage.
- Replay reuses tables when an event leaves physical state unchanged. It still
  invokes the snapshot boundary and observer and checks every assertion, retains
  a distinct event/snapshot and charges the existing analysis/output budgets.
- Output builds snapshot JSON directly, moves route arrays into the retained
  snapshot, formats each prefix once per snapshot and sorts lightweight route
  references instead of sorting JSON objects with repeated string copies.
  The public baseline JSON interface and canonical ordering remain unchanged.

The [phase driver](phases.cpp) runs one warmup and 20 in-process iterations on
already parsed input. It helped identify SPF allocation and serialization costs;
these exploratory averages are separate from the published fresh-process medians.
On the 256-router chain it measured SPF at 1.752 / 0.827 ms before/after, table
validation near 0.003 ms in both builds, and complete simulation at
47.884 / 28.011 ms. The [chain logs](chain-256-before.txt) and
[optimized chain logs](chain-256-after.txt), plus the
[prefix-density logs](ring-prefix-density-2-before.txt) and
[optimized prefix-density logs](ring-prefix-density-2-after.txt), preserve them.
Validation was retained because it was a small fraction of runtime.

## Frozen workload comparison

Each sweep uses the unchanged `benchmarks/profiles/scaling.json`: one warmup
and five measured fresh processes per mode per completed cell. This is 140
measured processes and 28 warmup processes per sweep. Core values use instrumented
processes; simulation and CLI values below use ordinary processes. Core excludes
JSON, parsing and file writes; simulation includes canonical output; CLI includes
process launch, loading and writes. The [comparison JSON](comparison.json) retains
median, range and median absolute deviation, plus result hashes and dimensions.

| Workload | Core ms before / after | Simulation ms before / after | Complete CLI ms before / after |
| --- | ---: | ---: | ---: |
| chain-16 | 0.134 / 0.092 | 2.251 / 1.739 | 5.543 / 5.525 |
| chain-64 | 1.153 / 0.542 | 8.879 / 6.297 | 13.586 / 11.508 |
| chain-256 | 17.396 / 6.493 | 47.714 / 28.499 | 57.964 / 38.865 |
| ring-16 | 0.143 / 0.093 | 2.353 / 1.806 | 6.147 / 5.270 |
| grid-16 | 0.224 / 0.148 | 2.786 / 2.090 | 6.399 / 5.929 |
| diamond-width-2 | 0.188 / 0.121 | 2.662 / 1.936 | 6.272 / 5.861 |
| diamond-width-4 | 0.219 / 0.134 | 2.623 / 1.975 | 6.253 / 5.863 |
| sparse-16 | 0.232 / 0.151 | 2.511 / 1.889 | 6.120 / 5.675 |
| sparse-denser-16 | 0.306 / 0.193 | 3.219 / 2.360 | 7.049 / 6.556 |
| ring-prefix-density-1 | 0.259 / 0.195 | 17.420 / 12.268 | 23.673 / 18.722 |
| ring-prefix-density-2 | 0.332 / 0.249 | 34.469 / 24.224 | 43.936 / 33.601 |
| ring-all-assertions | 0.578 / 0.516 | 25.356 / 19.925 | 34.561 / 29.496 |
| ring-long-trace | 0.444 / 0.267 | 8.468 / 6.195 | 13.492 / 11.127 |
| ring-64 | 3.254 / 2.064 | 306.202 / 200.015 | 359.048 / 254.629 |

The 1,024-router chain and 256-router dense-prefix ring remain **budget-skipped**
in both runs. Both sweeps exit 3 and have partial status: these two probes are not
measurements or capacity ceilings. The comparator preserves their exact reasons.

Peak RSS medians fell in 13 workloads, including 103.09 / 78.81 MiB for `ring-64`
and 17.55 / 14.44 MiB for `chain-256`. `ring-all-assertions` increased from
15.12 to 15.98 MiB (about 6%); this pass does not claim lower memory for every
workload. RSS is provisional macOS evidence, including full JSON history and
allocator/runtime overhead. Existing Linux receipts concern their historical
source snapshots; no new live Linux/FRR run is claimed here.

Host: Apple M4, 10 CPU cores, 16 GB RAM, macOS 27.0.1 arm64; Apple Clang 21.0.0,
Release `-O3 -DNDEBUG`, no sanitizers in measurements. Runs were sequential:
baseline sweep first, optimized sweep afterward, with no builds or tests during
either sweep. CPU frequency/boost and background load are uncontrolled. These are
descriptive five-sample comparisons, not tail latency, calibrated probe overhead
or a universal speedup guarantee. Tiny CLI workloads have substantial launch cost.

## Correctness and source receipts

All 11 CTest groups pass with native Release, GCC 12.5.0 Debug, upstream Clang
18.1.8 Debug and native ASan/UBSan. These include independent generated
routing/replay oracles, malformed forwarding graphs, resource boundaries, the
checked demo, offline FRR and benchmark contracts. The routing integration check
also covers an exact merged-ECMP scratch limit, one-reference exhaustion, reuse
after failure, changing sources and unavailable-source reset.

See [validation metadata](validation.json), [Release test log](release-tests.txt),
[GCC tests](gcc-tests.txt), [Clang tests](clang-tests.txt) and
[sanitizer tests](sanitizer-tests.txt). The corresponding build logs are included.

Baseline revision: `670e0dbd5e560685b1aa089e8776430480c9e395`, initially clean.
The optimized build uses uncommitted changes on that revision. The
[baseline manifest](before-manifest.json) and [optimized manifest](after-manifest.json)
record separate source hashes, binary hashes, dependency revisions, compiler flags
and host context. [Before source](before-source.tar.gz) and
[after source](after-source.tar.gz) freeze code, tests, fixtures and build inputs;
they omit Git metadata and historical evidence. Their measured source files are
verified against the manifest hashes before archiving. Documentation does not
participate in the benchmark source-input hash.

[Before raw receipts](before-raw.tar.gz) and [after raw receipts](after-raw.tar.gz)
include both complete and skipped cells, all process/run/sample manifests,
normalized scenarios, raw CSVs and retained canonical results. To revalidate:

```sh
mkdir -p results/performance-receipts
tar -xzf evidence/performance/before-raw.tar.gz -C results/performance-receipts
tar -xzf evidence/performance/after-raw.tar.gz -C results/performance-receipts
python3 evidence/performance/compare.py \
  results/performance-receipts/performance-before-20261008 \
  results/performance-receipts/performance-after-20261008 \
  --out results/performance-receipts/comparison.json
```

The [comparator](compare.py) validates each run with the existing raw-receipt
validator, then requires equal workload policies, host/build configuration,
dependencies, measurement harness, inputs, counters and canonical bytes. It
intentionally permits production-source changes and imposes no timing threshold;
it is distinct from same-source clean reproduction validation. Fresh builds from
either source archive use the normal CMake presets and pinned dependencies.

Original commands:

```sh
cmake --build --preset host-release
ctest --test-dir build/host-release --output-on-failure -j 4
python3 tools/bench/run.py --binary build/host-release/routeproof \
  --profile benchmarks/profiles/scaling.json --out results/performance-before-20261008
# Apply the source optimization, rebuild and run Release CTest.
python3 tools/bench/run.py --binary build/host-release/routeproof \
  --profile benchmarks/profiles/scaling.json --out results/performance-after-20261008
python3 evidence/performance/compare.py \
  results/performance-before-20261008 results/performance-after-20261008 \
  --out evidence/performance/comparison.json
cmake --build --preset gcc-debug --parallel 4
ctest --test-dir build/gcc-debug --output-on-failure -j 4
cmake --build --preset clang-debug --parallel 4
ctest --test-dir build/clang-debug --output-on-failure -j 4
cmake --build --preset host-sanitizers --parallel 4
ctest --test-dir build/host-sanitizers --output-on-failure -j 4
```

[SHA256SUMS](SHA256SUMS) covers the archived artifacts and comparison/validation
receipts. Historical acceptance and benchmark evidence is preserved separately.
