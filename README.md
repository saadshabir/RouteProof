# RouteProof

RouteProof is a C++20 tool that computes single-area OSPF-style routes and complete
ECMP sets, replays link/router failures and restoration, and checks whether every
forwarding branch delivers traffic. Each event produces a converged snapshot.

The v0.1 implementation and acceptance are complete. See the
[acceptance checklist](docs/acceptance.md) for scope and evidence, and the
[model contract](docs/model.md) for routing semantics, resource limits, schemas
and exit codes.

## Quick start

Requires Git, Python 3.9+, CMake 3.25.2+, Ninja 1.11.1+, and GCC 12.5.0+,
upstream Clang 18.1.8+, or Apple Clang 21.0.0+.

```sh
git clone https://github.com/saadshabir/RouteProof.git
cd RouteProof
python3 tools/run.py demo --out results/diamond-demo
```

The launcher builds Release and fetches [pinned dependencies](cmake/Dependencies.cmake)
on first use. It reconfigures when build configuration, tools or environment change;
unchanged launches go straight to the incremental build. Presets with external
includes use automatic configuration. The checked demo exits 0 when all six
snapshots and the two expected reachability failures match. Use fresh output
paths for each run.

## Essential commands

```sh
python3 tools/run.py validate examples/input/valid/diamond.yaml --normalized
python3 tools/run.py routes examples/routing/merged-ecmp.json
python3 tools/run.py simulate examples/diamond-failures.yaml --out results/diamond
python3 tools/run.py explain results/diamond/result.json --assertion a-to-d
python3 tools/run.py bench --profile benchmarks/profiles/sparse-small.json --out results/bench
python3 tools/run.py test
```

`simulate` and `explain` return 1 for this diamond's two expected broken
requirements. `python3 tools/run.py --help` lists launcher commands. The `frr`
command runs the lab matrix; live labs require Linux, Docker, Containerlab and a
pinned FRR image.

For manual builds or repeated direct executable use:

```sh
cmake --preset host-release
cmake --build --preset host-release
build/host-release/routeproof --version
ctest --test-dir build/host-release --output-on-failure
```

Compiler gates use `gcc-debug` with `ROUTEPROOF_GCC_CXX=/path/to/g++` and
`clang-debug` with `ROUTEPROOF_CLANG_CXX=/path/to/clang++`. Linux also has
`linux-gcc-debug` and `linux-clang-debug`; `host-sanitizers` enables ASan/UBSan.

## Documentation and validation

- [Model contract](docs/model.md): input validation, forwarding, replay, explanations and budgets.
- [Acceptance checklist](docs/acceptance.md): v0.1 scope and completion evidence.
- [FRRouting validation](docs/validation.md): offline generation and live lab procedures.
- [Benchmarks](docs/benchmarks.md): frozen workloads, measurement boundaries and reproduction.
- [Local Linux testing](docs/local-linux-testing.md): OrbStack setup and Linux checks on macOS.
- [Validation evidence](evidence/README.md): receipts grouped by capability.
- [Scenario examples](examples/input/README.md) and [schemas](schemas): supported inputs and outputs.

[Core CI](.github/workflows/ci.yml) runs compiler, sanitizer, oracle and harness
checks. [Linux acceptance](.github/workflows/linux-acceptance.yml) runs live FRR
and memory validation. To check a fresh committed source tree and build, run
`python3 tools/verify_checkout.py --out results/checkout-check`.
