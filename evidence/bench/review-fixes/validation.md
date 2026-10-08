# Benchmark harness follow-up verification

The shipping source includes three harness/test fixes added after the original
measurement snapshot: binary provenance now follows its CMake source checkout
and records harness provenance separately; reaped workers still undergo final
timeout validation; partial sweeps account for every declared cell. The verifier
also reconciles workload dimensions, per-snapshot counters, simulation timings,
budgets and instrumentation aggregates against retained raw/canonical artifacts.

The routing engine and C++ instrumentation are unchanged. The previously recorded
14 complete scaling cells, both small runs and all original artifact checksums
pass the strengthened verifier. The original source archive and manifests retain
their measured source hash; the current shipping source hash is recorded separately
in [source-inputs.json](source-inputs.json). No old timing sample was relabeled with
a new source hash.

`ctest --test-dir build/host-release -R bench --output-on-failure` passes the expanded
benchmark contract checks; [raw test output](benchmark-tests.txt) records the run.
These checks cover final timeout enforcement, external-binary provenance,
interruption between cells, altered counters/timings/diagnostics and dirty or
mismatched reproduction harness provenance, in addition to the original checks.
