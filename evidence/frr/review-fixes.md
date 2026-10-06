# Phase 4 review fixes

Validation date: **2026-10-06**. These checks ran on the existing macOS host
build. The Linux FRR image compatibility, live agreement, and clean Linux
reproduction gates remain open.

## Changes

1. Generated FRR configs explicitly disable kernel next-hop objects with
   `no zebra nexthop kernel enable`, keeping kernel captures self-contained.
   The adapter reports unexpected `nhid` references as configuration errors.
2. OSPF/Zebra adapters validate the complete default-VRF envelope. Error
   objects, wrapped tables, and unknown fields cannot become route absence.
3. `/32` origin `local` routes normalize to connected delivery only after
   owner, interface, metric, and gateway checks. Kernel local/main delivery
   rows collapse into one action while duplicate rows remain errors.
4. Matrix reports embed each run's manifest. The rerun gate checks live Linux
   environment/image provenance, distinct lab identities, consistent coverage,
   matching source inputs/image pins, and a clean reproduction checkout. The
   workflow now documents a fresh clone and rebuild before the second matrix.

## Verification

- [Standalone harness](review-fixes/offline-harness.txt): **17 tests pass** on
  Python 3.9.6, including all four regressions, the full `/32` failure trace,
  and the five-profile/six-scenario **27-snapshot/687-slot** transport exercise.
- [Host build](review-fixes/host-build.txt) and
  [CTest](review-fixes/host-validation.txt): build succeeds; **all 9 checks pass**.
- [Matrix generation](review-fixes/generation.txt): exits **3**, reports
  `skipped`, requests 27 snapshots, and records zero FRR observations.
  The [saved matrix report](review-fixes/generated-matrix-report.json) includes
  the generated manifests and source/config hashes.
- [Skipped rerun rejection](review-fixes/skipped-rerun.txt): exits **3** with
  `incomplete`; identical generation-only reports cannot satisfy the gate.

Rerun unit cases also reject missing/nonlive manifests, reused identities,
dirty reproduction checkouts, missing Linux/image observations, changed source
inputs, and missing/duplicate snapshot coverage. Valid synthetic provenance
fixtures permit different binary hashes and poll metadata between runs; changed
scenario/result/snapshot hashes fail reproduction. These fixtures and transport
observations are offline contracts, not live FRR evidence.

Earlier artifacts under this evidence group describe the pre-review source
snapshot. Their logs and selected generated configs are preserved. The current
generation report above records the corrected configuration and provenance
format; older reports without embedded manifests must be regenerated for live
acceptance.
