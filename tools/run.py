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
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/host-release'
STAMP = BUILD / '.routeproof-launcher.json'
INITIAL_ENVIRONMENT = ('CC', 'CXX', 'CMAKE_TOOLCHAIN_FILE', 'CFLAGS', 'CXXFLAGS', 'LDFLAGS')
FLAG_CACHE_ENTRIES = {
    'CFLAGS': ('CMAKE_C_FLAGS',),
    'CXXFLAGS': ('CMAKE_CXX_FLAGS',),
    'LDFLAGS': ('CMAKE_EXE_LINKER_FLAGS', 'CMAKE_SHARED_LINKER_FLAGS', 'CMAKE_MODULE_LINKER_FLAGS'),
}


def cache_entries():
    cache = BUILD / 'CMakeCache.txt'
    if not cache.exists():
        return {}
    return {line.split(':', 1)[0]: line.split('=', 1)[1]
            for line in cache.read_text().splitlines()
            if not line.startswith(('#', '//')) and ':' in line.split('=', 1)[0] and '=' in line}


def configuration(cache):
    # Ninja still regenerates for CMake dependencies and always builds sources.
    # Unknown preset includes use the normal configure path instead of trying to
    # duplicate CMake's macro/include resolution in the launcher.
    paths = [ROOT / 'CMakeLists.txt', ROOT / 'CMakePresets.json', ROOT / 'CMakeUserPresets.json',
             BUILD / 'CMakeCache.txt', *sorted((ROOT / 'cmake').rglob('*.cmake'))]
    for key in ('CMAKE_TOOLCHAIN_FILE', 'CMAKE_USER_MAKE_RULES_OVERRIDE'):
        if cache.get(key):
            paths.append(Path(cache[key]))
    files = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
             for path in paths}
    for path in paths[1:3]:
        if path.is_file():
            try:
                if json.loads(path.read_text()).get('include'):
                    return None
            except ValueError:
                return None  # let CMake report the invalid preset
    executables = {}
    for name in ('cmake', 'ninja', cache.get('CMAKE_CXX_COMPILER'), cache.get('CMAKE_C_COMPILER')):
        if name:
            resolved = shutil.which(name)
            if resolved is None:
                return None
            path = Path(resolved).resolve()
            stat = path.stat()
            executables[name] = [str(path), stat.st_size, stat.st_mtime_ns]
    # Presets/toolchains can read arbitrary environment variables. Conservatively
    # invalidate on all changes except shell bookkeeping.
    environment = {key: value for key, value in os.environ.items()
                   if key not in ('PWD', 'OLDPWD', 'SHLVL', '_')}
    hashed_environment = hashlib.sha256(json.dumps(environment, sort_keys=True).encode()).hexdigest()
    selectors = {key: hashlib.sha256(environment[key].encode()).hexdigest() if key in environment else None
                 for key in INITIAL_ENVIRONMENT}
    return {'version': 1, 'files': files, 'executables': executables,
            'environment_sha256': hashed_environment, 'selectors': selectors}


def build_release(all_targets=False):
    cache = cache_entries()
    try:
        previous = json.loads(STAMP.read_text())
    except (OSError, ValueError):
        previous = None
    current = configuration(cache)
    mismatch = bool(cache) and (cache.get('CMAKE_HOME_DIRECTORY') != str(ROOT)
                               or cache.get('CMAKE_GENERATOR') != 'Ninja')
    if current is None or current != previous or mismatch or not (BUILD / 'build.ninja').is_file():
        configure = ['cmake', '--preset', 'host-release']
        selectors = {key: hashlib.sha256(os.environ[key].encode()).hexdigest() if key in os.environ else None
                     for key in INITIAL_ENVIRONMENT}
        previous_selectors = previous.get('selectors', {}) if isinstance(previous, dict) else {}
        changed_selectors = {key for key, value in selectors.items() if value != previous_selectors.get(key)}
        if mismatch or changed_selectors.intersection(('CC', 'CXX', 'CMAKE_TOOLCHAIN_FILE')):
            # Compiler/toolchain selection needs a fresh configure. Keep
            # explicitly supplied dependency source caches.
            configure.append('--fresh')
            if not mismatch:
                configure.extend('-D' + key + '=' + value for key, value in cache.items()
                                 if key.startswith('FETCHCONTENT_SOURCE_DIR_') and value)
        else:
            # Reinitialize only changed environment flags, preserving unrelated
            # cache options, compiler selection and configuration-specific flags.
            for key in sorted(changed_selectors):
                for entry in FLAG_CACHE_ENTRIES[key]:
                    configure.extend(('-U', entry))
        subprocess.run(configure, cwd=ROOT, stdout=sys.stderr, check=True)
    build = ['cmake', '--build', '--preset', 'host-release', '--parallel', '4']
    if not all_targets:
        build += ['--target', 'routeproof']
    subprocess.run(build, cwd=ROOT, stdout=sys.stderr, check=True)
    # Record after building: Ninja may have regenerated CMake and its cache.
    current = configuration(cache_entries())
    if current is not None:
        STAMP.write_text(json.dumps(current, sort_keys=True) + '\n')


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
        build_release(argv[0] == 'test')
        binary = str(BUILD / 'routeproof')
        if argv[0] == 'build':
            return 0
        if argv[0] == 'test':
            command = ['ctest', '--test-dir', str(BUILD), '--output-on-failure', *argv[1:]]
            os.execvp(command[0], command)
        if argv[0] in ('demo', 'frr'):
            script, option = ('demo.py', '--binary') if argv[0] == 'demo' else ('frr/run_matrix.py', '--routeproof')
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
