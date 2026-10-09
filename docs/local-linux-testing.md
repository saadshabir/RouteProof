# Local Linux testing with OrbStack

The macOS development machine can run the Linux core checks and live FRR labs
inside a dedicated OrbStack Ubuntu machine. The FRR harness requires Linux
`amd64`, so create that architecture explicitly on Apple Silicon. OrbStack uses
Rosetta for amd64 programs on Apple Silicon; these runs check correctness and
reproduction, rather than native amd64 performance.

[The 2026-10-09 local validation](../evidence/linux/local-orbstack.md) passed all
core and sanitizer groups, both complete live matrices and combined acceptance.

## Machine and packages

The local test machine is `routeproof-test`, running Ubuntu 24.04 with a
four-core limit, a 6 GiB memory limit and a 32 GiB disk limit. Create a machine
only if it does not already exist:

```sh
orbctl list
orbctl create --arch amd64 --cpus 4 --memory 6G --disk 32G ubuntu:24.04 routeproof-test
orb -m routeproof-test -u root
```

In the Linux shell, install the compiler and test dependencies:

```sh
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl git cmake ninja-build g++-14 clang-19 \
  libclang-rt-19-dev python3 iproute2 kmod
```

`libclang-rt-19-dev` supplies the sanitizer runtime when recommended packages
are omitted. Set `CC` explicitly as well as `CXX`: PicoSHA2's CMake project
enables C even though the RouteProof engine uses C++.

Install Docker Engine inside this machine using
[Docker's Ubuntu apt repository instructions](https://docs.docker.com/engine/install/ubuntu/).
The machine's Docker daemon is separate from the macOS OrbStack Docker context.
Install the same Containerlab package and verify the same checksum as
[the Linux acceptance workflow](../.github/workflows/linux-acceptance.yml).
Run the live harness as root in this dedicated machine.

Check that the environment reports `x86_64`, Docker is running, and dummy/veth
interfaces can be created. Probe names must fit Linux's 15-character interface
name limit:

```sh
uname -m
docker version
containerlab version
ip link add rp-dummy-test type dummy
ip link delete rp-dummy-test
ip link add rp-veth-test type veth peer name rp-peer-test
ip link delete rp-veth-test
```

## Core and sanitizer checks

Use a fresh committed checkout on the machine's Linux filesystem. Keep Linux
build directories separate from native macOS builds. The recorded run cloned
the shared macOS repository into
`/home/saad/routeproof-testing/20261009/first-source`.

From the clean Linux checkout:

```sh
export CC=gcc-14 CXX=g++-14
python3 tools/verify_checkout.py --out results/local-core \
  --gcc-cxx /usr/bin/g++-14 --clang-cxx /usr/bin/clang++-19 --jobs 4

CC=clang-19 CXX=clang++-19 cmake --preset host-sanitizers
cmake --build --preset host-sanitizers --parallel 4
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
  ctest --test-dir build/host-sanitizers --output-on-failure
```

The checkout verifier runs all 11 CTest groups in GCC Release, GCC Debug and
Clang Debug, checks identical canonical diamond output, runs the small
benchmark and checks offline FRR generation. Offline generation reports
`skipped` with exit 3; live agreement is checked separately.

## Live FRR and clean reproduction

Use the tested immutable FRR image, and pre-pull it before the harness's bounded
commands begin:

```sh
export ROUTEPROOF_FRR_IMAGE=quay.io/frrouting/frr@sha256:e47e67bd612030cb1bedee2bde85b73913f2ea021573b749deb21d94940f03c1
docker pull --platform linux/amd64 "$ROUTEPROOF_FRR_IMAGE"
build/host-release/routeproof bench --profile benchmarks/profiles/sparse-small.json \
  --out results/local-first/bench-small
python3 tools/frr/run_matrix.py --image "$ROUTEPROOF_FRR_IMAGE" \
  --routeproof "$PWD/build/host-release/routeproof" --out results/local-first/frr
```

Repeat the Release build, all CTest groups, small benchmark and live matrix
from a second clean clone with a distinct binary path and fresh output
directories. Run the combined validator against the two bundles:

```sh
python3 tools/linux/check_acceptance.py \
  --first /absolute/path/to/local-first \
  --second /absolute/path/to/local-second \
  --out results/local-checked
```

It checks distinct fresh labs, source/binary provenance, canonical bytes, raw
benchmark counters and complete Linux memory samples. Each live matrix must
finish all 27 snapshots and 687 comparison slots, and confirm cleanup.

OrbStack's architecture and emulation behavior are described in its
[architecture documentation](https://docs.orbstack.dev/architecture).
