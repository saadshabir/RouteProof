# Validation evidence

Evidence is grouped by capability: `build`, `input`, `routing`, `replay`, and `frr`.
Documentation in each group states the tested scope and points to its commands,
logs, fixtures, and source manifests.

Archived logs and manifest paths use the current descriptive directory and test
names. These labels were normalized without changing recorded outcomes, timing
values, or scenario/result hashes. Historical source manifests retain the
checksums of the snapshots originally tested; they are not checksums of today's
edited source tree.

[FRR tooling evidence](frr/frr-validation.md) records offline harness coverage and generation artifacts. Privileged Linux image compatibility, route agreement, and clean-rerun acceptance remain open.

Phase 5 scenario timing, provisional native RSS, scaling, and clean source
reproduction evidence are in [benchmark-validation.md](bench/benchmark-validation.md).
The authoritative Linux memory gate remains open.
