# Scenario, memory, and scaling measurements

Repeatable measurement tooling and its acceptance gates are complete. Native results and
clean source reproduction are recorded in [native evidence](../evidence/bench/benchmark-validation.md).
[Linux acceptance](../evidence/release/linux/README.md) adds authoritative peak and boundary RSS
and a clean reproduction for the 16-router small workload. Scenario processing measures converged snapshots; these times
are not network convergence, detection delays, or outage durations.

## Run the frozen workloads

Use an unsanitized Release build with Python 3.9+, CMake and Ninja:

```sh
cmake --preset host-release
cmake --build --preset host-release
ctest --test-dir build/host-release --output-on-failure
build/host-release/routeproof bench --profile benchmarks/profiles/sparse-small.json --out results/bench-small
build/host-release/routeproof bench --profile benchmarks/profiles/scaling.json --out results/bench-scaling
```

`bench` launches the checked-in Python harness using argument vectors. The source
checkout and configured Python interpreter must remain available. The same harness
can be called directly with `python3 tools/bench/run.py --binary PATH --profile
FILE --out DIR`. Profiles are strict JSON; unknown fields, duplicate keys, bools in
integer fields, unsupported shapes, and unsafe cell names are rejected. Existing
output directories are refused. `--allow-debug` is reserved for CTest smoke runs.
The binary's adjacent `CMakeCache.txt` identifies its source checkout; published
runs require that cache and checkout. Binary source revision, dirty state and
hashes are recorded separately from the harness checkout, including when
`--binary` selects an executable built elsewhere. Missing binary source metadata
is explicitly unavailable in smoke runs.

Exit 0 means every cell completed its declared sample policy and identical result
bytes were observed. Exit 3 means the sweep is partial (including budget skips,
timeouts, resource limits, or interruption). Expected reachability failures
(`simulate` exit 1) are completed benchmark work. Invalid profiles/build selection
exit 2. Partial cells are excluded from performance summaries; their samples and
reasons remain available. Release acceptance never converts a skipped workload
into a successful measurement.
Checkpoint summaries include declared, attempted and completed cell counts. A
sweep is complete only after every declared cell completes, including when an
interruption occurs between cells.

## Boundaries and memory

An instrumented `bench-sample FILE --out DIR` runs the exact `simulate` pipeline and
also writes `sample.json`. All runs retain full canonical JSON history and only
current/candidate C++ routing tables. Instrumentation leaves `result.json`
byte-identical to ordinary `simulate`; every warmup and repetition checks this.

- **Core processing:** C++ `steady_clock` segments covering baseline initialization,
  physical event mutation, full routing recomputation and invariants, cached
  destination analysis, all assertions, and witness validation. Parsing, canonical
  JSON construction/hashing/publication, cache cleanup, final serialization and
  file writes are outside these segments. Per-event samples use the same boundary;
  the baseline is a separate sample. Core totals sum completed snapshots only.
- **Simulation:** the existing `simulate` boundary includes replay/checks, all
  canonical JSON work and serialization; it excludes input loading and file writes.
- **Complete CLI:** Python `perf_counter_ns` from process launch through a blocking
  `wait4` return, covering loading, validation, simulation, serialization and output
  writes. A waiter thread records completion without a polling interval added to
  each duration. Scheduling/launch overhead remains included. Outputs use ordinary
  buffered writes without `fsync`, on the filesystem named in the run manifests.
- **Peak RSS:** `wait4`'s per-process high-water RSS, normalized to bytes (Linux KiB;
  macOS bytes). The reported peak distribution comes from ordinary CLI processes.
  Instrumented high-water samples are also preserved separately.
- **Steady RSS:** after parsing/loading, and after routing/checks for each snapshot.
  The latter retains prior JSON history, the current candidate JSON/assertion
  buffers, routing tables and destination cache before publication. Linux uses
  `/proc/self/status`; macOS uses `mach_task_basic_info`. These are boundary samples,
  not a claim about a long-lived service reaching equilibrium. Missing readings
  are `null`. macOS RSS is provisional; authoritative memory requires Linux.

RSS includes parser allocations, shared next-hop storage, scratch space, allocator
arenas, JSON, and runtime overhead. No table-allocation bytes or bytes-per-route
claim is made. Logical next-hop references count every prefix reference even when
prefixes at one origin share an immutable set. Timing runs are single-threaded
inside the engine; the external harness uses one waiter thread. Clocks, CPU/RAM,
OS/kernel, compiler flags, dependencies and power settings are in `manifest.json`.
Frequency/boost and background load are uncontrolled on the published native host.

Instrumentation adds clock reads per assertion, counters, and RSS samples. Each
repetition runs an instrumented process and a separate ordinary CLI process in
that fixed order. Their simulation-time distributions and median ratio are saved
as diagnostics; host variation prevents treating that ratio as exact probe cost.
No subtraction is applied to raw times. RSS guard polling runs every 100 ms and may
briefly miss a spike; the final high-water check still marks a memory-limit failure.
The final recorded process duration is also checked against the timeout, even if
the process exited successfully before the monitor observed the deadline.
On macOS the guard uses `ps`; on Linux it reads procfs. This overhead and waiter
thread scheduling are included in CLI durations.

## Workload dimensions and budgets

The frozen `routeproof_workload_v1` generator uses integer arithmetic. Sparse graph
selection uses xorshift32 with shifts `(13,17,5)`, uint32 truncation after left
shifts, nonzero seed, and modulo endpoint selection. Its algorithm and seed are
saved, alongside raw and parser-normalized scenarios and SHA-256 digests. Other
shapes do not use random draws. Each topology has a gateway leaf with a single
attachment link so a fixed-length trace includes a real partition at every size.
The ring/grid/sparse/ladder portion occupies the remaining routers.

The sweep covers chain sizes 16/64/256/1024, ring, grid, diamond ladder and sparse
connected random graphs. Separate cells vary prefixes per origin, selected versus
all origins, ladder width 2/4, sparse density, selected versus every destination
from every declared router, and trace length. Down sources remain assertions and
fail explicitly. Topology scaling keeps the eight-event trace fixed. Each cycle
contains internal link down/up, gateway partition/recovery, origin router down/up,
and two explicit no-ops: six effective events and two no-ops. The long-trace cell
uses four cycles. Timestamps annotate order without sleeps. No-op timings remain
visible and no-ops are excluded from effective-event counters.

Profiles cap per-process wall time and memory, estimated retained routes/output,
and estimated SPF work. Estimates use `R*P*(events+1)` route rows, maximum physical
degree as a next-hop bound, conservative JSON/RSS allowances and
`R*(R+2L)*(events+1)` work units. These are screening estimates, not measured
allocation or time predictions. Default engine/parser/output limits also apply.
The harness kills its owned child process group on timeout or memory guard failure
and saves commands, stderr and process status. Signal/OOM ambiguity is labeled
`oom_or_signal`; it is not asserted to be a kernel OOM without additional evidence.
SIGINT/SIGTERM interruptions checkpoint the active cell and stop the sweep.

Every attempted cell has R, physical L/directed arcs, P, events, assertions,
destination coverage, config/seed, and screening estimates. Completed cells also
report per-snapshot actual route/next-hop counts, maximum observed ECMP width,
available routers, analyses, failed assertions and retained history. Larger probes
are workload attempts, not promised capacity. The matrix is intentionally bounded.

## Samples and reproduction

Each completed cell has one fixed fresh-process warmup per mode and five measured
fresh processes per mode. Published values are median, minimum, maximum, and median
absolute deviation. Five repetitions do not support p99 claims. Raw per-process
commands, exit codes, output hashes, timings, RSS and all per-snapshot samples stay
in `summary.json`, `scenario-timings.csv`, `event-timings.csv`, `memory.csv`, and the
individual process/run/sample manifests. One canonical result per cell is retained;
repeated copies are deleted after recording their hashes. Warmups are excluded
from CSV statistics but kept in the JSON and raw manifests. Raw timings, including
failed probes, are never replaced by an aggregate.

Reproduce the small profile from a fresh clean checkout/build, then compare:

```sh
python3 tools/bench/compare_runs.py results/bench-small /path/to/clean/results/bench-small --cell sparse-small-16
```

The validator requires an unsanitized Release build, clean reproduction source
and harness checkouts, a distinct binary path, equal source-input/generator/workload hashes, complete
raw sample coverage and identical canonical bytes. It checks reported aggregates
against raw samples, including simulation distributions and the instrumentation
ratio. It reconciles per-snapshot and aggregate counters with the retained
canonical result, and simulation timings with the raw run/sample manifests.
Completed processes must respect the recorded time/memory budgets. Timing equality
is not required and no regression threshold is imposed. Both binary and harness
source-input manifests cover code, tests, profiles, schemas and build
configuration; raw scenario hashes cover actual measurement inputs. Dependency
commits are recorded separately. The selected evidence includes a source archive
for the uncommitted implementation and the exact clean-build/reproduction commands.
Historical bundles predating separate harness provenance remain comparable to
each other; they cannot be mixed with the new provenance format.

Full generated runs live under ignored `results/`. The published bundle retains
small raw evidence and a source archive with checksums; larger canonical results
can be regenerated from the archived normalized scenarios. No routing optimization
was introduced: this phase measures the reference implementation first.
