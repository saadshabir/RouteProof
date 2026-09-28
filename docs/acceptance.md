# v0.1 acceptance checklist

The release stays incomplete until every deliverable has reproducible evidence. A checked box must point to a command, result, or evidence artifact; implementation status alone is not evidence.

| Release deliverable | Required acceptance evidence | Status |
| --- | --- | --- |
| C++20 routing engine: validated single-area model, prefixes, shortest paths, complete ECMP | Independent tiny-graph oracle agrees on costs and all first-hop interfaces, including asymmetry and parallel links | Not implemented |
| Link/router failure scenarios with deterministic replay | Baseline plus each ordered event yields canonical snapshots; repeat runs/toolchains agree; router restoration preserves link administrative state | Not implemented |
| All-branch reachability and useful explanations | Every ECMP branch is checked; each emitted witness/frontier certificate validates against its snapshot; resource exhaustion is `incomplete` | Not implemented |
| FRRouting comparison | Fresh supported labs agree on converged route costs and full next-hop sets for every declared snapshot, including missing routes | Not implemented |
| Reproducible time, memory, and scaling measurements | Frozen workload, commands, toolchain/host manifest, raw samples, hashes, and one clean-checkout reproduction | Not implemented |

## Phase 0 exit gate

- [x] The model and strict scenario/result schema versions are visible in documentation and `routeproof --version`.
- [x] CMake presets configure and build a clean checkout with the declared GCC and Clang toolchains.
- [x] The Linux FRR lab host and tooling path are documented in [lab-environment.md](lab-environment.md).
- [x] The five release deliverables above remain the complete v0.1 scope.

The clean-checkout build evidence and exact tested toolchain versions are recorded in [phase0-builds.md](../evidence/phase0/phase0-builds.md). Later phases add evidence links beside each release row rather than weakening these conditions.

## Phase 1 exit gate

- [x] Strict YAML parsing rejects duplicate keys, multiple documents, unsupported or mismatched tags, non-string mapping keys, and unknown fields.
- [x] Semantic validation checks identifiers, router IDs, links and event targets, costs and timestamps, canonical IPv4 prefixes in `1..32`, disjoint prefix ownership, assertions, and the OSPF cost bound; default routes are rejected.
- [x] The constructed physical graph passes an integration check of directional arcs, parallel link IDs, derived endpoint interfaces, router availability, link administrative state, and prefix ownership.
- [x] Reordered router/link/event declarations and multiple prefixes/assertions, endpoint reversal with corresponding cost reversal, and omitted default `up` state normalize to identical JSON and hashes.
- [x] CTest passes both the physical-topology integration check and named valid/invalid CLI fixtures; commands and results are in [input-validation.md](../evidence/phase1/input-validation.md).

The CLI validates scenarios only. Route calculation, failure replay, and reachability acceptance remain open for later phases.
