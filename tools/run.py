#!/usr/bin/env python3
"""Build and run RouteProof from a source checkout.

Usage: python3 tools/run.py COMMAND [ARGS...]

  demo --out DIR       Run and verify the diamond example
  test                 Build and run all acceptance checks
  build                Build the Release executable
  frr [ARGS...]        Run the FRR matrix (live labs require Linux)
  validate/routes/simulate/explain/bench/--version
                       Forward arguments to the RouteProof CLI

Requires Python 3.9+, Git, CMake, Ninja and a supported C++20 compiler.
The first build fetches pinned dependencies; later builds are incremental.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/host-release'


def main(argv):
    if not argv or argv == ['--help']:
        print(__doc__)
        return 0
    if sys.version_info < (3, 9):
        print('RouteProof requires Python 3.9 or newer.', file=sys.stderr)
        return 3
    if argv[0] == 'build' and len(argv) != 1:
        print('Usage: python3 tools/run.py build', file=sys.stderr)
        return 2
    missing = [name for name in ('git', 'cmake', 'ninja') if shutil.which(name) is None]
    if missing:
        print('Install required tools: ' + ', '.join(missing) + '. See README.md.', file=sys.stderr)
        return 3
    try:
        # Keep build logs off stdout so CLI JSON remains machine-readable.
        subprocess.run(['cmake', '--preset', 'host-release'], cwd=ROOT,
                       stdout=sys.stderr, check=True)
        build = ['cmake', '--build', '--preset', 'host-release', '--parallel', '4']
        if argv[0] != 'test':
            build += ['--target', 'routeproof']
        subprocess.run(build, cwd=ROOT, stdout=sys.stderr, check=True)
        binary = str(BUILD / 'routeproof')
        if argv[0] == 'build':
            return 0
        if argv[0] == 'test':
            command = ['ctest', '--test-dir', str(BUILD), '--output-on-failure', *argv[1:]]
            os.execvp(command[0], command)
        if argv[0] in ('demo', 'frr'):
            script, option = ('release/demo.py', '--binary') if argv[0] == 'demo' else ('frr/run_matrix.py', '--routeproof')
            command = [sys.executable, str(ROOT / 'tools' / script), option, binary, *argv[1:]]
            os.execv(command[0], command)
        os.execv(binary, [binary, *argv])
    except (OSError, subprocess.CalledProcessError) as error:
        print('RouteProof build/run failed: ' + str(error), file=sys.stderr)
        return 3


if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        raise SystemExit(130)
