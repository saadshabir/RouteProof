# RouteProof model contract

**Model ID:** `ospf_spf_v1`

**Scenario schema:** `schemas/scenario-v1.schema.json` (version 1)

**Result schema:** `schemas/result-v1.schema.json` (version 1)

**Status:** frozen, implemented and accepted v0.1 contract. Input validation, physical topology, SPF, converged replay, universal reachability and validated witnesses pass independent checks. Two fresh Linux FRR matrices reproduce all 27 snapshots and 687 slots; native timing/scaling and authoritative Linux small-workload RSS are published ([acceptance](../evidence/linux/README.md)).

This document defines the behavior the engine must implement. The JSON Schemas define the structural data contract for YAML or JSON inputs and canonical JSON results. Semantic checks below remain mandatory even when a document passes schema validation.

## Supported model

- One IPv4 OSPF-style area, area 0. The model is a converged SPF calculation, not an OSPF daemon or wire-protocol implementation.
- Routers have stable IDs and unique 32-bit IPv4-form OSPF router IDs. Router IDs are compared numerically.
- Links are numbered point-to-point physical links with unique stable IDs. Endpoints must be distinct known routers. Parallel links are allowed.
- A link supplies positive directional costs `cost_ab` and `cost_ba`, each in `1..65535`. The outgoing interface identity is derived as `<link-id>@<router-id>`. This simulator identity is stable and does not claim to be a Linux or vendor interface name.
- Routers and links start `up` unless `initial_state` is `down`. Router availability and link administrative state are separate.
- Prefixes are non-overlapping IPv4 networks with lengths in `1..32`, exactly one known origin, and a stub cost in `1..65535`. Prefix text must name its canonical network address. Default routes (`/0`) are unsupported.
- A prefix origin delivers locally through a connected terminal action. A remote route has metric `distance(source, origin) + stub_cost`. Connected metadata is kept distinct from the OSPF calculation metric when comparing FRR output.
- A destination address must match exactly one declared prefix. There is no longest-prefix-match tie or overlap behavior in v0.1.
- At least one router and one prefix are required. Links, events, and reachability assertions may be empty. A `must_reach` assertion has `quantifier: all` and `scope: every_snapshot`.

## Forwarding calculation

Use a directed graph internally. An arc from router `x` to `y` uses the directional cost of `x`'s outgoing interface. Both directions of a physical link are usable only while the link is administratively up and both endpoint routers are available.

For each available source, compute shortest distances with Dijkstra, then propagate complete first-hop interface sets over the shortest-path DAG in increasing-distance order. Preserve parallel links as distinct alternatives, even when they share a neighbor. Sort and deduplicate next-hop tuples `(neighbor, link, interface)`. A single parent pointer or one sampled path is insufficient. Unreachable prefixes are absent from that source's table.

For the FRR-compatible profile, validate this conservative bound before calculation:

```text
(R - 1) * maximum_directional_cost + maximum_stub_cost < 0x00ffffff
```

Check integer arithmetic before multiplication and addition. This keeps all allowed simple-path costs below OSPF infinity. Router IDs, IDs, timestamps, event sequence numbers, route counts, and intermediate route costs also require explicit range and overflow checks.

With strictly positive link costs, every selected forwarding edge must strictly reduce distance to the route origin. Treat this as a runtime invariant. Full recomputation is the initial algorithm; do not retain all-pairs path lists or add incremental SPF before profiling shows a need.

## Baseline routing interface

`routeproof routes FILE [--timing]` computes the declared initial state only. Its diagnostic JSON format is [baseline-v1.schema.json](../schemas/baseline-v1.schema.json), separate from the simulation result. It does not apply events or evaluate assertions. Route rows are ordered lexically by `(router, prefix)`; first-hop sets by `(neighbor, link, interface)`. A remote route records `distance_to_origin`, `metric = distance + stub_cost`, and equal `protocol_cost`. Connected delivery has distance and metric 0, protocol cost equal to stub cost, and an empty next-hop set. Prefix lookup uses the validated disjoint attachment domain.

The library accepts a `spf::PhysicalState` separately from immutable topology, and recomputes all tables. State dimensions are checked before routing; unavailable sources retain empty tables and are skipped before SPF, sharing-cache allocation, and prefix scanning. Per-source scratch storage is reused; prefixes sharing a source/origin share immutable next-hop sets. Runtime validation checks every selected interface's availability, shortest-path equality, and strictly decreasing distance to its origin. It stores no all-pairs trees or complete paths.

`forwarding::RoutingLimits` defaults to 1,000,000 materialized route entries, 4,000,000 logical next-hop references (including references from prefixes sharing a set), and 4,000,000 per-source scratch next hops. Counters are checked before insertion. Limit exhaustion raises `spf::ResourceLimit`; the CLI exits 3 with a diagnostic and emits no partial route output. Library callers may override these operational limits. State dimensions must match the topology. The routing library requires the validated positive-cost model from the input module.

`--timing` writes separate stderr JSON with a monotonic `baseline_compute_ns` sample. It includes SPF, ECMP propagation, table construction, and runtime invariant validation; it excludes input parsing, state initialization, and output serialization. No canonical JSON field varies with this measurement. This is a timing hook, not published performance evidence.

## Input validation and unsupported constructs

Reject duplicate YAML/JSON keys, multiple YAML documents, custom YAML tags, unknown fields, duplicate IDs, duplicate router IDs, unresolved endpoints/origins/event targets, self-links, noncanonical or invalid addresses, default routes, overlapping prefixes, and event-order violations. Recognized explicit YAML tags are `map`, `seq`, `str`, `int`, `bool`, `float`, and `null` in the standard YAML namespace; their node kinds and the expected field types must agree. Mapping keys must be strings. Diagnostics identify the field or source location, offending value, and expected rule. No accepted input may silently discard a field that could affect routing.

Files ending in `.json` (case insensitive) use strict JSON syntax. JSON object/array input is also recognized by content when the source has another name; flow-style YAML remains supported. JSON Unicode escapes, including valid surrogate pairs, decode to the same UTF-8 values as literal text. Duplicate keys are checked after escape decoding, before normalization. YAML aliases may refer to completed nodes; aliases to an active ancestor are rejected as recursive.

Input parsing has operational budgets: 16 MiB of source bytes, 1,000,000 node/alias occurrences (including mapping keys), 100,000 entries per mapping or sequence, 64 KiB per decoded scalar, and syntactic nesting depth 128 (root depth 0). File reads stop at the byte budget; the remaining budgets are enforced while parsing, before topology construction. Exceeding a budget is an input error (CLI exit 2). Library callers can supply `InputLimits` to `load_scenario` or `parse_scenario`. These limits bound processing resources without changing normalized scenario semantics.

CLI summaries and diagnostics escape terminal controls and malformed UTF-8 bytes. Normalized JSON retains the original validated string values and hashes.

| Supported in v0.1 | Explicitly unsupported in v0.1 |
| --- | --- |
| One area (area 0), IPv4, single-origin disjoint prefixes | Multiple areas, IPv6, VRFs, overlapping prefixes, multiple origins |
| Numbered point-to-point links, asymmetric positive costs, parallel links | Broadcast networks, DR elections, tunnels |
| Connected origin attachments and remote OSPF-style routes | External/redistributed/default routes, dynamic prefix announcements, policy changes |
| Link/router availability failures and restoration | Cost-change events, BFD, packet/adjacency state machines, LSA aging/flooding |
| Converged snapshots and all-branch `must_reach` checks | Transient forwarding, detection delay, router-by-router installation |
| Strict versioned YAML/JSON data model | Full FRR configuration import |

Unsupported values and fields are errors, not ignored extensions.

## Events, snapshots, and reachability

Events are `link_down`, `link_up`, `router_down`, or `router_up`. Each has a unique ID, unique positive sequence number, and nonnegative `at_ns`. Sequence number defines execution order; timestamps must be nondecreasing in sequence order and are annotations only. Equal-time events are each applied and checked separately. Declaration order does not change event order.

An event targeting an already matching state is a recorded no-op. Unknown targets are errors. Router restoration preserves each incident link's administrative state. Start with a fully converged baseline, then apply each event, recompute every route table, publish one atomic converged snapshot, evaluate assertions, and save the result. No check sees partial or stale forwarding state.

For `must_reach` with quantifier `all`, every eligible ECMP choice at each hop must eventually deliver to the requested attachment. Check the whole reachable forwarding graph, including cycles; do not enumerate every simple path. Reject an assertion if the source or attachment is down, any eligible branch lacks a usable action, or any reachable cycle can persist. A successful branch never cancels a failed branch.

Findings distinguish `source_down`, `destination_down`, `no_route`, `link_down`, `next_hop_down`, `loop`, and `incomplete`. A missing route after a partition is a failed assertion with available-component/frontier evidence, not automatically an SPF defect. An incomplete analysis never counts as a pass. Witness paths and partition evidence must be checked against their referenced snapshot.

### Implemented replay and analysis interfaces

`engine::replay` retains a current snapshot and computes a candidate's complete tables before publishing through its observer. A routing failure never publishes partially computed tables. The output consumer publishes each snapshot and its full assertion set together. Router events mutate only router availability, and link events mutate only link administrative state. Identical states have identical snapshot hashes, including no-ops; snapshot/event identities remain separate.

`analysis::DestinationAnalysis` builds a graph once per requested destination prefix and snapshot. It validates every selected link/interface against physical state, uses iterative Kosaraju strongly connected components to detect cycles, and propagates failure backwards to every source that can choose a failed branch. A cycle with a delivery exit still fails. Passing sources need no path enumeration. For a failed source, select the lexically first unusable edge or unsafe successor at each step until a terminal or repeated vertex; include the repeated vertex and zero-based `cycle_entry` for a closed cycle. Source-down takes precedence when both source and origin are unavailable. A connected action is terminal only at the available origin; malformed interface/terminal actions are `incomplete`.

Every emitted witness is checked again for route membership, physical traversal, terminal state, and cycle closure by `validate_witness`. No-route certificates contain the exact available component at the current drop router, every boundary link and its unavailable state, and unavailable routers at that boundary. A malformed FIB may omit a route even inside a physically connected component; the checker does not claim a physical partition in that case. Historical paths are not retained. The independent Python replay reference revalidates all emitted paths/frontiers and compares every snapshot's full route domain against Floyd–Warshall.

Graph classification takes `O(R + H)` time/storage per destination, where `H` is that destination's forwarding-edge count; witness selection is bounded by `R + 1` steps. All traversals are iterative. A physical certificate takes `O(R + L)` work. Graphs are cached per destination within the current snapshot, then released. Canonical JSON history is retained within explicit output budgets; C++ snapshots retain no unbounded history.

`output::SimulationLimits` defaults to 10,000 snapshots (including baseline), 1,000,000 assertion evaluations, 100,000 destination analyses, 10,000,000 cumulative analyzed vertices, 40,000,000 conservatively charged analyzed edges, 2,000,000 retained route rows, 8,000,000 retained next-hop references, and a conservative 64 MiB canonical-output allowance including digest/structure overhead. Edge charging counts the snapshot's total logical next-hop references for each destination analysis, so it may reject earlier than an exact per-destination count. `AnalysisLimits` additionally caps each graph at 1,000,000 vertices and 4,000,000 edges. Routing limits remain those documented above. Library callers may override limits; these counters bound retained work/data, not process RSS. One candidate table/serialization may coexist with completed output.

Limit exhaustion or computation failure returns canonical `status: incomplete`, an `incomplete_reason`, and completed/requested snapshot counts. Only fully analyzed snapshots are retained, so a previously passing prefix of a trace never becomes a passing incomplete run. A preflight failure may retain zero snapshots. A small diagnostic result is emitted even when the output allowance is zero. `simulate` returns 3 in these cases. Invalid scenarios return 2 before output creation. Output failures return 3; no successful result is claimed for an unwritten artifact.

`run.json` records compiler/program/model versions, source path, semantic digests, completed snapshots, applied/no-op event counts, and a separate monotonic `simulation_ns`. Its boundary includes replay, route computation, analysis, witness validation, and canonical serialization; it excludes parsing and file writes. No-op events are separately counted and never included in `applied_events`. This diagnostic sample is not published performance or convergence evidence.

`explain` bounds result input at 64 MiB and nesting at 128, rejects duplicate JSON keys and unsupported versions, and verifies result/finding/snapshot hashes and every finding's assertion/scenario/snapshot/event references before displaying the selected assertion. Assertion statuses must agree with their findings, and a complete result's status must agree with all assertion outcomes. Incomplete results require a nonempty reason and integer completed/requested snapshot counts consistent with the retained snapshots. Displayed JSON strings escape terminal controls. It does not reconstruct the original topology or independently certify an arbitrary externally supplied result; witness validation belongs to simulation and the reference checks.

## Deterministic data and hashes

Normalize accepted inputs before hashing: canonical IPv4 and prefix text; routers, links, prefixes, and assertions in their documented stable order; events by sequence; complete next-hop sets sorted by `(neighbor, link, interface)`. Reordering declarations must not alter the normalized scenario or results. Generated workloads must identify the PRNG algorithm as well as the seed.

Canonical result JSON uses UTF-8, ASCII field names and IDs, lexically sorted object keys, no insignificant whitespace, decimal integers, and deterministic array order. `scenario_sha256` hashes the normalized scenario representation. `events_sha256` and `assertions_sha256` hash the corresponding normalized arrays. A snapshot SHA-256 hashes exactly the object containing `available_routers`, `administratively_up_links`, and `routes`, including route metadata. Event identity is excluded so no-ops reuse the same state digest. `canonical_sha256` hashes the canonical result projection after omitting all `canonical_sha256` and `result_sha256` fields; finding records then repeat that result digest without a self-reference. Hashes use SHA-256.

`result.json` contains routing semantics only. Host details, timestamps of the run, wall-clock samples, filesystem paths, and resource usage belong in separate `run.json` provenance. Every failed/incomplete finding includes a reproduction argument vector using a stable `<scenario>` placeholder rather than a machine-specific path.

## Model and schema versioning

The CLI reports project version `0.1.0`, model ID `ospf_spf_v1`, scenario schema version `1`, and result schema version `1`. A semantic or structural change that would make a v1 document mean something different requires a new model/schema version. The five implementation deliverables and their evidence gates are tracked in [acceptance.md](acceptance.md).
