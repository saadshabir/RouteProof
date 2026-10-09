# v0.1 acceptance checklist

**Status: completed.** Every v0.1 deliverable has reproducible evidence. Checked boxes point to commands, results or artifacts; Linux acceptance is recorded in [the Linux receipts](../evidence/linux/README.md).

| Deliverable | Required acceptance evidence | Status |
| --- | --- | --- |
| C++20 routing engine: validated single-area model, prefixes, shortest paths, complete ECMP | Independent tiny-graph oracle agrees on costs and all first-hop interfaces, including asymmetry and parallel links | Complete for baseline routing; [Routing evidence](../evidence/routing/routing-validation.md) |
| Link/router failure scenarios with deterministic replay | Baseline plus each ordered event yields canonical snapshots; repeat runs/toolchains agree; router restoration preserves link administrative state | Complete; [Replay evidence](../evidence/replay/replay-validation.md) |
| All-branch reachability and useful explanations | Every ECMP branch is checked; each emitted witness/frontier certificate validates against its snapshot; resource exhaustion is `incomplete` | Complete; [Replay evidence](../evidence/replay/replay-validation.md) |
| FRRouting comparison | Fresh supported labs agree on converged route costs and full next-hop sets for every declared snapshot, including missing routes | Complete; two fresh live Linux matrices agree exactly ([Linux evidence](../evidence/linux/README.md)) |
| Reproducible time, memory, and scaling measurements | Frozen workload, commands, toolchain/host manifest, raw samples, hashes, and one clean-checkout reproduction | Complete; native timing/scaling and Linux small-workload RSS reproduce ([native evidence](../evidence/bench/benchmark-validation.md), [Linux evidence](../evidence/linux/README.md)) |

## Build contract

- [x] The model and strict scenario/result schema versions are visible in documentation and `routeproof --version`.
- [x] CMake presets configure and build a clean checkout with the declared GCC and Clang toolchains.
- [x] The Linux FRR lab host and tooling path are documented in [local-linux-testing.md](local-linux-testing.md).
- [x] The five implementation deliverables above remain the complete v0.1 scope.

The clean-checkout build evidence and exact tested toolchain versions are recorded in [clean-builds.md](../evidence/build/clean-builds.md). Each deliverable requires its own evidence link.

## Input and physical topology

- [x] Strict YAML parsing rejects duplicate keys, multiple documents, unsupported or mismatched tags, non-string mapping keys, and unknown fields.
- [x] Semantic validation checks identifiers, router IDs, links and event targets, costs and timestamps, canonical IPv4 prefixes in `1..32`, disjoint prefix ownership, assertions, and the OSPF cost bound; default routes are rejected.
- [x] The constructed physical graph passes an integration check of directional arcs, parallel link IDs, derived endpoint interfaces, router availability, link administrative state, and prefix ownership.
- [x] Reordered router/link/event declarations and multiple prefixes/assertions, endpoint reversal with corresponding cost reversal, and omitted default `up` state normalize to identical JSON and hashes.
- [x] CTest passes both the physical-topology integration check and named valid/invalid CLI fixtures; commands and results are in [input-validation.md](../evidence/input/input-validation.md).

## SPF and ECMP

- [x] Full-recomputation Dijkstra and DAG propagation retain every equal-cost first-hop interface, including merged and unequal-hop-count alternatives.
- [x] Prefix tables represent connected delivery, remote stub costs, absent routes, and unavailable origins; shared immutable next-hop sets and lookup are checked.
- [x] An independent Floyd–Warshall oracle agrees on every route row and next-hop tuple for seven named and 80 seeded generated tiny graphs, including asymmetry, parallel links, disconnected graphs, and initial physical state.
- [x] Declaration/endpoint order and repeat/timing variations produce identical baseline bytes across GCC, Clang, and Apple Clang.
- [x] Resource boundaries, distance overflow, and the runtime rank invariant are checked; separate ASan/UBSan tests pass.
- [x] A monotonic baseline timing hook excludes parsing/output and keeps measurements outside canonical semantics.

Commands, compiler details, coverage, and logs are recorded in [routing-validation.md](../evidence/routing/routing-validation.md). The replay and reachability checks follow below.

## Failure replay and reachability

- [x] All four events, idempotent no-ops, separate equal-time snapshots, initial unavailability, and administrative restoration semantics pass independent replay checks.
- [x] The diamond produces both ECMP branches, its surviving alternate, partition withdrawal, restored delivery, origin withdrawal, and restoration with `cd` still down.
- [x] Universal delivery rejects a supplied bad ECMP branch and cycle with an exit; 64 tiny FIB variants match an independent traversal reference, and iterative checks handle a 20,000-router chain/cycle.
- [x] Every emitted forwarding path/component/frontier validates against its snapshot in both C++ and the independent Python replay reference; corrupt source/component/cycle witnesses are rejected.
- [x] Canonical result and snapshot hashes, repeated/order-permuted outputs, and compiler equivalence are checked.
- [x] Routing/analysis/history/output budgets produce incomplete results; incomplete snapshots are never published as passing.
- [x] CLI simulation/explanation, digest rejection, invalid input, preserved existing artifacts, and host ASan/UBSan checks pass.

Commands and raw output are recorded in [replay-validation.md](../evidence/replay/replay-validation.md). FRR comparison and measurement acceptance gates also pass ([Linux evidence](../evidence/linux/README.md)).

## FRRouting labs

- [x] Canonical-model lab generation preserves directional costs, passive stub costs, prefix masks, and parallel interface identity.
- [x] All five profiles (six scenarios) and 27 expected snapshots are generated; independent offline transport checks cover 687 comparison slots.
- [x] Readiness/stability deadlines, explicit missing/unavailable states, raw captures, mismatch reports, and run-owned cleanup pass offline failure-injection tests.
- [x] Adapter regressions cover malformed envelopes and `/32` local delivery; generated configs disable kernel next-hop objects for explicit forwarding captures.
- [x] Rerun checks reject reused lab identities, missing/nonlive provenance, inconsistent coverage, and dirty reproduction checkouts.
- [x] FRR 10.2.1 Linux amd64 image startup/configuration and actual JSON compatibility are verified, and the tested digest is frozen.
- [x] Every supported live baseline/post-event snapshot agrees exactly across OSPF, Zebra, and kernel forwarding.
- [x] Raw live captures, environment/configuration manifests, denominators, and a second clean Linux run reproduce the agreement.

Commands, limitations, and evidence are documented in [validation.md](validation.md)
and [frr-validation.md](../evidence/frr/frr-validation.md). Offline transport tests
and generation-only `skipped` reports do not close the live acceptance gate; the two [recorded live runs](../evidence/linux/README.md) do.

## Scenario benchmarks

- [x] Frozen integer/xorshift32 profiles cover five shapes, sizes, prefix density,
  ECMP width, assertion coverage and trace length independently.
- [x] Core/per-snapshot processing and complete CLI time have explicit boundaries;
  instrumentation preserves canonical simulation bytes.
- [x] Each published cell has fixed warmups and five fresh-process repetitions per
  mode, raw samples, actual route/next-hop counters and input/result hashes.
- [x] A clean source snapshot with a distinct Release build reproduces the small
  workload's canonical bytes and counters.
- [x] Budget-skipped cells, timeouts, memory guard failures and interrupted workers
  retain explicit evidence; owned worker processes are terminated and reaped.
- [x] Authoritative Linux peak and boundary RSS samples are published for the 16-router small workload ([receipts](../evidence/linux/README.md)). Native macOS RSS remains provisional.

Commands, measured coverage, raw evidence and limitations are recorded in
[benchmarks.md](benchmarks.md) and [benchmark-validation.md](../evidence/bench/benchmark-validation.md).
The [review-fix evidence](../evidence/bench/review-fixes/README.md) covers interrupted
sweep completion, binary/harness provenance, raw counter/timing reconciliation
and final timeout enforcement.

## Repository usability and CI

- [x] Core CI declares Linux GCC/Clang and native macOS builds, all CTest checks,
  a separate sanitizer/generated-corpus job, and a clean-checkout demo/benchmark
  job ([workflow](../.github/workflows/ci.yml)).
- [x] Current README and model status distinguish implemented behavior, published native
  measurements and completed Linux acceptance ([README](../README.md), [model](model.md)).
- [x] The repository launcher builds and runs scenarios, demos, benchmarks and tests
  ([launcher](../tools/run.py)).
- [x] A checked diamond demo verifies expected failures, restoration and deterministic
  canonical bytes ([runner](../tools/demo.py), [regression tests](../tests/workflows/check_workflows.py)).
- [x] Fresh checkout builds/tests and a separate clean-source benchmark reproduction
  are supported ([checkout checker](../tools/verify_checkout.py),
  [native reproduction](../evidence/bench/benchmark-validation.md)).
- [x] Live Linux lab/image/rerun and authoritative Linux RSS acceptance passes
  ([receipts](../evidence/linux/README.md), [workflow](../.github/workflows/linux-acceptance.yml)).
