# Replay review fixes

Validated October 5, 2026, on macOS arm64, using the toolchains recorded in [toolchains.json](toolchains.json).

- `validate_witness` bounds `cycle_entry` without adding to an unchecked index. The integration test rejects a missing entry, the closing terminal index, an index past the path, and `SIZE_MAX`; valid cycles still validate.
- `explain` checks every assertion's status against its findings and a complete result's status against all assertion outcomes. Finding assertion/scenario/snapshot/event references and terminal reasons are checked even for assertions outside the selected ID. Contradictory results return 2 without displaying an explanation.
- Incomplete results require a nonempty reason and nonnegative integer completed/requested snapshot counts. Completed counts must match retained snapshots, requested counts must be positive, and completed counts cannot exceed requested counts. The result schema requires all three diagnostic fields, and simulation supplies them for every incomplete result.

The Python replay reference now reseals malformed results with valid digests before checking rejection, so status/reference/coverage checks are exercised independently of digest errors. Cases cover contradictory run/record/finding statuses, invalid finding references and reasons, empty complete results, omitted diagnostics, malformed or overflowing coverage counts, and legitimate incomplete results with zero snapshots or a retained failing prefix.

| Build | Checks | Log |
| --- | --- | --- |
| Apple Clang 21.0.0 | 8/8 pass | [review-host.txt](review-host.txt) |
| GCC 12.5.0 | 8/8 pass | [review-gcc.txt](review-gcc.txt) |
| Clang 18.1.8 | 8/8 pass | [review-clang.txt](review-clang.txt) |
| Apple Clang 21.0.0, ASan + UBSan | 8/8 pass, no sanitizer findings | [review-sanitizers.txt](review-sanitizers.txt) |

Each log includes the build and verbose CTest commands and exit codes. The 42-trace replay corpus still contains 373 snapshots and 4,830 failed assertion records. All three compiler builds retain the original canonical corpus SHA-256:

```text
54d3222c07f6a1bc7fc3671d256cca71262c1397ffe4d36d432ad9f5909fec0c
```

[review-fix-inputs.sha256](review-fix-inputs.sha256) records the current source/docs/fixture hashes after these fixes, excluding evidence and generated files. The initial replay logs and source manifest are preserved in [replay-validation.md](replay-validation.md). These follow-up checks use rebuilt existing build directories; the original fresh-copy checks are not claimed as rerun after the fixes.
