# Local OrbStack Linux validation

Validation date: **2026-10-09**. Tested committed source
`f3d5881674f4eecb460f637ecc9a60d897f3ace2` in two separate clean Linux
checkouts. Core, sanitizer, live FRR and clean reproduction checks passed.
No project-code changes were needed.

## Environment

- OrbStack machine: `routeproof-test`, Ubuntu 24.04.5 LTS, Linux amd64.
- Kernel: `7.0.14-orbstack-00380-ga7e0a2dc9535`.
- Machine limits: 4 CPU cores, 6 GiB memory, 32 GiB disk.
- GCC 14.2.0, upstream Clang 19.1.1, CMake 3.28.3, Ninja 1.11.1,
  Python 3.12.3, Docker Engine 29.9.0 and Containerlab 0.79.0.
- FRR 10.2.1 image, verified as Linux amd64:
  `quay.io/frrouting/frr@sha256:e47e67bd612030cb1bedee2bde85b73913f2ea021573b749deb21d94940f03c1`.

The amd64 machine uses emulation on Apple Silicon. These results establish
local correctness and reproduction; timings are not native amd64 performance
measurements.

## Core checks

| Build | CTest groups | Diamond demo |
| --- | ---: | --- |
| GCC Release, first checkout | 11/11 pass | pass |
| GCC Debug | 11/11 pass | pass |
| Clang Debug | 11/11 pass | pass |
| Clang ASan + UBSan | 11/11 pass | pass |
| GCC Release, second clean checkout | 11/11 pass | checked through FRR replay |

All **55 CTest group executions** passed. The checks cover strict input and
parser limits, independent shortest-path and replay oracles, complete ECMP,
failure explanations, offline FRR normalization/orchestration, benchmark
contracts and acceptance workflows. Sanitizers ran with
`ASAN_OPTIONS=detect_leaks=1:halt_on_error=1` and
`UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1`.

The Release, GCC Debug, Clang Debug and sanitized diamond demos produced the
same canonical result bytes:
`c6e0a1be719af6c47b802e2f536b8c7357abcca0aa15e5c2f1f20c24b02fb7d0`.
The small benchmark and offline FRR generation checks also passed their
contracts; generation-only results retained their expected `skipped` status.

## Live FRR and reproduction

| Scenario | Snapshots per run | Slots per run | First / clean rerun |
| --- | ---: | ---: | --- |
| Pair | 3 | 36 | pass / pass |
| Asymmetric pair | 3 | 36 | pass / pass |
| Chain | 5 | 126 | pass / pass |
| Diamond | 6 | 69 | pass / pass |
| Parallel links | 5 | 60 | pass / pass |
| Ring | 5 | 360 | pass / pass |
| Total | 27 | 687 | pass / pass |

Both matrices matched every declared slot across OSPF, selected installed
Zebra routes and kernel forwarding. All 12 fresh scenario labs confirmed
cleanup. The final Docker inventory contained no containers and only the
default `bridge`, `host` and `none` networks. Both source checkouts remained
clean.

The combined Linux acceptance validator reported `status: pass`,
`acceptance_complete: true` and no open gates. It validated fresh lab
identities, the same tested implementation/binary for each run's FRR and
benchmark captures, exact semantic FRR reproduction, identical canonical
benchmark bytes/counters and complete positive Linux RSS samples. Each small
benchmark had one warmup and five measured processes in each mode.

## Evidence and setup corrections

Complete local logs and raw captures are retained under the ignored directory
`results/local-linux-20261009/`: `core/verification.json`,
`sanitizer-tests.txt`, `second-release-tests.txt`, both `first/` and `second/`
FRR/benchmark bundles, and `checked/acceptance.json`. Provisioning scripts,
command logs and the failed initial configure log are retained there too.
The checked acceptance summary is also retained in
[orbstack-acceptance.json](orbstack-acceptance.json).

The fresh minimal machine initially lacked a default C compiler command;
setting `CC=gcc-14` resolved PicoSHA2's configure failure. Installing
`libclang-rt-19-dev` resolved the missing sanitizer libraries. An initial
network probe used an interface name exceeding Linux's 15-character limit;
the corrected dummy/veth probes passed. None required changes to RouteProof.

[The local testing guide](../../docs/local-linux-testing.md) records the setup
and rerun commands. Live captures here supplement the historical
[hosted Linux validation](README.md).
