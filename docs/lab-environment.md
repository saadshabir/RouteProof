# Linux lab environment

**Selected host:** Ubuntu Server 24.04 LTS, x86_64/amd64, on a dedicated Linux VM or bare-metal machine. The authoritative FRR labs use the Linux kernel, Docker Engine, and Containerlab.

Containerlab requires a Linux server or VM and Docker; its installation guide lists Ubuntu 24.04 as a tested host. Docker's official Engine installation guide supports 64-bit Ubuntu 24.04 and amd64. This makes the host suitable for isolated FRR labs using Linux network namespaces, veth interfaces, and containerized routers.

## Toolchain contract

- CMake 3.25.2 or newer; the checked-in presets use schema version 6, introduced in CMake 3.25.
- Ninja 1.11.1 or newer.
- GCC 12.5.0 or newer and upstream Clang 18.1.8 or newer are the compiler build-gate toolchains. The generic CMake presets accept explicit compiler paths on Linux or macOS. Apple Clang 21.0.0 or newer is also supported for native development, but is reported separately from upstream Clang.
- Python 3.9 or newer is required for the default acceptance checks and is used for independent graph oracles, lab orchestration, and measurement summaries.
- Docker Engine from Docker's official Ubuntu repository and Containerlab from its official release/package source.

These minimum compiler/tool versions are the tested support floor. Clean-checkout evidence is recorded in [clean-builds.md](../evidence/build/clean-builds.md). The FRR lab host remains Linux-only.

## FRR lab pinning

Use Containerlab to create fresh, isolated point-to-point topologies with explicit interface mapping and one FRR node per modeled router. The FRR image tag and OCI digest, Docker/Containerlab versions, kernel, architecture, and generated lab configuration must be recorded in each FRR comparison evidence bundle. Freeze the image digest after the first supported lab has been checked for OSPF behavior and route-output normalization. A mutable `latest` tag is not acceptable evidence.

The selected lab host is the target environment, not a claim that FRR comparisons have run. A macOS checkout can satisfy the compiler build gate when both declared compilers are installed, but it cannot run the privileged Linux/containerlab labs.
