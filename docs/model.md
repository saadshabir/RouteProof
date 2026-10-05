# RouteProof model contract

**Model ID:** `ospf_spf_v1`

**Scenario schema:** `schemas/scenario-v1.schema.json` (version 1)

**Result schema:** `schemas/result-v1.schema.json` (version 1)

**Status:** frozen contract for v0.1. Phases 1–2 implement input validation, physical topology, SPF, and baseline forwarding tables. Replay and reachability behavior remain future phases.

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

`routeproof routes FILE [--timing]` computes the declared initial state only. Its diagnostic JSON format is [baseline-v1.schema.json](../schemas/baseline-v1.schema.json), separate from the future simulation result. It does not apply events or evaluate assertions. Route rows are ordered lexically by `(router, prefix)`; first-hop sets by `(neighbor, link, interface)`. A remote route records `distance_to_origin`, `metric = distance + stub_cost`, and equal `protocol_cost`. Connected delivery has distance and metric 0, protocol cost equal to stub cost, and an empty next-hop set. Prefix lookup uses the validated disjoint attachment domain.

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

## Deterministic data and hashes

Normalize accepted inputs before hashing: canonical IPv4 and prefix text; routers, links, prefixes, and assertions in their documented stable order; events by sequence; complete next-hop sets sorted by `(neighbor, link, interface)`. Reordering declarations must not alter the normalized scenario or results. Generated workloads must identify the PRNG algorithm as well as the seed.

Canonical result JSON uses UTF-8, ASCII field names and IDs, lexically sorted object keys, no insignificant whitespace, decimal integers, and deterministic array order. `scenario_sha256` hashes the normalized scenario representation. A snapshot SHA-256 hashes its normalized physical state and full route tables. `canonical_sha256` hashes the canonical result projection after omitting all `canonical_sha256` and `result_sha256` fields; finding records then repeat that result digest without a self-reference. Hashes use SHA-256.

`result.json` contains routing semantics only. Host details, timestamps of the run, wall-clock samples, filesystem paths, and resource usage belong in separate `run.json` provenance. Every failed/incomplete finding includes a reproduction argument vector using a stable `<scenario>` placeholder rather than a machine-specific path.

## Versioning and release boundary

The CLI reports project version `0.1.0`, model ID `ospf_spf_v1`, scenario schema version `1`, and result schema version `1`. A semantic or structural change that would make a v1 document mean something different requires a new model/schema version. The five release deliverables and their evidence gates are tracked in [acceptance.md](acceptance.md).
