#!/usr/bin/env python3
"""Validate raw sample provenance and semantic reproduction for one workload."""
import argparse
import hashlib
import json
import statistics
from pathlib import Path
from generate import estimates, generate


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_run(root, cell_id):
    manifest = read(root / 'manifest.json')
    summary = read(root / 'summary.json')
    cell = next(x for x in summary['cells'] if x['id'] == cell_id)
    if cell['status'] != 'complete':
        raise ValueError('workload is not complete')
    profile = manifest['profile']
    config = next(x for x in profile['cells'] if x['id'] == cell_id)
    scenario = read(root / cell_id / 'scenario.json')
    if cell['config'] != config or scenario != generate(config) or cell['dimensions'] != estimates(scenario):
        raise ValueError('workload configuration/dimensions mismatch')
    if manifest['host']['source_inputs'] is None:
        raise ValueError('binary source provenance is unavailable')
    if manifest['host']['build_cache'].get('CMAKE_BUILD_TYPE') != 'Release' or 'sanitize' in json.dumps(manifest['host']['build_cache']):
        raise ValueError('measurement build is not unsanitized Release')
    if profile['repetitions'] < 5 or profile['warmups'] < 1:
        raise ValueError('insufficient sample policy')
    source = root / cell_id
    if (digest(source / 'scenario.json') != cell['input_file_sha256'] or
            digest(source / 'normalized.json') != cell['normalized_file_sha256']):
        raise ValueError('archived input digest mismatch')
    result_path = source / 'instrumented-000/output/result.json'
    canonical = read(result_path)
    if canonical['status'] not in ('pass', 'fail') or canonical['scenario_sha256'] != cell['scenario_sha256']:
        raise ValueError('incomplete/mismatched canonical result')
    if (len(canonical['snapshots']) != cell['dimensions']['events'] + 1 or
            len(canonical['events']) != cell['dimensions']['events']):
        raise ValueError('incomplete canonical snapshot coverage')
    assertions_by_snapshot = {x['id']: [] for x in canonical['snapshots']}
    for assertion in canonical['assertions']:
        assertions_by_snapshot[assertion['snapshot_id']].append(assertion)
    expected_snapshots = []
    for index, snapshot in enumerate(canonical['snapshots']):
        assertions = assertions_by_snapshot[snapshot['id']]
        expected_snapshots.append({
            'id': snapshot['id'],
            'applied': index > 0 and canonical['events'][index - 1]['disposition'] == 'applied',
            'route_entries': len(snapshot['routes']),
            'next_hop_references': sum(len(x['next_hops']) for x in snapshot['routes']),
            'assertion_evaluations': len(assertions),
            'destination_analyses': cell['dimensions']['analyzed_destinations'],
            'failed_assertions': sum(x['status'] == 'fail' for x in assertions),
            'incomplete_assertions': sum(x['status'] == 'incomplete' for x in assertions),
            'available_routers': len(snapshot['available_routers']),
            'retained_snapshots': index,
            'max_ecmp_width': max((len(x['next_hops']) for x in snapshot['routes']), default=0)})
    expected_counters = {
        'baseline_routes': expected_snapshots[0]['route_entries'],
        'baseline_next_hops': expected_snapshots[0]['next_hop_references'],
        'route_range': [min(x['route_entries'] for x in expected_snapshots), max(x['route_entries'] for x in expected_snapshots)],
        'next_hop_range': [min(x['next_hop_references'] for x in expected_snapshots), max(x['next_hop_references'] for x in expected_snapshots)],
        'applied_events': sum(x['applied'] for x in expected_snapshots[1:]),
        'noop_events': sum(not x['applied'] for x in expected_snapshots[1:]),
        'assertion_evaluations': sum(x['assertion_evaluations'] for x in expected_snapshots),
        'destination_analyses': sum(x['destination_analyses'] for x in expected_snapshots),
        'max_ecmp_width': max(x['max_ecmp_width'] for x in expected_snapshots)}
    if cell['counters'] != expected_counters:
        raise ValueError('counters do not trace to canonical snapshots')
    hashes = set()
    for category, count in [('samples', profile['repetitions']), ('warmups', profile['warmups'])]:
        records = cell[category]
        if len(records) != count * 2:
            raise ValueError('missing samples')
        identities = set()
        for record in records:
            mode, rep = record['mode'], record['repetition']
            if mode not in ('instrumented', 'cli') or (mode, rep) in identities:
                raise ValueError('duplicate/unsupported sample')
            expected = range(count) if category == 'samples' else range(-count, 0)
            if rep not in expected:
                raise ValueError('sample index outside declared range')
            identities.add((mode, rep))
            label = f'{mode}-' + (f'warmup{-rep}' if rep < 0 else f'{rep:03d}')
            path = source / label
            raw = read(path / 'process.json')
            if raw != record['process'] or raw['status'] != 'complete' or raw['exit_code'] not in (0, 1):
                raise ValueError('raw process record mismatch/incomplete')
            if (raw['elapsed_ns'] > profile['budgets']['timeout_seconds'] * 1e9 or
                    raw['peak_rss_bytes'] > profile['budgets']['memory_mib'] * 1024**2):
                raise ValueError('completed process exceeds its declared budget')
            hashes.add(record['result_file_sha256'])
            run = read(path / 'output/run.json')
            if run['result_sha256'] != record['result_sha256'] or run['scenario_sha256'] != cell['scenario_sha256']:
                raise ValueError('raw run digest mismatch')
            if (run['simulation_ns'] != record['simulation_ns'] or run['status'] != canonical['status'] or
                    run['result_sha256'] != canonical['canonical_sha256'] or
                    not 0 < run['simulation_ns'] <= raw['elapsed_ns']):
                raise ValueError('raw simulation timing/status mismatch')
            if mode == 'instrumented':
                metrics = read(path / 'output/sample.json')
                if metrics != record['metrics'] or metrics['result_sha256'] != record['result_sha256']:
                    raise ValueError('raw metrics mismatch')
                if len(metrics['snapshots']) != cell['dimensions']['events'] + 1:
                    raise ValueError('incomplete snapshot coverage')
                if (metrics['simulation_ns'] != run['simulation_ns'] or metrics['scenario_sha256'] != cell['scenario_sha256'] or
                        metrics['status'] != run['status'] or
                        any(metrics[key] != cell['dimensions'][key] for key in
                            ('routers', 'physical_links', 'directed_arcs', 'prefixes', 'events', 'assertions', 'analyzed_destinations'))):
                    raise ValueError('metrics/run mismatch')
                for measured, expected in zip(metrics['snapshots'], expected_snapshots):
                    if any(measured[key] != value for key, value in expected.items()):
                        raise ValueError('snapshot counters do not trace to canonical result')
                if metrics['core_processing_ns'] != sum(x['processing_ns'] for x in metrics['snapshots']):
                    raise ValueError('core sample accounting mismatch')
                if metrics['core_processing_ns'] > metrics['simulation_ns'] or metrics['status'] == 'incomplete':
                    raise ValueError('incomplete/invalid core sample')
    if len(hashes) != 1 or digest(result_path) != cell['result_file_sha256'] or hashes != {cell['result_file_sha256']}:
        raise ValueError('canonical bytes differ')
    for key, values in [('core_ns', [x['metrics']['core_processing_ns'] for x in cell['samples'] if x['mode'] == 'instrumented']),
                        ('cli_ns', [x['process']['elapsed_ns'] for x in cell['samples'] if x['mode'] == 'cli']),
                        ('instrumented_simulation_ns', [x['simulation_ns'] for x in cell['samples'] if x['mode'] == 'instrumented']),
                        ('cli_simulation_ns', [x['simulation_ns'] for x in cell['samples'] if x['mode'] == 'cli']),
                        ('peak_rss_bytes', [x['process']['peak_rss_bytes'] for x in cell['samples'] if x['mode'] == 'cli'])]:
        median = statistics.median(values)
        expected = {'median': median, 'min': min(values), 'max': max(values),
                    'median_absolute_deviation': statistics.median(abs(x - median) for x in values)}
        if cell[key] != expected:
            raise ValueError('aggregate does not trace to raw samples: ' + key)
    ratio = cell['instrumented_simulation_ns']['median'] / cell['cli_simulation_ns']['median']
    if cell['instrumentation_median_ratio'] != ratio:
        raise ValueError('instrumentation ratio does not trace to raw samples')
    return manifest, cell


def compare(first, second, cell_id):
    a, ca = validate_run(first, cell_id)
    b, cb = validate_run(second, cell_id)
    if b['host']['git_status'] != '':
        raise ValueError('reproduction source checkout was dirty')
    for key in ('generator_version', 'prng_algorithm'):
        if a[key] != b[key]:
            raise ValueError('generator mismatch')
    if a['host']['source_inputs'] != b['host']['source_inputs']:
        raise ValueError('source-input hashes differ')
    if a['host']['dependencies'] != b['host']['dependencies']:
        raise ValueError('dependency revisions differ')
    harness_a, harness_b = a['host'].get('harness'), b['host'].get('harness')
    if harness_a is not None or harness_b is not None:
        if harness_a is None or harness_b is None or harness_a['source_inputs'] != harness_b['source_inputs']:
            raise ValueError('harness source-input hashes differ')
        if harness_b['git_status'] != '':
            raise ValueError('reproduction harness checkout was dirty')
    for key in ('config', 'dimensions', 'scenario_sha256', 'result_file_sha256', 'counters'):
        if ca[key] != cb[key]:
            raise ValueError('workload/result mismatch: ' + key)
    if a['host']['binary_path'] == b['host']['binary_path']:
        raise ValueError('reproduction did not use a distinct build')
    return {'status': 'pass', 'cell': cell_id, 'source_sha256': a['host']['source_inputs']['sha256'],
            'scenario_sha256': ca['scenario_sha256'], 'result_file_sha256': ca['result_file_sha256'],
            'original_core_ns': ca['core_ns'], 'reproduced_core_ns': cb['core_ns'],
            'original_cli_ns': ca['cli_ns'], 'reproduced_cli_ns': cb['cli_ns'],
            'timing_policy': 'descriptive comparison; no equality or regression threshold claimed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original', type=Path)
    parser.add_argument('reproduction', type=Path)
    parser.add_argument('--cell', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(compare(args.original, args.reproduction, args.cell), indent=2))
        return 0
    except (ValueError, OSError, KeyError, StopIteration) as error:
        print(json.dumps({'status': 'fail', 'reason': str(error)}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
