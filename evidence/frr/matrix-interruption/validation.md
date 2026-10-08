# Phase 4 matrix interruption checks

Validation date: **2026-10-07**. Host: macOS arm64. These checks do not establish
live FRRouting agreement.

The existing Phase 4 implementation had two matrix orchestration gaps: SIGTERM
could stop the parent without coordinating child cleanup, and timeout/interruption
handling replaced the child's partial report with a generic failure. The matrix
now gives the active child a bounded cleanup period and retains its comparisons,
coverage counters, raw output, and provenance. Each child runs in a separate
session; the matrix forwards one termination signal and defers further Ctrl-C
or SIGTERM signals until cleanup and evidence collection finish. Every lab
checkpoint records snapshot and slot totals before cleanup starts. Timeout
always stays incomplete; forced termination marks cleanup unknown. Inconsistent
child exit/report status also remains incomplete.

The offline harness passes **23 tests**, including these interruption regressions:

- A timed-out runner preserves partial mismatches, counters, and cleanup evidence.
- Forced kill and an inconsistent process exit cannot become agreement.
- Real parent/child tests use `execute_live` with simulated transport and cleanup.
  Parent-only SIGTERM and process-group SIGINT/SIGTERM complete cleanup, preserve
  partial coverage/provenance, and stop before the next lab starts.
- SIGINT/SIGTERM during timeout cleanup or an earlier signal's cleanup wait leave
  the matrix alive until child cleanup finishes and its evidence is saved.
- Forced-kill recovery of a real six-snapshot checkpoint retains all **69 compared
  and matched slots** and six passing snapshots while remaining incomplete with
  unknown cleanup. Every earlier checkpoint also carries its cumulative totals.

Commands and raw results:

```sh
python3 tests/frr/check_frr.py build/host-debug/routeproof
cmake --build --preset host-debug
ctest --test-dir build/host-debug --output-on-failure
python3 tools/frr/run_matrix.py --generate-only --out results/frr-phase4-review-fixes-20261007
```

See the current [offline harness](review-fixes/offline-harness.txt),
[build](review-fixes/host-build.txt), [CTest](review-fixes/host-validation.txt),
and [generation](review-fixes/generation.txt) results. Earlier 20-test logs in
this directory are preserved as pre-review evidence. Generation exits
3 (`skipped`) with zero FRR observations. The local host has neither Docker nor
Containerlab ([preflight](host-preflight.json)); the required two live Linux amd64 matrices, tested image digest,
recorded JSON compatibility, and clean rerun are still open.
