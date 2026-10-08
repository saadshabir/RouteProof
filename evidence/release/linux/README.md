# Completed Linux acceptance

Validation date: **2026-10-08 UTC**. Both clean Release builds passed all 11
CTest groups; both fresh live matrices passed all **27 snapshots and 687 slots**,
with complete cleanup. [Hosted run 37725496964](https://github.com/saadshabir/RouteProof/actions/runs/37725496964)
tested source `f2921b80eecfe6c19e2f82b290384f74a76cab95` on Ubuntu 24.04
amd64, Linux `6.17.0-1022-azure`, GCC 14.2.0 and Containerlab 0.79.0.
Exact Docker/compiler/kernel/image metadata stays in the raw attachment.

FRR 10.2.1 startup, generated configuration and actual OSPF/Zebra/kernel JSON
compatibility are verified. The frozen image is:

```text
quay.io/frrouting/frr@sha256:e47e67bd612030cb1bedee2bde85b73913f2ea021573b749deb21d94940f03c1
```

| Scenario | Snapshots per run | Slots per run | First / clean reproduction |
| --- | ---: | ---: | --- |
| Pair | 3 | 36 | pass / pass |
| Asymmetric pair | 3 | 36 | pass / pass |
| Chain | 5 | 126 | pass / pass |
| Diamond | 6 | 69 | pass / pass |
| Parallel links | 5 | 60 | pass / pass |
| Ring | 5 | 360 | pass / pass |
| Total | 27 | 687 | pass / pass |

Every declared destination is compared at every available router on OSPF,
selected active/installed Zebra and kernel forwarding planes. Absence and
unavailable routers remain explicit. [Reproduction](frr-reproduction.json)
requires distinct fresh lab identities and a clean reproduction checkout.

## Linux memory and benchmark reproduction

The frozen `sparse-small-16` workload has 16 routers, 30 physical links (60
directed arcs), two prefixes, one all-branch assertion and eight events. Each
build ran one warmup and five measured fresh processes per mode (ordinary CLI
and instrumented). Canonical bytes, raw counters and workload/source/dependency
hashes reproduce exactly; timing equality is not a gate.

| RSS boundary | First run, bytes | Clean reproduction, bytes |
| --- | ---: | ---: |
| Ordinary CLI peak, five samples | 21,233,664–21,233,664 | 21,237,760–21,237,760 |
| Loaded RSS, five samples | 4,390,912–4,460,544 | 4,370,432–4,468,736 |
| Per-snapshot boundary RSS | 4,702,208–5,201,920 | 4,648,960–5,201,920 |

Peak RSS is the complete launched process high-water value from Linux `wait4`;
loaded and snapshot RSS come from `/proc/self/status`. These measure different
boundaries. [Acceptance JSON](acceptance.json) preserves every sample and its
route/next-hop denominator. Authoritative Linux memory coverage is limited to
this small workload; published larger scaling measurements remain native and
macOS RSS remains provisional. No bytes-per-route or network convergence claim
is inferred from these measurements.

## Raw evidence and independent checking

[The complete passing archive](https://github.com/saadshabir/RouteProof/releases/download/v0.1.0/routeproof-linux-acceptance.tar.gz)
contains both builds' test logs, lab configs/mappings, commands, every physical,
adjacency, LSDB, OSPF, Zebra and kernel capture, normalized comparisons, benchmark
samples and manifests. Raw archives are release attachments; summaries and
[archive checksums](raw-SHA256SUMS) are kept in Git. GitHub Actions artifacts are
also available from the run but expire after 90 days.

```sh
mkdir -p results
tar -xzf routeproof-linux-acceptance.tar.gz -C results
python3 tools/release/check_linux.py \
  --first results/linux-acceptance/first \
  --second results/linux-acceptance/second --out results/linux-rechecked
```

The downloaded bundle was independently rechecked locally with the stricter
same-source/binary guard. It passes without local Linux access because raw
Linux observations already exist; generating those observations requires Linux.
Final packaging also verifies implementation hashes against these receipts.
[Core acceptance for the packaging guards](https://github.com/saadshabir/RouteProof/actions/runs/37726063505)
passes GCC, Clang, macOS, sanitizers and Release smoke checks.

## Preserved initial failure

The first hosted attempt is preserved in [release attachment](https://github.com/saadshabir/RouteProof/releases/download/v0.1.0/routeproof-linux-attempt-1.tar.gz).
It ran source revision `27edb94add3a11615d850d8ed1311eb875d0f4c8` in
[GitHub run 37724355584](https://github.com/saadshabir/RouteProof/actions/runs/37724355584).
Both clean Release builds passed all 11 CTest groups. The live matrix completed
23 of 27 snapshots, matching all 639 observed comparison slots, then timed out
on the parallel-link failure. Cleanup completed; the four unobserved snapshots
were not counted as passing.

FRR retained an inactive next hop with `fib: true` in Zebra's selected route
while OSPF and the Linux kernel used only the surviving interface. The strict
adapter had incorrectly required every retained RIB hop to be active. The
[recorded fixture](../../../tests/frr/fixtures/parallel-withdrawal.json) and
regression test now distinguish inactive RIB records from active installed
forwarding branches, reject malformed or uninstalled active branches, and still
fail comparison when a required ECMP alternative is missing. Raw captures and
poll errors remain in the archived failed attempt.

The source fix is `f2921b80eecfe6c19e2f82b290384f74a76cab95`. Its core acceptance
jobs all passed in [run 37725496887](https://github.com/saadshabir/RouteProof/actions/runs/37725496887).
The archive SHA-256 is recorded in [raw-SHA256SUMS](raw-SHA256SUMS).
Raw captures are release attachments; only summaries and checksums are kept in Git.
