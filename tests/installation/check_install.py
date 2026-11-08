#!/usr/bin/env python3
"""Exercise an installed prefix or binary archive after relocation, without PATH tools."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile


def check(prefix, working, version):
    binary = prefix / 'bin/routeproof'
    data = prefix / 'share/routeproof'
    for name in ('LICENSE', 'yaml-cpp-LICENSE', 'nlohmann-json-LICENSE', 'PicoSHA2-LICENSE'):
        assert (data / 'licenses' / name).is_file(), name
    assert (data / 'schemas/scenario-v1.schema.json').is_file()
    assert not (prefix / 'include').exists(), 'dependency development files leaked into install'
    assert not (prefix / 'lib').exists(), 'dependency libraries leaked into install'
    environment = {**os.environ, 'PATH': str(working / 'no-tools')}
    (working / 'no-tools').mkdir()

    def run(*arguments, expected=0):
        process = subprocess.run([str(binary), *map(str, arguments)], cwd=working,
                                 env=environment, capture_output=True, text=True, timeout=60)
        assert process.returncode == expected, (arguments, process.returncode, process.stderr)
        return process

    reported = run('--version').stdout
    assert 'RouteProof ' in reported
    if version:
        assert reported.splitlines()[0] == 'RouteProof ' + version, reported
    # Also exercise a copied executable with no adjacent installed resources.
    standalone = working / 'standalone'
    standalone.mkdir()
    shutil.copy2(binary, standalone / 'routeproof')
    binary = standalone / 'routeproof'
    assert 'simulate' in run('--help').stdout
    scenario = data / 'examples/diamond-failures.yaml'
    assert json.loads(run('validate', scenario, '--normalized').stdout)['model'] == 'ospf_spf_v1'
    json.loads(run('routes', scenario).stdout)
    out = working / 'simulation'
    run('simulate', scenario, '--out', out, expected=1)
    result = json.loads((out / 'result.json').read_text())
    assert result['status'] == 'fail' and len(result['snapshots']) == 6
    assert sum(item['status'] == 'fail' for item in result['assertions']) == 2
    json.loads(run('summary', out / 'result.json').stdout)
    run('explain', out / 'result.json', '--assertion', 'a-to-d', expected=1)
    json.loads(run('compare', out / 'result.json', out / 'result.json').stdout)
    sweep = working / 'single failures'
    run('n-1', scenario, '--out', sweep)
    assert json.loads((sweep / 'result.json').read_text())['status'] == 'pass'
    sample = working / 'sample'
    run('bench-sample', scenario, '--out', sample, expected=1)
    assert (sample / 'result.json').read_bytes() == (out / 'result.json').read_bytes()
    assert 'bench is source tooling' in run('bench', expected=2).stderr
    print('PASS: relocated installation runs all native commands without PATH tools')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--prefix', type=Path)
    source.add_argument('--archive', type=Path)
    parser.add_argument('--version')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='routeproof install ') as directory:
        working = Path(directory)
        prefix = working / 'relocated prefix'
        if args.prefix:
            shutil.copytree(args.prefix, prefix)
        else:
            unpacked = working / 'unpacked'
            with tarfile.open(args.archive) as archive:
                for member in archive.getmembers():
                    path = Path(member.name)
                    if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                        raise ValueError('unexpected archive entry: ' + member.name)
                archive.extractall(unpacked)
            roots = list(unpacked.iterdir())
            assert len(roots) == 1 and roots[0].is_dir(), roots
            roots[0].rename(prefix)
        check(prefix, working, args.version)


if __name__ == '__main__':
    main()
