#!/usr/bin/env python3
"""Check that two complete live matrices reproduce the declared agreement."""
import argparse
import json
import re
import sys
from pathlib import Path
from generate import FRR_VERSION, check_image


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def live_manifest(cell, clean):
    manifest = cell.get('manifest')
    require(isinstance(manifest, dict), 'cell is missing its live provenance manifest; regenerate the matrix')
    require(manifest.get('schema_version') == 1 and manifest.get('mode') == 'live'
            and manifest.get('platform') == 'linux/amd64' and manifest.get('frr_version') == FRR_VERSION
            and manifest.get('image_pin_status') == 'provided_digest', 'cell does not have supported live provenance')
    check_image(manifest['image'])
    require(re.fullmatch(r'rp-[a-z0-9-]{1,40}', manifest.get('lab_name', '')) is not None,
            'cell is missing its run-owned lab identity')
    require(isinstance(manifest.get('git_revision'), str)
            and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', manifest['git_revision']) is not None,
            'cell is missing its source revision')
    require(isinstance(manifest.get('git_status'), str), 'cell is missing checkout cleanliness')
    require(not clean or manifest['git_status'] == '', 'reproduction run must use a clean checkout')
    for key in ('source_root', 'binary_path'):
        require(isinstance(manifest.get(key), str) and Path(manifest[key]).is_absolute(),
                f'cell is missing its absolute {key}')
    for key in ('scenario_sha256', 'result_sha256', 'binary_sha256'):
        require(digest(manifest.get(key)), f'cell is missing its {key}')
    for key in ('source_hashes', 'generated_hashes'):
        hashes = manifest.get(key)
        require(isinstance(hashes, dict) and bool(hashes)
                and all(isinstance(path, str) and digest(value) for path, value in hashes.items()),
                f'cell is missing its {key}')
    environment = cell['report'].get('environment')
    require(isinstance(environment, dict) and environment.get('system') == 'Linux'
            and environment.get('architecture') in ('amd64', 'x86_64')
            and bool(environment.get('kernel')) and bool(environment.get('containerlab'))
            and isinstance(environment.get('docker'), dict) and bool(environment['docker'].get('Server')),
            'cell is missing its recorded Linux lab environment')
    image = environment.get('image')
    require(isinstance(image, dict) and image.get('Architecture') == 'amd64' and image.get('Os') == 'linux'
            and manifest['image'] in image.get('RepoDigests', []), 'cell image inspection does not confirm its pin')
    return manifest


def semantic_report(report, clean=False):
    require(isinstance(report, dict), 'matrix report must be an object')
    if report.get('status') != 'pass':
        raise ValueError('rerun gate requires complete passing LIVE matrices; skipped/incomplete/failed is not agreement')
    if (report.get('profile_count'), report.get('requested_scenarios'), report.get('completed_scenarios'),
        report.get('requested_snapshots'), report.get('completed_snapshots'), report.get('passing_snapshots'),
        report.get('comparison_slots'), report.get('matched_slots')) != (5, 6, 6, 27, 27, 27, 687, 687):
        raise ValueError('matrix does not cover the frozen Phase 4 domain')
    cells = []
    manifests = {}
    source = None
    labs = set()
    require(isinstance(report.get('cells'), list), 'matrix cells must be a list')
    for cell in report['cells']:
        require(isinstance(cell, dict) and isinstance(cell.get('report'), dict), 'invalid matrix cell/report')
        value = cell['report']
        if value['status'] != 'pass' or cell['exit_code'] != 0 or value['cleanup'] != 'complete':
            raise ValueError('cell is not a complete clean live pass')
        manifest = live_manifest(cell, clean)
        require(manifest['lab_name'] not in labs, 'matrix reuses a lab identity')
        labs.add(manifest['lab_name'])
        current_source = {key: manifest[key] for key in
                          ('source_hashes', 'git_revision', 'git_status', 'source_root', 'binary_path', 'binary_sha256', 'image')}
        require(source is None or source == current_source, 'source, binary, checkout, or image changed during the matrix')
        source = current_source
        require(isinstance(value.get('snapshots'), list)
                and all(isinstance(snapshot, dict) for snapshot in value['snapshots']), 'cell snapshots must be objects')
        require(value['requested_snapshots'] == value['completed_snapshots'] == value['passing_snapshots']
                == len(value['snapshots']), 'cell snapshot coverage is inconsistent')
        require(value['comparison_slots'] == value['matched_slots']
                == sum(s['comparison_slots'] for s in value['snapshots']), 'cell route-slot coverage is inconsistent')
        snapshot_ids = set()
        for snapshot in value['snapshots']:
            require(snapshot['status'] == 'pass' and not snapshot['mismatches']
                    and snapshot['matched_slots'] == snapshot['comparison_slots']
                    and snapshot['snapshot_id'] not in snapshot_ids and digest(snapshot['snapshot_sha256']),
                    'cell has incomplete, duplicate, or failed snapshot evidence')
            snapshot_ids.add(snapshot['snapshot_id'])
        snapshots = [{key: s[key] for key in ('snapshot_id', 'snapshot_sha256', 'status', 'matched_slots',
                                              'comparison_slots', 'unavailable_routers', 'mismatches')}
                     for s in value['snapshots']]
        cells.append({'profile': cell['profile'], 'scenario': cell['scenario'], 'snapshots': snapshots})
        manifests[cell['profile'], cell['scenario']] = manifest
    identities = [(cell['profile'], cell['scenario']) for cell in cells]
    matrix = json.loads((Path(__file__).resolve().parents[2] / 'labs/profiles/matrix.json').read_text())
    declared = [(profile['id'], scenario) for profile in matrix['profiles'] for scenario in profile['scenarios']]
    if sorted(identities) != sorted(declared):
        raise ValueError('missing/duplicate/extra matrix cells')
    for key in ('requested_snapshots', 'completed_snapshots', 'passing_snapshots', 'comparison_slots', 'matched_slots'):
        require(report[key] == sum(cell['report'][key] for cell in report['cells']),
                f'matrix {key} does not match its cell evidence')
    return sorted(cells, key=lambda c: (c['profile'], c['scenario'])), manifests


def compare_runs(first, second):
    try:
        left, first_manifests = semantic_report(first)
        right, second_manifests = semantic_report(second, clean=True)
        require(not {m['lab_name'] for m in first_manifests.values()}
                & {m['lab_name'] for m in second_manifests.values()}, 'rerun gate requires two distinct fresh lab matrices')
        for identity, manifest in first_manifests.items():
            rerun = second_manifests[identity]
            require(manifest['image'] == rerun['image'] and manifest['source_hashes'] == rerun['source_hashes'],
                    'rerun must reproduce the same source inputs and image digest')
        same_inputs = all(first_manifests[key]['scenario_sha256'] == second_manifests[key]['scenario_sha256']
                          and first_manifests[key]['result_sha256'] == second_manifests[key]['result_sha256']
                          for key in first_manifests)
        return {'schema_version': 1, 'status': 'pass' if left == right and same_inputs else 'fail',
                'reason': 'exact semantic reproduction from fresh labs and a clean checkout' if left == right and same_inputs
                          else 'scenario/result hashes or snapshot comparisons differ',
                'snapshots': 27, 'comparison_slots': 687}
    except (ValueError, KeyError, TypeError) as error:
        return {'schema_version': 1, 'status': 'incomplete', 'reason': str(error)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('first', type=Path, help='first matrix-report.json')
    parser.add_argument('second', type=Path, help='second matrix-report.json')
    parser.add_argument('--out', type=Path, help='optional fresh rerun report file')
    args = parser.parse_args()
    try:
        result = compare_runs(json.loads(args.first.read_text()), json.loads(args.second.read_text()))
        if args.out:
            # Exclusive creation preserves prior evidence even on partial writes.
            with args.out.open('x', encoding='utf-8') as stream:
                stream.write(json.dumps(result, indent=2, sort_keys=True) + '\n')
        print(json.dumps(result, sort_keys=True))
        return {'pass': 0, 'fail': 1, 'incomplete': 3}[result['status']]
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 3


if __name__ == '__main__':
    sys.exit(main())
