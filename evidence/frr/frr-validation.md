# Phase 4: FRR tooling and offline validation

Historical offline validation date: **2026-10-06**. Host: macOS 27.0.1 arm64.
The Linux gate was open at that time. It is now complete in [Linux acceptance](../linux/README.md):
two fresh live matrices pass all 27 snapshots and 687 slots each. Earlier raw
records and open-gate notes below describe this historical offline run.

## Implemented

- Deterministic lab/config generation from C++-validated canonical scenarios,
  explicit interface/address mapping, directional costs, passive dummy
  attachments, area 0, and a declared ECMP capacity.
- Five profiles/six scenarios covering 27 baseline/post-event snapshots.
- Physical link/router down/up replay with no-ops and preserved administrative
  state; bounded daemon readiness and table stability; raw captures/logs.
- Strict FRR 10.2.1 OSPF/Zebra adapters and Linux kernel forwarding normalization,
  complete next-hop identity, connected delivery, explicit absence/unavailability,
  mismatch reports and full comparison denominators.
- Run-owned cleanup on success, mismatches, partial deployment, interruption,
  and infrastructure failure; cleanup failures cannot become passes.
- Fresh-run matrix orchestration and an exact semantic rerun checker.

The [workflow documentation](../../docs/validation.md) gives generation and live
commands, limits, normalization rules, event semantics, and artifact layout.

## Checks performed

All **9 CTest checks** passed against each existing compiler build after CMake
registered `frr.offline_harness`:

```sh
ctest --test-dir build/host-debug --output-on-failure
cmake --build --preset gcc-debug
ctest --test-dir build/gcc-debug --output-on-failure
cmake --build --preset clang-debug
ctest --test-dir build/clang-debug --output-on-failure
```

Raw results: [host](host-validation.txt), [GCC build](gcc-build.txt),
[GCC tests](gcc-validation.txt), [Clang build](clang-build.txt), and
[Clang tests](clang-validation.txt). Exact compiler versions are in
[toolchains.json](toolchains.json): Apple Clang 21.0.0, GCC 12.5.0, and upstream
Clang 18.1.8. These are local existing-build checks, not a new clean-checkout or
Linux build claim. No C++ routing behavior changed in this phase.

The initial standalone harness check passed **14 tests** on Python 3.9.6:

```sh
python3 tests/frr/check_frr.py build/host-debug/routeproof
```

[Raw harness output](offline-harness.txt) records that run. Tests cover:
hand-calculated diamond JSON/ECMP fields, invalid formats/gateways/installation,
missing/extra routes and branches, unavailable routers, stability resets and
timeouts, raw command failures, partial deployment, cleanup failure and ownership
refusal, initially unavailable state/no-ops/restoration, prefix masks/costs,
zero-link and long-ID generation, CLI diagnostics and preserved artifacts, and
rerun comparison. The six-profile-scenario transport exercise uses an independent
Floyd–Warshall oracle, checks 27 snapshots and **687 slots**, and asserts complete
agreement with C++ expectations. These are **synthetic transport observations**,
not FRR measurements. The JSON fixture explicitly says it is synthetic.

A full generation-only CLI run also completed:

```sh
python3 tools/frr/run_matrix.py --generate-only --out results/frr-phase4-evidence
```

It exits **3** with `status: skipped`, 27 requested snapshots, **zero** FRR
observations and zero observed comparison slots. See
[generation stdout](generation-command.txt), [raw matrix report](offline-generation.json),
and the selected [diamond configs/mapping](generated-diamond/lab/mapping.json).
The selected generated topology, node configs/daemon files, scenario, manifest,
and skipped report are saved under `generated-diamond/`. Original output paths
and random run identity remain in the raw artifact; regeneration produces new
run paths/identities while preserving canonical scenario/result semantics.
The tag `quay.io/frrouting/frr:10.2.1` is an **unverified candidate**, not a frozen
or tested live image pin.

The rerun checker correctly refuses two skipped reports:

```sh
python3 tools/frr/compare_runs.py results/frr-phase4-evidence/matrix-report.json \
  results/frr-phase4-evidence/matrix-report.json
```

It exits 3 with `incomplete`; [raw output](skipped-rerun-check.txt) confirms that
identical generation-only artifacts cannot satisfy the live reproduction gate.

## Open acceptance work

The subsequent [review fixes](review-fixes.md) address kernel next-hop objects,
malformed route envelopes, `/32` local delivery, and fresh/clean rerun provenance.
Their final standalone harness passes **17 tests**, all **9 host CTest checks**
pass, and the corrected matrix generation still reports `skipped`. Earlier logs
and selected configs above are preserved as historical artifacts.

A live-host preflight returned `incomplete` with no deployment or route
observations because this host is macOS and has neither Docker nor Containerlab.
[The saved report](host-preflight.json) preserves that failure explicitly.

Still required on Linux amd64:

1. Verify candidate image startup/configuration and recorded JSON compatibility;
   resolve and freeze its tested OCI digest, recording all environment versions.
2. Run the entire supported matrix in fresh labs: exact agreement for all
   27 snapshots and all 687 declared slots, including absence/unavailability.
3. Archive raw OSPF, Zebra, kernel, physical/adjacency/LSDB observations, configs,
   manifests, mismatches and denominators; preserve any infrastructure failures.
4. Repeat from a clean checkout with fresh labs and pass `compare_runs.py`.

No live FRR route-cost/next-hop agreement, Linux execution, frozen digest, or
clean Linux rerun is claimed. The plan and acceptance checklists retain those gates.
