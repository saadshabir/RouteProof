# Phase 0 clean-checkout build evidence

**Recorded:** 2026-09-28

**Temporary source snapshot:** `069c9edca3289f0b083d5161554368a702bbf6c5`

**Host:** macOS 27.0, Darwin 27.0.0, arm64

The repository working tree was copied to a temporary source tree, committed in a temporary Git repository, cloned into a fresh checkout, and built there. The checkout reported no changes before or after the builds. This snapshot includes the Phase 0 model, schemas, build files, CLI, README, plan, and acceptance checklist. This evidence file was added after that snapshot.

## Tested minimum toolchain

| Tool | Version used |
| --- | --- |
| CMake | 3.25.2 |
| Ninja | 1.11.1 (`1.11.1.git.kitware.jobserver-1` executable version) |
| GCC | 12.5.0 |
| Upstream Clang | 18.1.8 |
| Apple Clang | 21.0.0 |

The generic compiler presets configured and built the CLI with both declared compiler families. The host preset also built successfully with Apple Clang. The exact minimums are enforced by `CMakeLists.txt` and documented in [lab-environment.md](../../docs/lab-environment.md).

## Reproduction commands

With CMake 3.25.2 and Ninja 1.11.1 on `PATH`:

```sh
ROUTEPROOF_GCC_CXX=/path/to/g++ cmake --preset gcc-debug
cmake --build --preset gcc-debug
build/gcc-debug/routeproof --version

ROUTEPROOF_CLANG_CXX=/path/to/clang++ cmake --preset clang-debug
cmake --build --preset clang-debug
build/clang-debug/routeproof --version
```

Both builds exited successfully from the clean snapshot. The CLI reported:

```text
RouteProof 0.1.0
model: ospf_spf_v1
scenario schema: 1
result schema: 1
```

The separate `host-debug` preset also configured and built with Apple Clang 21.0.0. CMake and Ninja ran at their declared minimum versions; GCC and Clang ran at the tested floors shown above.

## Scope

This evidence closes the Phase 0 compiler/build-contract gate. It verifies configuration, compilation, clean-checkout behavior, and visible model/schema metadata. It does not claim routing behavior, parser compatibility, test results, FRRouting agreement, Linux lab execution, or performance measurements; those belong to later phases.

Clang 15.0.7 was not retained as the support floor: Homebrew's build could not link against this host's macOS 27 SDK. The Phase 0 floor is the oldest upstream Clang version successfully built here, 18.1.8. Compatibility with older Clang versions on Linux remains unclaimed.
