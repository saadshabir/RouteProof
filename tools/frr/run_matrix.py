#!/usr/bin/env python3
"""Run every frozen profile; preserve failed cells and aggregate denominators."""
import argparse
import json
import signal
import subprocess
import sys
from pathlib import Path
from generate import write_json

ROOT = Path(__file__).resolve().parents[2]


class TerminationSignals:
    """Interrupt the active wait once; defer later signals until evidence is saved."""
    def __init__(self):
        self.requested = False
        self.waiting = False
        self.previous = {}

    def handle(self, _signum, _frame):
        self.requested = True
        if self.waiting:
            self.waiting = False
            raise KeyboardInterrupt

    def __enter__(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            self.previous[signum] = signal.signal(signum, self.handle)
        return self

    def __exit__(self, *_exc):
        for signum, handler in self.previous.items():
            signal.signal(signum, handler)


def read_object(path):
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f'{path}: expected an evidence object')
    return value


def collect_cell(argv, output, timeout=7200, cleanup_timeout=180, termination=None):
    """Let interrupted children clean up, retaining their partial evidence."""
    if termination is None:
        with TerminationSignals() as termination:
            return collect_cell(argv, output, timeout, cleanup_timeout, termination)
    process = None
    stdout, stderr = '', ''
    interruption = None
    interrupted, killed = False, False
    try:
        # Foreground process-group signals reach the parent only. The parent
        # forwards one SIGTERM, so the child can finish its cleanup uninterrupted.
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        try:
            termination.waiting = True
            if termination.requested:
                raise KeyboardInterrupt
            stdout, stderr = process.communicate(timeout=timeout)
        finally:
            termination.waiting = False
    except (subprocess.TimeoutExpired, KeyboardInterrupt, OSError) as error:
        interruption = str(error) or 'interrupted'
        interrupted = isinstance(error, KeyboardInterrupt)
        if interrupted:
            termination.requested = True
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=cleanup_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                killed = True
                stdout, stderr = process.communicate()
    manifest = None
    result = {'status': 'incomplete', 'cleanup': 'unknown'}
    try:
        result = read_object(output / 'report.json')
        if (output / 'manifest.json').exists():
            manifest = read_object(output / 'manifest.json')
        expected_code = {'pass': 0, 'fail': 1, 'invalid': 2, 'incomplete': 3, 'skipped': 3}.get(result.get('status'))
        if not interruption and (expected_code is None or process.returncode != expected_code):
            interruption = 'runner exit code and report status disagree'
        if result.get('status') == 'pass' and manifest is None:
            interruption = 'passing runner omitted its provenance manifest'
    except (OSError, ValueError) as error:
        result = {**result, 'status': 'incomplete', 'evidence_error': f'cannot read runner evidence: {error}'}
        interruption = interruption or result['evidence_error']
    interrupted |= termination.requested
    if interrupted:
        interruption = interruption or 'interrupted'
    if interruption:
        # A child can finish a report while its parent reaches the deadline.
        # Preserve snapshots/counters/cleanup, but never turn that timeout into
        # agreement. Killing the child leaves cleanup unconfirmed even if an
        # earlier report was written before its finally block.
        result = {**result, 'status': 'incomplete', 'orchestration_error': interruption}
        if killed:
            result.update(cleanup='unknown', cleanup_error='runner exceeded cleanup grace period and was killed')
    code = 3 if interruption else process.returncode
    return {'exit_code': code, 'stdout': stdout, 'stderr': stderr,
            'manifest': manifest, 'report': result}, interrupted


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
    profiles = len(matrix['profiles'])
    requested = sum(len(p['scenarios']) for p in matrix['profiles'])
    with TerminationSignals() as termination:
        for profile in matrix['profiles']:
            for scenario in profile['scenarios']:
                if termination.requested:
                    write_json(args.out / 'matrix-report.json', summary(cells, profiles, requested, interrupted=True))
                    return 3
                output = args.out / Path(scenario).stem
                argv = [sys.executable, str(ROOT / 'tools/frr/run_lab.py'), '--scenario', str(ROOT / scenario),
                        '--out', str(output), '--routeproof', args.routeproof]
                if args.image:
                    argv.extend(['--image', args.image])
                if args.generate_only:
                    argv.append('--generate-only')
                cell, interrupted = collect_cell(argv, output, termination=termination)
                cells.append({'profile': profile['id'], 'scenario': scenario, 'argv': argv, **cell})
                write_json(args.out / 'matrix-report.json', summary(cells, profiles, requested,
                           interrupted=interrupted or termination.requested))
                if interrupted or termination.requested:
                    # A signal can arrive while the completed cell is being saved.
                    write_json(args.out / 'matrix-report.json', summary(cells, profiles, requested, interrupted=True))
                    return 3
        result = summary(cells, profiles, requested, interrupted=termination.requested)
        print(json.dumps({key: result[key] for key in ('status', 'passing_snapshots', 'comparison_slots', 'matched_slots')}))
        return {'pass': 0, 'fail': 1, 'incomplete': 3, 'skipped': 3}[result['status']]


def summary(cells, profiles, requested, interrupted=False):
    statuses = {c['report']['status'] for c in cells}
    status = 'incomplete' if interrupted or statuses & {'incomplete', 'invalid'} or len(cells) != requested else (
        'skipped' if 'skipped' in statuses else 'fail' if 'fail' in statuses else 'pass')
    return {'schema_version': 1, 'status': status, 'profile_count': profiles,
            'requested_scenarios': requested, 'completed_scenarios': len(cells), 'cells': cells,
            **{key: sum(c['report'].get(key, 0) for c in cells) for key in
               ('requested_snapshots', 'completed_snapshots', 'passing_snapshots', 'comparison_slots', 'matched_slots')}}


if __name__ == '__main__':
    sys.exit(main())
