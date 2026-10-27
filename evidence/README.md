# Validation evidence

Evidence is grouped by capability: `build`, `input`, `routing`, `replay`, `frr`, `bench`, and `linux`.
Documentation in each group states the tested scope and points to its commands,
logs, fixtures, and source manifests.

Archived logs and manifest paths use the current descriptive directory and test
names. These labels were normalized without changing recorded outcomes, timing
values, or scenario/result hashes. Historical source manifests retain the
checksums of the snapshots originally tested; they are not checksums of today's
edited source tree. Personal filesystem prefixes have been replaced with generic
paths. Planning documents and compressed source/scaling bundles were removed;
retained historical manifests may still name the documents originally tested.
Recorded outcomes, measurements and canonical result hashes are unchanged.
Generated artifact hashes cover the retained files; `historical_generated_hashes`
preserves original hashes for artifacts changed by path redaction.

[FRR tooling evidence](frr/frr-validation.md) records offline harness coverage
and generated lab artifacts. [Linux acceptance](linux/README.md) records two
fresh live matrices with exact agreement for 27 snapshots and 687 slots each,
verified image compatibility, clean reproduction and authoritative small-workload RSS.
Full captures are GitHub Actions artifacts retained for 90 days and can be
regenerated with the hosted workflow.

Scenario timing, provisional native RSS, scaling and clean source reproduction
are recorded in [benchmark-validation.md](bench/benchmark-validation.md).
