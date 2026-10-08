#!/usr/bin/env python3
"""Validate before/after benchmark receipts across a source optimization."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools' / 'bench'))
from compare_runs import read, validate_run


def compare(before, after):
    manifests = [read(root / 'manifest.json') for root in (before, after)]
    summaries = [read(root / 'summary.json') for root in (before, after)]
    a, b = manifests
    for key in ('profile', 'generator_version', 'prng_algorithm'):
        if a[key] != b[key]:
            raise ValueError('benchmark policy differs: ' + key)
    for key in ('compiler', 'build_cache', 'dependencies', 'cpu', 'ram', 'machine', 'os_kernel'):
        if a['host'][key] != b['host'][key]:
            raise ValueError('build/host differs: ' + key)
    # The production sources intentionally differ. The measurement harness must
    # be identical so a harness change cannot masquerade as an engine speedup.
    harness_files = []
    for manifest in manifests:
        files = manifest['host']['harness']['source_inputs']['files']
        harness_files.append({key: value for key, value in files.items()
                              if key.startswith('tools/bench/')})
    if harness_files[0] != harness_files[1]:
        raise ValueError('measurement harness differs')
    declared = [cell['id'] for cell in a['profile']['cells']]
    indexed = []
    for summary in summaries:
        cells = summary['cells']
        if len(cells) != len(declared) or {cell['id'] for cell in cells} != set(declared):
            raise ValueError('declared cell coverage differs')
        indexed.append({cell['id']: cell for cell in cells})
    completed, excluded = [], []
    for cell_id in declared:
        ca, cb = (cells[cell_id] for cells in indexed)
        for key in ('status', 'config', 'dimensions'):
            if ca[key] != cb[key]:
                raise ValueError(cell_id + ': workload/status differs: ' + key)
        if ca['status'] != 'complete':
            for key in ('reason', 'input_file_sha256', 'normalized_file_sha256', 'samples', 'warmups'):
                if ca[key] != cb[key]:
                    raise ValueError(cell_id + ': excluded probe differs: ' + key)
            excluded.append({key: ca[key] for key in ('id', 'status', 'reason', 'dimensions')})
            continue
        _, ca = validate_run(before, cell_id)
        _, cb = validate_run(after, cell_id)
        for key in ('scenario_sha256', 'input_file_sha256', 'normalized_file_sha256',
                    'result_file_sha256', 'counters'):
            if ca[key] != cb[key]:
                raise ValueError(cell_id + ': canonical workload/result differs: ' + key)
        row = {'id': cell_id, 'dimensions': ca['dimensions'],
               'result_file_sha256': ca['result_file_sha256']}
        for key in ('core_ns', 'cli_simulation_ns', 'cli_ns', 'peak_rss_bytes'):
            row[key] = {'before': ca[key], 'after': cb[key],
                        'median_reduction_percent': 100 * (1 - cb[key]['median'] / ca[key]['median'])}
        completed.append(row)
    return {'status': 'validated_comparison', 'sweep_status': 'partial' if excluded else 'complete',
            'baseline_revision': a['host']['source_revision'],
            'baseline_source_sha256': a['host']['source_inputs']['sha256'],
            'optimized_source_sha256': b['host']['source_inputs']['sha256'],
            'declared_cells': len(declared), 'completed_cells': len(completed),
            'excluded_cells': excluded, 'cells': completed,
            'policy': 'Five fresh processes per mode after one warmup; descriptive medians; '
                      'identical canonical bytes; no timing threshold or capacity claim. '
                      'macOS RSS is provisional.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = compare(args.before, args.after)
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
        print(f"Validated {result['completed_cells']} identical workloads; "
              f"{len(result['excluded_cells'])} excluded probes")
        return 0
    except (ValueError, OSError, KeyError, StopIteration) as error:
        print(str(error), file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
