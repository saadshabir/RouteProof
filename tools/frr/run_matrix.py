#!/usr/bin/env python3
"""Run every frozen profile; preserve failed cells and aggregate denominators."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from generate import write_json

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--image')
    parser.add_argument('--routeproof', default=str(ROOT / 'build/host-debug/routeproof'))
    parser.add_argument('--generate-only', action='store_true')
    args = parser.parse_args()
    if not args.image and not args.generate_only:
        parser.error('live runs require --image repository@sha256:digest')
    try:
        args.out.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error(f'output directory must be fresh: {error}')
    matrix = json.loads((ROOT / 'labs/profiles/matrix.json').read_text())
    cells = []
    for profile in matrix['profiles']:
        for scenario in profile['scenarios']:
            output = args.out / Path(scenario).stem
            argv = [sys.executable, str(ROOT / 'tools/frr/run_lab.py'), '--scenario', str(ROOT / scenario),
                    '--out', str(output), '--routeproof', args.routeproof]
            if args.image:
                argv.extend(['--image', args.image])
            if args.generate_only:
                argv.append('--generate-only')
            process = None
            manifest = None
            interrupted = False
            try:
                process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout, stderr = process.communicate(timeout=7200)
                result = json.loads((output / 'report.json').read_text()) if (output / 'report.json').exists() else {
                    'status': 'incomplete', 'error': 'runner failed without a report'}
                if (output / 'manifest.json').exists():
                    manifest = json.loads((output / 'manifest.json').read_text())
                elif result.get('status') == 'pass':
                    result = {**result, 'status': 'incomplete', 'error': 'passing runner omitted its provenance manifest'}
                code = process.returncode
            except (subprocess.TimeoutExpired, KeyboardInterrupt, OSError, ValueError) as error:
                # Terminate gracefully so the child runs its finally/cleanup path.
                # If it does not exit, retain an explicit unknown-cleanup failure.
                interrupted = isinstance(error, KeyboardInterrupt)
                stdout, stderr = '', ''
                cleanup = 'unknown'
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        stdout, stderr = process.communicate(timeout=180)
                        cleanup = 'see child report'
                    except subprocess.TimeoutExpired:
                        process.kill()
                        stdout, stderr = process.communicate()
                result, code = {'status': 'incomplete', 'error': str(error) or 'interrupted', 'cleanup': cleanup}, 3
            cells.append({'profile': profile['id'], 'scenario': scenario, 'argv': argv,
                          'exit_code': code, 'stdout': stdout, 'stderr': stderr,
                          'manifest': manifest, 'report': result})
            write_json(args.out / 'matrix-report.json', summary(cells, len(matrix['profiles']),
                       sum(len(p['scenarios']) for p in matrix['profiles'])))
            if interrupted:
                return 3
    result = summary(cells, len(matrix['profiles']), sum(len(p['scenarios']) for p in matrix['profiles']))
    print(json.dumps({key: result[key] for key in ('status', 'passing_snapshots', 'comparison_slots', 'matched_slots')}))
    return {'pass': 0, 'fail': 1, 'incomplete': 3, 'skipped': 3}[result['status']]


def summary(cells, profiles, requested):
    statuses = {c['report']['status'] for c in cells}
    status = 'incomplete' if statuses & {'incomplete', 'invalid'} or len(cells) != requested else (
        'skipped' if 'skipped' in statuses else 'fail' if 'fail' in statuses else 'pass')
    return {'schema_version': 1, 'status': status, 'profile_count': profiles,
            'requested_scenarios': requested, 'completed_scenarios': len(cells), 'cells': cells,
            **{key: sum(c['report'].get(key, 0) for c in cells) for key in
               ('requested_snapshots', 'completed_snapshots', 'passing_snapshots', 'comparison_slots', 'matched_slots')}}


if __name__ == '__main__':
    sys.exit(main())
