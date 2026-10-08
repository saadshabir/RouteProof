# v0.1.0 release evidence

**Status: completed.** All five implementation deliverables and release gates
pass. The [implementation plan](../../../docs/implementation-plan.md) and
[acceptance checklist](../../../docs/acceptance.md) are complete.

- Independent routing, deterministic replay and all-branch witness checks are
  documented in the [validation guide](../../../docs/validation.md).
- [Native release receipts](../v0.1.0-rc.1/README.md) preserve compiler floors,
  clean builds, the checked diamond, native scaling and separate source reproduction.
  Their frozen candidate metadata remains historical.
- [Linux acceptance](../linux/README.md) records two fresh complete matrices,
  tested FRR image/configuration/JSON compatibility, exact clean reproduction,
  and authoritative small-workload peak/loaded/snapshot RSS.
- [Hosted core checks](https://github.com/saadshabir/RouteProof/actions/runs/37726063505)
  pass Linux GCC/Clang, macOS Clang, ASan/UBSan and the Release demo/benchmark smoke job.

## Final source artifact

[The versioned source archive](https://github.com/saadshabir/RouteProof/releases/download/v0.1.0/routeproof-0.1.0-source.tar.gz)
has deterministic tar/gzip metadata and a complete per-file inventory in
[manifest.json](manifest.json). [SHA256SUMS](SHA256SUMS) covers the source archive,
manifest and [Linux acceptance receipt](linux-acceptance.json).
[The package integrity check](package-check.json) records the checked hashes.

The packager reruns strict raw Linux reproduction and RSS acceptance, then
matches every routing, lab and measurement implementation input to its tested
hash. The receipt records the exact Linux-tested revision; completion docs and
release packaging changed afterward. All packaged source bytes are separately
identified by the source manifest. Candidates cannot acquire final status merely
by changing a version string or declaring a pass.

Raw Linux captures are attached to the [v0.1.0 release](https://github.com/saadshabir/RouteProof/releases/tag/v0.1.0),
including the initial failed attempt. The companion evidence archive carries
`evidence/release` receipts referenced by the source documentation. After
extracting the source archive, extract that companion archive into the extracted
source root so relative evidence links resolve. Instructions and reproduction
commands are in [release.md](../../../docs/release.md).

Optional proof, transient convergence, protocol expansion, UI and optimization
remain follow-up proposals outside the completed v0.1 scope.
