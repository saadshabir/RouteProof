# v0.1.0-rc.1 native release verification

Validation date: **2026-10-07 (America/Toronto)**.

The non-Linux release preparation is verified against the packaged source.
**The full v0.1 release remains incomplete:** live Linux FRR image compatibility,
route agreement and clean rerun, plus authoritative Linux peak/boundary RSS,
still require Linux evidence. No final release tag or publication was created.

## Source artifact and integrity

The [source candidate](package/routeproof-0.1.0-rc.1-source.tar.gz) contains **537 files**:
code, tests, profiles, schemas, examples, docs, CI and historical evidence.
Its [manifest](package/manifest.json) records all file hashes, originating revision
and dirty state, explicit candidate status and open gates. The archive is rebuilt
byte-identically in two independent output directories
([determinism check](package-determinism.json)); its contents match the current
worktree ([package check](package-check.json)).

- Archive SHA-256: `a159e45f2785ded06c705fbe0b659d1a0142dfcb200c483f075a406455649dd4`.
- Packaged file-set SHA-256: `436395f66e4835f95bb2ff6f2b0d39ca594b1e3ee02bf13e2e5c3f9ad1152ead`.
- Benchmark code/harness input SHA-256: `c7884e137cd24bcb2eccaefb83cb8604ee01f390e2d4e9154de2032a27d18e27`.

[Package checksums](package/SHA256SUMS) protect the archive and manifest.
[Bundle checksums](artifact-sha256.txt) cover this index, selected raw receipts and
preserved failed attempts. `evidence/release` is excluded from the source archive
so source hashes do not recursively depend on verification output. These receipts
are delivered beside the source artifact. Reproduction instructions are in
[release.md](../../../docs/release.md).

## Fresh clean-source builds

The same verified archive was extracted into two separate temporary source
snapshots and committed in local Git repositories. Both report empty Git status
before and after verification. The first builds all four configurations; the
second uses a distinct fresh Release build. All **11 CTest groups** pass in every
configuration, including input limits/regressions, independent routing/replay
oracles, generated graphs, witnesses, offline FRR, benchmark contracts and the
four new package/demo checks.

| Fresh configuration | Tested compiler | Acceptance evidence |
| --- | --- | --- |
| Release | Apple Clang 21.0.0 | [11 groups pass](first/host-release-tests.txt) |
| GCC Debug | GCC 12.5.0 | [11 groups pass](first/gcc-debug-tests.txt) |
| Clang Debug | Upstream Clang 18.1.8 | [11 groups pass](first/clang-debug-tests.txt) |
| ASan/UBSan Debug | Apple Clang 21.0.0 | [11 groups pass](first/host-sanitizers-tests.txt) |
| Separate reproduction Release | Apple Clang 21.0.0 | [11 groups pass](reproduction/host-release-tests.txt) |

[First verification](first/verification.json) and
[second verification](reproduction/verification.json) retain exact command vectors,
log names, source commits, clean state, platform and dependency reuse. Sanitizer
runs halt on errors; macOS LeakSanitizer is disabled because that platform does not
support it. Timings use the unsanitized Release builds.

The verified-clean dependency caches are reused explicitly at their pinned tags:
yaml-cpp 0.9.0 (`56e3bb550c91fd7005566f19c079cb7a503223cf`), nlohmann/json 3.12.0
(`55f93686c01528224f448c19128836e7df245f72`), and PicoSHA2 1.0.1
(`161cb3fc4170fa7a3eca9e582cebd27cc4d1fe29`). They are not vendored or reacquired;
all application and dependency build outputs are freshly compiled.

## Demo and benchmark reproduction

The [checked diamond](first/host-release-diamond/report.json) matches all six
snapshots: two baseline ECMP links, one surviving branch, a partition, recovery,
origin failure, and restoration preserving `cd`'s administrative failure.
`simulate` and `explain` deliberately exit 1; the runner exits 0 after checking
those expected failures and repeated canonical bytes. [Explanation output](first/host-release-diamond/explain.stdout.txt)
contains the recorded partition and destination-down witnesses. GCC, upstream
Clang and sanitizer demo files have the same SHA-256 as the Release demo:
`c6e0a1be719af6c47b802e2f536b8c7357abcca0aa15e5c2f1f20c24b02fb7d0`.

Each clean Release snapshot runs the frozen `sparse-small-16` profile with one
warmup and five fresh measured processes per mode. The [raw first samples](first/bench-small/summary.json)
and [raw reproduction samples](reproduction/bench-small/summary.json) retain
commands, inputs, outputs, timing/RSS samples and host/build provenance.
[The strict comparison](reproduction-comparison.json) passes with equal source,
harness, dependencies, scenario and canonical hashes, reconciled counters and
clean reproduction checkouts. Result-file SHA-256 is
`ff773b89a3298cc37f4d036a990abe6ae924c42b90eee78f66f81d9e09f35f2a`. Timing equality is not required and no
performance regression threshold is claimed; native RSS remains provisional.

Both snapshots generate all five offline FRR profiles/six scenarios and 27
requested snapshots. The [first matrix report](first/frr-generated/matrix-report.json)
and [second report](reproduction/frr-generated/matrix-report.json) explicitly say
`skipped`, with zero live observed/matched slots. Generation exits 3 as expected;
it does not satisfy live FRR acceptance.

## CI and corrected failures

The [workflow](../../../.github/workflows/ci.yml) declares Linux GCC/Clang and native
macOS Clang builds, separate sanitizer/generated-corpus checks, a Release
benchmark/demo smoke run and checksummed source artifacts. [Actionlint 1.7.11](workflow-lint.json)
passes on this workflow. Hosted GitHub jobs have **not** been executed by this local
verification; CI timings are smoke evidence only.

Two failed preparatory attempts are retained and excluded from passing evidence:

- [Initial GCC test failure](initial-attempt/first/gcc-debug-tests.txt): the
  interruption test included unrelated host-provenance discovery in its eight-second
  worker-start deadline. The corrected test replaces only that discovery inside an
  isolated subprocess, retaining real CLI signal handling, checkpointing and worker
  reaping. [Targeted regression](interruption-regression.json) and all five current
  CTest runs pass.
- [Compiler-driver failure](compiler-driver-attempt/first/clang-debug-build.txt): the
  initial verifier resolved `clang++` to `clang`, omitting C++ runtime linkage. It now
  preserves the compiler's invocation name. The current fresh Clang build and all
  checks pass; historical source packages remain available beside those failed logs.

[Commands](commands.txt) record package creation, source reconstruction,
verification, comparison and lint. Temporary snapshot/build paths in raw manifests
are provenance for these runs; the source archive permits reconstruction without
those paths. The original repository was not committed, tagged or pushed.
