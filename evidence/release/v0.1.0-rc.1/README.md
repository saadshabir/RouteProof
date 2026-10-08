# v0.1.0-rc.1 native release verification

Validation date: **2026-10-07 (America/Toronto)**.

The archived native release preparation is verified against its packaged source.
That frozen snapshot predates the subsequently added hosted Linux acceptance
workflow; its file hashes identify the exact native source tested here.
**Historical candidate:** the full release was incomplete when these native
receipts were collected. [Linux acceptance](../linux/README.md) now closes live
FRR image compatibility, matrix agreement, clean reproduction and authoritative
small-workload RSS. The final source artifact is indexed in [v0.1.0 evidence](../v0.1.0/README.md).
The frozen candidate manifest retains the gates that were open at its collection time.

## Source artifact and integrity

The [source candidate](package/routeproof-0.1.0-rc.1-source.tar.gz) contains **537 files**:
code, tests, profiles, schemas, examples, docs, CI and historical evidence.
Its [manifest](package/manifest.json) records all file hashes, originating revision
and dirty state, explicit candidate status and open gates. The archive is rebuilt
byte-identically in two independent output directories
([determinism check](package-determinism.json)); its contents match the frozen
native verification snapshot ([package check](package-check.json)).

- Archive SHA-256: `6e6390d96443d038f1d88778315106a97c2c07f5c6233cc4dc46f4449836e0f5`.
- Packaged file-set SHA-256: `9ade3021040b653b02cc202cc5ff9e4fef797fcc0a985ccf3631b30defc86d9b`.
- Benchmark code/harness input SHA-256: `665eac4220a5eb90bba2ab0b926051b4d0eef8df2ac2987682ab8214598b2665`.

[Package checksums](package/SHA256SUMS) protect the archive and manifest.
[Bundle checksums](artifact-sha256.txt) cover this index, selected raw receipts and
preserved failed attempts. `evidence/release` is excluded from the source archive
so source hashes do not recursively depend on verification output. These receipts
are included in the CI download beside the source artifact. Copy the companion
`evidence/release` directory into the extracted source before initializing its
Git snapshot so the packaged documentation links resolve. Reproduction instructions are in
[release.md](../../../docs/release.md).

## Fresh clean-source builds

The same verified archive was extracted into two separate temporary source
snapshots and committed in local Git repositories. Both report empty Git status
before and after verification. The first builds all four configurations; the
second uses a distinct fresh Release build. All **11 CTest groups** pass in every
configuration, including input limits/regressions, independent routing/replay
oracles, generated graphs, witnesses, offline FRR, benchmark contracts and the
seven package/demo checks, including the packaging regressions below.

| Fresh configuration | Tested compiler | Acceptance evidence |
| --- | --- | --- |
| Release | Apple Clang 21.0.0 | [11 groups pass](review-fixes/first/host-release-tests.txt) |
| GCC Debug | GCC 12.5.0 | [11 groups pass](review-fixes/first/gcc-debug-tests.txt) |
| Clang Debug | Upstream Clang 18.1.8 | [11 groups pass](review-fixes/first/clang-debug-tests.txt) |
| ASan/UBSan Debug | Apple Clang 21.0.0 | [11 groups pass](review-fixes/first/host-sanitizers-tests.txt) |
| Separate reproduction Release | Apple Clang 21.0.0 | [11 groups pass](review-fixes/reproduction/host-release-tests.txt) |

[First verification](review-fixes/first/verification.json) and
[second verification](review-fixes/reproduction/verification.json) retain exact command vectors,
log names, source commits, clean state, platform and dependency reuse. Sanitizer
runs halt on errors; macOS LeakSanitizer is disabled because that platform does not
support it. Timings use the unsanitized Release builds.

The verified-clean dependency caches are reused explicitly at their pinned tags:
yaml-cpp 0.9.0 (`56e3bb550c91fd7005566f19c079cb7a503223cf`), nlohmann/json 3.12.0
(`55f93686c01528224f448c19128836e7df245f72`), and PicoSHA2 1.0.1
(`161cb3fc4170fa7a3eca9e582cebd27cc4d1fe29`). They are not vendored or reacquired;
all application and dependency build outputs are freshly compiled.

## Demo and benchmark reproduction

The [checked diamond](review-fixes/first/host-release-diamond/report.json) matches all six
snapshots: two baseline ECMP links, one surviving branch, a partition, recovery,
origin failure, and restoration preserving `cd`'s administrative failure.
`simulate` and `explain` deliberately exit 1; the runner exits 0 after checking
those expected failures and repeated canonical bytes. [Explanation output](review-fixes/first/host-release-diamond/explain.stdout.txt)
contains the recorded partition and destination-down witnesses. GCC, upstream
Clang and sanitizer demo files have the same SHA-256 as the Release demo:
`c6e0a1be719af6c47b802e2f536b8c7357abcca0aa15e5c2f1f20c24b02fb7d0`.

Each clean Release snapshot runs the frozen `sparse-small-16` profile with one
warmup and five fresh measured processes per mode. The [raw first samples](review-fixes/first/bench-small/summary.json)
and [raw reproduction samples](review-fixes/reproduction/bench-small/summary.json) retain
commands, inputs, outputs, timing/RSS samples and host/build provenance.
[The strict comparison](reproduction-comparison.json) passes with equal source,
harness, dependencies, scenario and canonical hashes, reconciled counters and
clean reproduction checkouts. Result-file SHA-256 is
`ff773b89a3298cc37f4d036a990abe6ae924c42b90eee78f66f81d9e09f35f2a`. Timing equality is not required and no
performance regression threshold is claimed; native RSS remains provisional.

Both snapshots generate all five offline FRR profiles/six scenarios and 27
requested snapshots. The [first matrix report](review-fixes/first/frr-generated/matrix-report.json)
and [second report](review-fixes/reproduction/frr-generated/matrix-report.json) explicitly say
`skipped`, with zero live observed/matched slots. Generation exits 3 as expected;
it does not satisfy live FRR acceptance.

## CI and corrected failures

The [workflow](../../../.github/workflows/ci.yml) declares Linux GCC/Clang and native
macOS Clang builds, separate sanitizer/generated-corpus checks, a Release
benchmark/demo smoke run and checksummed source artifacts. [Actionlint 1.7.11](workflow-lint.json)
passes on this workflow. Hosted GitHub jobs have **not** been executed by this local
verification; CI timings are smoke evidence only.

The four review findings are corrected in the current candidate. Packaging now
rejects nonexistent/incomplete source trees and outputs inside packaged directories
before creating files. Checking validates candidate versions and complete canonical
member paths, including traversal and duplicate path aliases. The CI download
includes the native companion receipts; extraction/copy instructions restore the
evidence links. [Seven release checks](review-fixes/release-regressions.txt) and
[the delivered-layout audit](review-fixes/companion-layout.json) cover these changes.
The current source archive and all five fresh CTest runs were regenerated after
the fixes. The [pre-review source package](pre-review/package/manifest.json),
original `first`/`reproduction` logs and original comparison under `pre-review`
remain historical evidence for the superseded source.

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
