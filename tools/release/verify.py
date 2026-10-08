#!/usr/bin/env python3
"""Verify a clean candidate: fresh builds, all CTest groups, demo and benchmark."""
import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def verify(args):
    source, out = args.source.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = {'status': 'incomplete', 'source': str(source), 'host': platform.platform(),
              'commands': [], 'builds': [], 'release_complete': False,
              'open_gates': ['live Linux FRR acceptance', 'authoritative Linux RSS']}

    def command(argv, name, expected=0, env=None):
        print(name, flush=True)
        with (out / (name + '.txt')).open('w') as log:
            proc = subprocess.run(argv, cwd=source, env=env, stdout=log,
                                  stderr=subprocess.STDOUT, timeout=1800)
        report['commands'].append({'argv': argv, 'log': name + '.txt',
                                   'exit_code': proc.returncode, 'expected_exit_code': expected})
        if proc.returncode != expected:
            raise ValueError(f'{name} failed; see {out / (name + ".txt")}')

    def clean():
        status = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=all'],
                                         cwd=source, text=True).strip()
        if status:
            raise ValueError('candidate checkout must stay clean: ' + status)
        return status

    try:
        report['initial_git_status'] = clean()
        report['revision'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
        cache_args = []
        if args.dependency_cache:
            dependencies = {}
            for name, tag in (('yaml-cpp', 'yaml-cpp-0.9.0'), ('nlohmann_json', 'v3.12.0'),
                              ('picosha2', 'v1.0.1')):
                path = args.dependency_cache.resolve() / (name + '-src')
                revision = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
                pinned = subprocess.check_output(['git', '-C', str(path), 'rev-parse', tag + '^{commit}'], text=True).strip()
                status = subprocess.check_output(['git', '-C', str(path), 'status', '--porcelain'], text=True).strip()
                if status or revision != pinned:
                    raise ValueError('dependency cache must be clean and match ' + tag + ': ' + str(path))
                dependencies[name] = {'path': str(path), 'revision': revision, 'tag': tag}
                cache_args.append('-DFETCHCONTENT_SOURCE_DIR_' + name.upper() + '=' + str(path))
            report['reused_dependencies'] = dependencies
        builds = [('host-release', 'host-release', {})]
        # Preserve the driver's invocation name: clang++ is often a symlink to
        # clang, but invoking clang directly omits automatic C++ runtime linkage.
        if args.gcc_cxx:
            builds.append(('gcc-debug', 'gcc-debug', {'ROUTEPROOF_GCC_CXX': str(args.gcc_cxx.absolute())}))
        if args.clang_cxx:
            builds.append(('clang-debug', 'clang-debug', {'ROUTEPROOF_CLANG_CXX': str(args.clang_cxx.absolute())}))
        if args.sanitizers:
            builds.append(('host-sanitizers', 'host-sanitizers', {}))
        for name, preset, variables in builds:
            build = source / 'build' / name
            if build.exists():
                raise ValueError('verification requires a fresh build directory: ' + str(build))
            env = dict(os.environ, **variables)
            if name == 'host-sanitizers':
                env['ASAN_OPTIONS'] = 'halt_on_error=1:detect_leaks=' + ('0' if sys.platform == 'darwin' else '1')
                env['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
                report['sanitizer_options'] = {key: env[key] for key in ('ASAN_OPTIONS', 'UBSAN_OPTIONS')}
            command(['cmake', '--preset', preset, *cache_args], name + '-configure', env=env)
            command(['cmake', '--build', '--preset', preset, '--parallel', str(args.jobs)], name + '-build', env=env)
            command(['ctest', '--test-dir', str(build), '--output-on-failure'], name + '-tests', env=env)
            command([str(build / 'routeproof'), '--version'], name + '-version', env=env)
            command([sys.executable, str(source / 'tools/release/demo.py'), '--binary', str(build / 'routeproof'),
                     '--out', str(out / (name + '-diamond'))], name + '-diamond-demo', env=env)
            demo = json.loads((out / (name + '-diamond/report.json')).read_text())
            if report.get('diamond_result_file_sha256', demo['result_file_sha256']) != demo['result_file_sha256']:
                raise ValueError('canonical diamond bytes differ across toolchains')
            report['diamond_result_file_sha256'] = demo['result_file_sha256']
            report['builds'].append({'preset': preset, 'status': 'pass'})
        binary = source / 'build/host-release/routeproof'
        command([str(binary), 'bench', '--profile', str(source / 'benchmarks/profiles/sparse-small.json'),
                 '--out', str(out / 'bench-small')], 'benchmark-small')
        command([sys.executable, str(source / 'tools/frr/run_matrix.py'), '--generate-only',
                 '--routeproof', str(binary), '--out', str(out / 'frr-generated')], 'frr-generation', expected=3)
        frr = json.loads((out / 'frr-generated/matrix-report.json').read_text())
        if frr['status'] != 'skipped':
            raise ValueError('offline FRR generation must be explicitly skipped')
        report['offline_frr_status'] = 'skipped (not live acceptance)'
        report['final_git_status'] = clean()
        report['status'] = 'pass'
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        report['reason'] = str(error)
        print(str(error), file=sys.stderr)
        return 3
    finally:
        (out / 'verification.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--gcc-cxx', type=Path)
    parser.add_argument('--clang-cxx', type=Path)
    parser.add_argument('--dependency-cache', type=Path)
    parser.add_argument('--sanitizers', action='store_true')
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    return verify(args)


if __name__ == '__main__':
    raise SystemExit(main())
