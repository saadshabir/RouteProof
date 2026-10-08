#!/usr/bin/env python3
"""Run the diamond demo, check its expected failures, and verify repeat bytes."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def check_result(result):
    expected = [('baseline', ['ab', 'ac'], 'pass', None),
                ('event-1', ['ac'], 'pass', None),
                ('event-2', [], 'fail', 'no_route'),
                ('event-3', ['ab'], 'pass', None),
                ('event-4', [], 'fail', 'destination_down'),
                ('event-5', ['ab'], 'pass', None)]
    if result['status'] != 'fail' or len(result['snapshots']) != 6 or len(result['assertions']) != 6:
        raise ValueError('diamond must complete six snapshots with two expected failures')
    rows = []
    for snapshot, assertion, (identity, links, status, kind) in zip(result['snapshots'], result['assertions'], expected):
        routes = [r for r in snapshot['routes'] if r['router'] == 'a' and r['prefix'] == '10.10.4.0/24']
        hops = [h['link'] for h in routes[0]['next_hops']] if routes else []
        kinds = [finding['kind'] for finding in assertion['findings']]
        if (snapshot['id'] != identity or assertion['snapshot_id'] != identity or
                assertion['assertion_id'] != 'a-to-d' or assertion['status'] != status or
                hops != links or kinds != ([] if kind is None else [kind]) or
                (links and (len(routes) != 1 or routes[0]['metric'] != 3))):
            raise ValueError('diamond outcome mismatch at ' + identity)
        rows.append({'snapshot': identity, 'next_hop_links': hops, 'status': status, 'reason': kind})
    if 'cd' in result['snapshots'][-1]['administratively_up_links']:
        raise ValueError('router restoration revived the separately failed cd link')
    return rows


def run(binary, out):
    out.mkdir(parents=True, exist_ok=False)
    commands = []

    def command(args, expected, name):
        process = subprocess.run(args, capture_output=True, text=True, timeout=60)
        (out / (name + '.stdout.txt')).write_text(process.stdout)
        (out / (name + '.stderr.txt')).write_text(process.stderr)
        commands.append({'argv': args, 'exit_code': process.returncode, 'expected_exit_code': expected})
        (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        if process.returncode != expected:
            raise ValueError(f'{name}: expected exit {expected}, got {process.returncode}')

    scenario = str(ROOT / 'examples/diamond-failures.yaml')
    command([str(binary), 'validate', scenario], 0, 'validate')
    for name in ('first', 'repeat'):
        command([str(binary), 'simulate', scenario, '--out', str(out / name)], 1, name)
    data = (out / 'first/result.json').read_bytes()
    if data != (out / 'repeat/result.json').read_bytes():
        raise ValueError('diamond repeat changed canonical bytes')
    rows = check_result(json.loads(data))
    command([str(binary), 'explain', str(out / 'first/result.json'), '--assertion', 'a-to-d'], 1, 'explain')
    report = {'status': 'pass', 'scenario': 'diamond-failures', 'snapshots': rows,
              'expected_simulate_exit': 1, 'expected_explain_exit': 1,
              'result_file_sha256': hashlib.sha256(data).hexdigest()}
    (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.binary.resolve(), args.out.resolve()), indent=2))
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'fail', 'reason': str(error)}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
