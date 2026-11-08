# Installation and binary distributions

The native executable runs without Python, CMake, Ninja, Git or the source tree.
Scenarios and result paths are supplied by the caller; it does not search for
files in the build or installation directories.

## Download an archive

The [binary distribution workflow](../.github/workflows/release.yml) builds and
tests four archives on pushes to `main`, pull requests and manual runs. They are
downloadable as workflow artifacts. Pushing a version tag matching CMake's
project version (for example `v0.1.0`) also publishes the tested archives and
checksums to [GitHub Releases](https://github.com/saadshabir/RouteProof/releases).
Archives appear only after the workflow succeeds.

| Archive suffix | Target |
| --- | --- |
| `linux-x86_64.tar.gz` | x86-64 Linux, Ubuntu 24.04 or compatible glibc 2.39+ |
| `linux-arm64.tar.gz` | ARM64 Linux, Ubuntu 24.04 or compatible glibc 2.39+ |
| `darwin-x86_64.tar.gz` | Intel macOS 15+ |
| `darwin-arm64.tar.gz` | Apple Silicon macOS 15+ |

Linux releases statically link the GCC C++ runtimes and still use the system
glibc. macOS releases use the system C++ runtime. These archives are unsigned.

Download the archive and its `.sha256` file into the same directory. For example,
on Linux (replace the version and architecture with the chosen release):

```sh
sha256sum --check routeproof-0.1.0-linux-x86_64.tar.gz.sha256
tar -xzf routeproof-0.1.0-linux-x86_64.tar.gz
export PATH="$PWD/routeproof-0.1.0-linux-x86_64/bin:$PATH"
routeproof --version
routeproof validate routeproof-0.1.0-linux-x86_64/share/routeproof/examples/input/valid/diamond.yaml
```

On macOS use `shasum -a 256 --check FILE.sha256` and the `darwin` archive. You can
move the extracted directory afterwards, or copy just `bin/routeproof` into a
directory on `PATH`. Examples, schemas and licenses live under
`share/routeproof`; documentation is under `share/doc/RouteProof`.

## Install from source

Building requires Git, CMake 3.25.2+, Ninja 1.11.1+, and a supported C++20 compiler:
GCC 12.5.0+, upstream Clang 18.1.8+, or Apple Clang 21.0.0+. CMake fetches the
pinned dependencies. Python 3.9+ is needed only when building the acceptance
tests or using the source workflow tools.

```sh
cmake -S . -B build/install -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF
cmake --build build/install --parallel 4
cmake --install build/install --prefix "$HOME/.local"
"$HOME/.local/bin/routeproof" --version
```

`--prefix` chooses the destination at installation time; `DESTDIR` staging and
the standard `CMAKE_INSTALL_BINDIR`, `CMAKE_INSTALL_DATADIR` and
`CMAKE_INSTALL_DOCDIR` settings are supported. Install rules copy the executable
and data, with no dependency headers, static libraries or development launcher.
Both the installed prefix and the executable can be relocated.

## Package and verify locally

```sh
cpack --config build/install/CPackConfig.cmake -B build/packages
python3 tests/installation/check_install.py --archive build/packages/routeproof-0.1.0-darwin-arm64.tar.gz
```

CPack names archives using the project version, system and architecture, and
produces a `.tar.gz.sha256` checksum alongside each archive. Use the filename
printed by CPack for your platform. The smoke check relocates the archive into a
path containing spaces and exercises native commands with no tools on `PATH`.
The release workflow also hides the entire source/build checkout while checking
both a staged installation and the extracted archive.

## Source launcher and benchmarks

The development launcher remains `python3 tools/run.py`; it builds the Release
executable incrementally before dispatching commands. `demo`, `test`, `frr` and
`bench` are source workflow tools. Run benchmarks with:

```sh
python3 tools/run.py bench --profile benchmarks/profiles/sparse-small.json --out results/bench
python3 tools/bench/run.py --binary /path/to/routeproof --profile benchmarks/profiles/sparse-small.json --out results/bench-other
```

The native `bench` command now prints these source-tool instructions and exits 2;
the Python harness is no longer embedded in the executable or installed. The
native `bench-sample` worker remains available without Python. Published
benchmark evidence still requires a Release build's CMake cache and source
provenance; testing an installed binary with `--allow-debug` is smoke-only. See
[benchmarks](benchmarks.md) for evidence requirements.
