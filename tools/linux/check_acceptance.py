#!/usr/bin/env python3
"""Close Linux acceptance only with live FRR reproduction and raw Linux RSS."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def positive(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def memory_evidence(manifest, summary):
    if not manifest['host']['os_kernel'].startswith('Linux-'):
        raise ValueError('authoritative RSS requires recorded Linux host provenance')
    cell = next(cell for cell in summary['cells'] if cell['id'] == 'sparse-small-16')
    if cell['status'] != 'complete':
        raise ValueError('Linux memory workload must be complete')
    rows, peaks = [], []
    for mode in ('cli', 'instrumented'):
        samples = [sample for sample in cell['samples'] if sample['mode'] == mode]
        if sorted(sample['repetition'] for sample in samples) != list(range(5)):
            raise ValueError('Linux memory requires five distinct repetitions per mode')
        for sample in samples:
            peak = sample['process']['peak_rss_bytes']
            if not positive(peak):
                raise ValueError('missing Linux peak RSS')
            if mode == 'cli':
                peaks.append(peak)
                continue
            metrics = sample['metrics']
            if metrics['rss_platform'] != 'linux' or metrics['authoritative_memory'] is not True:
                raise ValueError('memory sample is not authoritative Linux RSS')
            if not positive(metrics['loaded_rss_bytes']) or not metrics['snapshots']:
                raise ValueError('missing Linux loaded/snapshot RSS')
            steady = []
            for snapshot in metrics['snapshots']:
                if not positive(snapshot['steady_rss_bytes']):
                    raise ValueError('missing Linux snapshot boundary RSS')
                steady.append({key: snapshot[key] for key in
                               ('id', 'steady_rss_bytes', 'route_entries', 'next_hop_references')})
            rows.append({'repetition': sample['repetition'], 'loaded_rss_bytes': metrics['loaded_rss_bytes'],
                         'instrumented_peak_rss_bytes': peak, 'snapshots': steady})
    return {'cell': cell['id'], 'dimensions': cell['dimensions'],
            'cli_peak_rss_bytes': peaks, 'instrumented_boundaries': rows}


def same_implementation(manifest, matrix):
    host = manifest['host']
    bench_source = host['source_inputs']['files']
    for cell in matrix['cells']:
        lab = cell['manifest']
        if (lab['git_revision'] != host['source_revision']
                or lab['binary_sha256'] != host['binary_sha256']
                or not {'CMakeLists.txt', 'CMakePresets.json', 'app/main.cpp'} <= lab['source_hashes'].keys() & bench_source.keys()
                or any(digest != bench_source[name] for name, digest in lab['source_hashes'].items()
                       if name in bench_source)):
            raise ValueError('FRR and memory must test the same source and binary')


def check(first, second, out):
    out.mkdir(parents=True, exist_ok=False)
    report = {'schema_version': 1, 'status': 'incomplete', 'acceptance_complete': False}
    try:
        commands = ([sys.executable, str(ROOT / 'tools/frr/compare_runs.py'),
                     str(first / 'frr/matrix-report.json'), str(second / 'frr/matrix-report.json'),
                     '--out', str(out / 'frr-reproduction.json')],
                    [sys.executable, str(ROOT / 'tools/bench/compare_runs.py'),
                     str(first / 'bench-small'), str(second / 'bench-small'), '--cell', 'sparse-small-16'])
        for name, argv in zip(('frr', 'benchmark'), commands):
            result = subprocess.run(argv, capture_output=True, text=True, timeout=120)
            (out / (name + '.stdout.txt')).write_text(result.stdout)
            (out / (name + '.stderr.txt')).write_text(result.stderr)
            if result.returncode != 0:
                raise ValueError(name + ' reproduction failed: ' + result.stdout + result.stderr)
            report[name + '_reproduction'] = json.loads(result.stdout)
        report['memory'] = []
        for directory in (first, second):
            manifest = json.loads((directory / 'bench-small/manifest.json').read_text())
            summary = json.loads((directory / 'bench-small/summary.json').read_text())
            matrix = json.loads((directory / 'frr/matrix-report.json').read_text())
            same_implementation(manifest, matrix)
            report['memory'].append(memory_evidence(manifest, summary))
        report.update(status='pass', acceptance_complete=True, open_gates=[])
        return 0
    except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError) as error:
        report['reason'] = str(error)
        print(str(error), file=sys.stderr)
        return 3
    finally:
        (out / 'acceptance.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first', type=Path, required=True)
    parser.add_argument('--second', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    return check(args.first.resolve(), args.second.resolve(), args.out.resolve())


if __name__ == '__main__':
    raise SystemExit(main())
