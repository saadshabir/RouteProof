# Independent checks and FRRouting differential labs

The C++ model is `ospf_spf_v1`: one IPv4 area, numbered point-to-point links,
positive directional costs, passive single-origin destinations, and complete
ECMP interface sets. [Routing](../evidence/routing/routing-validation.md) and
[replay](../evidence/replay/replay-validation.md) evidence record the independent
core checks. Phase 4's lab tooling is implemented and tested offline. **Live FRR
agreement and the clean Linux rerun remain unverified.**

## Commands

Python 3.9+ is sufficient for generation, normalization, and harness tests. There
are no additional Python packages. Build RouteProof first; pass `--routeproof`
when using a binary outside `build/host-debug`.

```sh
python3 tests/frr/check_frr.py build/host-debug/routeproof
python3 tools/frr/run_matrix.py --generate-only --out results/frr-generated
python3 tools/frr/run_lab.py --scenario examples/diamond-failures.yaml \
  --generate-only --out results/frr-diamond-generated
```

Generation-only runs exit **3**, save a `skipped` report with zero observed slots,
and require no Docker, root access, or network. They default to the **unverified
candidate** `quay.io/frrouting/frr:10.2.1`. Generated topologies with that tag are
for review only; live runners require an immutable digest.

For authoritative runs, use a Linux amd64 host with Docker Engine, Containerlab,
and permission to create network namespaces/veth links. Resolve the candidate
image on that host:

```sh
docker pull --platform linux/amd64 quay.io/frrouting/frr:10.2.1
docker image inspect quay.io/frrouting/frr:10.2.1 --format '{{json .RepoDigests}}'
```

Set `ROUTEPROOF_FRR_IMAGE` to the returned `repository@sha256:...` reference.
Commit the implementation being tested before collecting release evidence;
the reproduction below clones committed files and builds a new binary. Run the
first matrix from the original checkout:

```sh
sudo -E python3 tools/frr/run_lab.py --scenario labs/profiles/pair.json \
  --image "$ROUTEPROOF_FRR_IMAGE" --routeproof build/host-debug/routeproof \
  --out results/frr-pair
sudo -E python3 tools/frr/run_matrix.py --image "$ROUTEPROOF_FRR_IMAGE" \
  --routeproof build/host-debug/routeproof --out results/frr-matrix
```

Then reproduce from a fresh clean clone on the same Linux host. The clone and
all evidence directories below must be new:

```sh
git clone --no-hardlinks . results/frr-clean-checkout
cd results/frr-clean-checkout
cmake --preset host-debug
cmake --build --preset host-debug
ctest --test-dir build/host-debug --output-on-failure
sudo -E python3 tools/frr/run_matrix.py --image "$ROUTEPROOF_FRR_IMAGE" \
  --routeproof build/host-debug/routeproof --out results/frr-matrix-rerun
python3 tools/frr/compare_runs.py ../frr-matrix/matrix-report.json \
  results/frr-matrix-rerun/matrix-report.json --out results/frr-rerun.json
```

Every output directory must be fresh. The image architecture and FRR version
are checked at runtime; the JSON adapter targets **FRR 10.2.1**. The candidate's
actual image startup, configuration behavior, and JSON output still need a live
compatibility run. Freeze that tested digest and archive both full matrix runs
before closing the Phase 4 exit gate. A tag, offline test, or skipped run cannot
satisfy that gate.

## Frozen coverage

[The matrix](../labs/profiles/matrix.json) has five profiles and six scenarios.
All declared prefixes are checked at **every available router** on three planes:
OSPF calculation, selected/installed Zebra, and kernel forwarding. Empty slots
are compared too, so partitions cannot disappear from the denominator.

| Profile | Scenario purpose | Snapshots | Available-router × prefix × plane slots |
| --- | --- | ---: | ---: |
| Pair | Link down/up; costs and stub origins | 3 | 36 |
| Pair, asymmetric fixture | Distinct outbound costs in each direction | 3 | 36 |
| Chain | Middle link and middle router down/up | 5 | 126 |
| Diamond | Both ECMP branches, alternate, partition, origin down/up | 6 | 69 |
| Parallel pair | Both physical interfaces; each independently down/up | 5 | 60 |
| Ring | Longer alternate path; link and origin router down/up | 5 | 360 |
| Total | Five profiles, six scenarios | 27 | 687 |

These are **requested coverage dimensions**, not FRR agreement results. The
per-run reports show completed/passing snapshots and actual observed denominators.
Unavailable routers are listed separately. An unavailable router presented as an
empty available table is an infrastructure failure.

## Generation and physical events

The C++ validator produces canonical input; its simulator saves the expected
baseline and each event snapshot. Assertions may fail legitimately (diamond exit
1); incomplete engine output is rejected. The generator never calculates routes.

Each router becomes an indexed Containerlab Linux node. A saved mapping relates
Linux `ethN` interfaces to model `link@router` identities, neighbor IDs, and peer
addresses. Transit /30s and a management /24 come from `198.18.0.0/15`, disjoint
from all modeled destinations and each other. A fixture consuming that pool is
rejected explicitly. Transit costs and point-to-point types are explicit in
area 0. Destination attachments use passive **dummy interfaces** with their real
prefix masks and stub costs; loopback mask conversion is avoided. FRR ECMP
capacity is explicitly 64. Small-lab budgets cap routers/links/prefixes/events
at 16/64/64/64 and require at least one destination.

Generated configs explicitly set `no zebra nexthop kernel enable`. FRR normally
uses kernel next-hop objects when supported; this lab profile disables them so
`ip -j route` contains the gateway/interface alternatives directly. Unexpected
`nhid` references are infrastructure errors with an explicit configuration
diagnostic, rather than an incomplete next-hop comparison.

Link events set both endpoint interfaces down/up. Router-down events disable all
incident modeled links **and every passive destination interface**. The container
and daemons stay running solely for management inspection; all modeled forwarding
connectivity is removed. Router-up re-derives effective interface state from
router availability and each link's administrative state. Previously failed links
stay down. Recorded no-ops still produce snapshots.

The runner allocates a fresh random lab name and management network, refuses
existing resource names, labels every node with the run identity, and verifies
ownership before teardown. A `finally` block cleans partial deployments, failures,
Ctrl-C, and SIGTERM. Only that run's topology is destroyed; no global Docker prune
is used. Cleanup errors and remaining owned resources force `incomplete`. Abrupt
host loss or SIGKILL cannot execute cleanup; saved lab topology and labels identify
resources for recovery.

The matrix runner also handles Ctrl-C and SIGTERM. Each child runs in a separate
session, so a foreground process-group signal reaches the matrix without also
interrupting the child. The matrix forwards one SIGTERM, allows up to 180 seconds
for owned-resource cleanup, saves that child's partial comparisons and provenance,
and stops before deploying another cell. Further Ctrl-C or SIGTERM signals during
cleanup or evidence collection are recorded without interrupting that work or
sending another termination signal to the child. Every lab report checkpoint
includes completed/passing snapshot counts and compared/matched slot totals, so
forced-kill recovery retains coverage already saved before cleanup.
A cell timeout remains `incomplete` even if the child finishes a passing report
while termination is in progress. If the cleanup grace period expires, the
child is killed and cleanup is explicitly `unknown`; earlier comparison evidence
is retained. A runner exit code inconsistent with its report also fails as
incomplete infrastructure.

## Readiness, capture, and stability

Default policy: 90-second snapshot/daemon readiness timeout, 30-second individual
command timeout, 1-second poll interval, at least 3 successful observations, and
at least 6 seconds of unchanged normalized tables. All durations are configurable
positive finite values, with a stable window smaller than the deadline. Commands
inside a poll share the snapshot deadline. These waits are capture readiness,
not published network convergence measurements.

Each poll saves physical interface state, OSPF neighbors, router LSDB JSON,
OSPF calculation routes, selected Zebra routes, and kernel routes. Before a poll
can count toward stability, kernel administrative interface flags must match the
new snapshot and the exact declared adjacency set must be Full; removed neighbors
must be absent. LSDB observations are preserved for diagnosis. Normalized tables
must then remain unchanged over the stable window. Uptime and LSA age do not
participate in the table stability key. Errors reset the stability window.

Agreement with the simulator is **not** a readiness condition: stable mismatches
are reported as differential failures instead of waiting until a desired result
appears. Failed commands, unexpected JSON shapes, uninstalled branches, and
readiness/timeouts remain infrastructure failures with their raw logs. The runner
continues all events after ordinary route mismatches; infrastructure failures stop
that lab while the matrix retains the failed cell and runs the other scenarios.

## Normalization and comparison

FRR's [OSPF inspection commands](https://docs.frrouting.org/en/stable-10.2/ospfd.html#showing-information)
and [Zebra inspection commands](https://docs.frrouting.org/en/stable-10.2/zebra.html#show-ip-route)
provide separate calculation and installed-route observations. Adapter fields
were checked against the official [OSPF source](https://github.com/FRRouting/frr/blob/frr-10.2.1/ospfd/ospf_vty.c)
and [Zebra source](https://github.com/FRRouting/frr/blob/frr-10.2.1/zebra/zebra_vty.c).
Synthetic JSON fixtures protect that contract; recorded live captures remain open.

OSPF costs are compared with `protocol_cost`, including the origin's stub cost.
Zebra costs are compared with `metric`; local connected delivery has metric 0
and the correct dummy attachment. At a `/32` origin, FRR's selected `local` route
is normalized to that same delivery action after checking its owner, attachment,
metric, and lack of a gateway. Kernel `/32` local/main-table delivery rows are
validated separately and collapsed into one action; duplicate rows within a
table are rejected. Remote forwarding must use the main table.
All active installed ECMP interfaces must be
present, with mapped peer addresses. Linux route metrics are not OSPF costs;
kernel comparison checks delivery kind and the complete gateway/interface set.
Next-hop order is canonicalized, duplicates are rejected, and each parallel
interface remains distinct. Only supported default-VRF metadata and OSPF router
calculation rows may accompany prefix keys. Error objects, unknown fields, and
wrapped VRF/route envelopes fail explicitly; they cannot become empty tables.

The comparison domain is exactly the declared destination prefixes. Generated
transit routes and unrelated management/kernel-local routes are excluded in
advance. Unexpected OSPF destinations outside the generated domain are retained
as explicit errors. Within the domain, absent/extra selected routes, wrong costs,
and missing/extra next-hop interfaces produce mismatch records. Local connected
attachments and unavailable origins/routers are checked explicitly.

## Artifacts and acceptance

A single run saves `scenario.json`, the engine's `result.json`/`run.json`, lab
configs/daemon settings/topology/mapping, a manifest, every raw command output,
all poll JSON/errors, per-snapshot comparisons, and `report.json`. The manifest
records normalized scenario/result hashes, binary and source hashes, generated
file hashes, source revision/dirty state, image reference, FRR version, architecture,
and wait policy. Live reports additionally save image inspection and Docker,
Containerlab, kernel, and host metadata. `matrix-report.json` retains every cell
and its provenance manifest, including stderr, infrastructure errors, missing
coverage, and mismatch lists.

Exit codes: 0 complete exact agreement; 1 complete with route mismatches; 2 invalid
CLI/output reuse; 3 incomplete infrastructure or generation-only/skipped. Passing
27 snapshots and all 687 slots on a fresh lab matrix, then reproducing those
normalized results in a second fresh run from a clean checkout, is the declared
Phase 4 gate. The rerun checker requires supported live manifests, recorded
Linux/Docker/Containerlab and image inspection, distinct lab identities across
both matrices, a clean reproduction checkout, matching source hashes/image pin,
and consistent per-cell/snapshot coverage. It then compares canonical
scenario/result hashes and semantic comparison rows. Copied reports, missing
provenance, generation-only runs, and dirty reproduction runs cannot pass.
Old matrix reports without embedded provenance must be regenerated. Binary
hashes, physical paths, timestamps, poll counts, and host provenance may differ
between runs; the fresh clone/build procedure establishes the rebuild step.
