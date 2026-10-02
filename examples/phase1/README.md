# Phase 1 input fixtures

`valid/` contains the diamond trace, a declaration-order equivalence pair,
an asymmetric parallel-link topology, and explicitly tagged YAML with a `/1`
attachment. The equivalence pair reorders multiple prefixes and assertions as
well as routers, links, and events. Both files must produce byte-identical output
and the same `scenario_sha256`. The physical-state fixture includes a `/32`
attachment and keeps router availability separate from link administrative state.

`invalid/` contains named inputs that must fail with exit code 2 and a field or
source location in the diagnostic. They cover duplicate YAML keys, unknown
fields, duplicate router IDs, unresolved endpoints, invalid costs, overlapping
and noncanonical prefixes, quoted strings in integer fields, event timestamp
ordering, custom tags, tags with unsupported names in the standard namespace,
mismatched collection tags, non-string mapping keys, default routes, and multiple
documents.

From the repository root, run:

```sh
cmake --preset host-debug
cmake --build --preset host-debug
ctest --test-dir build/host-debug --output-on-failure
build/host-debug/routeproof validate examples/phase1/valid/diamond.yaml
build/host-debug/routeproof validate examples/phase1/valid/equivalent-a.yaml --normalized
build/host-debug/routeproof validate examples/phase1/valid/equivalent-b.yaml --normalized
python3 tools/phase1/validate_fixtures.py
```

CTest runs the CLI fixtures and `routeproof_topology_check`, which loads the
physical-state fixture and inspects actual adjacency arcs, endpoint interfaces,
independent router/link state, and prefix ownership. The Python runner checks
normalized input data and hashes. Each file in `invalid/` must exit 2 with a source
location. These checks cover Phase 1; routing and reachability belong to later phases.

`routeproof_input_limits_check` checks exact parser-budget boundaries and source
marks. `tools/phase1/validate_regressions.py` generates temporary JSON/YAML inputs
to cover Unicode escapes, safe CLI output, duplicate decoded keys, strict JSON,
nonrecursive aliases, prefix boundaries, bounded reads, and larger event lists.
