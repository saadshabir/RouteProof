# Release preparation

The current package is **0.1.0-rc.1**, a source candidate. The routing core reports
`0.1.0`; the artifact filename and manifest carry the candidate suffix. This does
not close live Linux FRR or authoritative Linux RSS acceptance, create a Git tag,
or publish a release. Those gates remain explicit in [acceptance.md](acceptance.md).

## Continuous checks

[ci.yml](../.github/workflows/ci.yml) runs on push, pull request and manual dispatch:

- Linux GCC and upstream Clang, and native macOS upstream Clang builds run all
  CTest groups, including parser limits, independent routing/replay oracles,
  generated tiny graphs, witnesses, offline FRR, benchmarks and release artifacts.
- A separate Clang ASan/UBSan build runs the same corpus with sanitizer failures
  configured to stop the process.
- A fresh Release job checks the diamond, collects the frozen small workload,
  generates the offline FRR matrix and builds/checks a source candidate.
- [Linux acceptance](../.github/workflows/linux-acceptance.yml) separately runs
  privileged live FRR labs, clean-source reproduction and authoritative Linux RSS.
  It can be dispatched from GitHub without installing Linux locally.

Actions are pinned to reviewed commits; job permissions are read-only and checkout
credentials are not retained. Test logs and Release artifacts are uploaded even
after failure. Smoke timing is harness verification, not a performance claim.
The runner compiler versions are above the documented floors; local evidence
separately covers GCC 12.5.0 and Clang 18.1.8. Live privileged FRR CI is still Linux
acceptance work until its live workflow passes. The workflow implementation follows GitHub's
[workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).

## Source artifact

Use a fresh output directory from the repository root. The source must contain
the required project/build files. Output under packaged source directories is
rejected; `results`, `build`, an external directory, and the excluded
`evidence/release` subtree are valid destinations:

```sh
python3 tools/release/package.py --version 0.1.0-rc.1 --out results/package-rc1
python3 tools/release/package.py --check --out results/package-rc1
```

The output has a deterministic `routeproof-0.1.0-rc.1-source.tar.gz`, `manifest.json`
with every source file's SHA-256, and `SHA256SUMS`. Tar metadata/order and gzip
timestamps are fixed. The checker validates the candidate version and rejects
changed bytes, unsafe or noncanonical paths, duplicate entries, missing project files
and a mismatched file inventory. The package includes code, tests, profiles,
schemas, examples, docs, CI and historical evidence from earlier phases. Build/results, Git
metadata, local presets, Python caches and `evidence/release` are excluded. Candidate
receipts are delivered beside the package to avoid recursive source/evidence
hashes. Dependencies are fetched from the CMake pins, rather than vendored.

The `release-smoke` CI download preserves repository-relative paths under
`results/ci-package`, `results/ci-release`, and `evidence/release/v0.1.0-rc.1`.
The last directory contains the native candidate receipts referenced by the
packaged docs; the CI smoke logs are separate evidence. Keep those companion
receipts when sharing the source candidate. After extracting the source, copy
the companion `evidence/release` directory into the extracted tree's `evidence`
directory so the documentation links resolve. The commands below include that
copy before creating the clean Git snapshot. With a CI download, use
`results/ci-package` in place of `results/package-rc1`.

The manifest records the originating revision and dirty state; hashes identify
the actual packaged bytes even if the work is not committed yet. Candidate-only
version validation prevents this tool from labelling the unfinished gates as a
final `0.1.0` release. The archive is source-only; `bench` needs the source checkout,
Python harness and adjacent CMake cache, so a copied executable alone is insufficient.

## Fresh verification and reproduction

Extract the checked archive into a new directory, initialize a clean local source
snapshot and verify it. The temporary Git commit records the extracted source;
it does not modify the original repository.

```sh
mkdir -p results/extracted
tar -xzf results/package-rc1/routeproof-0.1.0-rc.1-source.tar.gz -C results/extracted
cp -R evidence/release results/extracted/routeproof-0.1.0-rc.1/evidence/
git -C results/extracted/routeproof-0.1.0-rc.1 init --quiet
git -C results/extracted/routeproof-0.1.0-rc.1 add .
git -C results/extracted/routeproof-0.1.0-rc.1 -c user.name='RouteProof candidate' -c user.email=candidate@routeproof.local commit --quiet -m 'Frozen source candidate'
python3 results/extracted/routeproof-0.1.0-rc.1/tools/release/verify.py \
  --out results/verify-first --gcc-cxx /path/to/g++ --clang-cxx /path/to/clang++ --sanitizers
```

`verify.py` refuses dirty checkouts and existing build/output directories, builds
Release plus the requested compiler/sanitizer presets, runs every CTest group,
checks diamond bytes across toolchains, runs the five-repetition small workload,
and generates the offline FRR matrix with explicit `skipped` status. It writes
individual command logs and `verification.json`, including failures. Optional
`--dependency-cache /path/to/build/_deps` reuses verified-clean dependency Git
sources and records their commits; omitting it fetches pinned dependencies.

Extract the same archive into a second clean snapshot and run `verify.py` with a
distinct output path there. Compare its benchmark using the existing raw-evidence
validator:

```sh
python3 tools/bench/compare_runs.py results/verify-first/bench-small \
  results/verify-second/bench-small --cell sparse-small-16
```

Both runs must have equal source/harness/workload/dependency hashes, identical
canonical results and reconciled raw counters. The reproduction must use a clean
checkout and distinct binary. Timing equality is not required. Selected current
source, commands, logs, demo and benchmark receipts are indexed in
[candidate evidence](../evidence/release/v0.1.0-rc.1/README.md).

After the Linux gates pass, refresh the final-source evidence and checklist,
prepare final versioned artifacts, and tag/publish v0.1. No optional proof, UI,
protocol expansion or optimization is required for that release.
