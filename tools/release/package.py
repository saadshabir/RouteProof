#!/usr/bin/env python3
"""Create and check a deterministic source artifact with explicit acceptance."""
import argparse
import gzip
import hashlib
import io
import json
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from check_linux import check as check_linux

ROOT = Path(__file__).resolve().parents[2]
DIRECTORIES = ('.github', 'app', 'src', 'include', 'cmake', 'tools', 'tests',
               'benchmarks', 'schemas', 'examples', 'labs', 'docs', 'evidence')
FILES = ('CMakeLists.txt', 'CMakePresets.json', 'README.md', 'LICENSE',
         '.gitignore', '.gitattributes')
REQUIRED_FILES = ('CMakeLists.txt', 'CMakePresets.json', 'README.md',
                  'app/main.cpp', 'cmake/Dependencies.cmake')
OPEN_GATES = ['live Linux FRR image compatibility, matrix agreement and clean rerun',
              'authoritative Linux peak and boundary RSS']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def candidate_version(version):
    if not isinstance(version, str) or not re.fullmatch(r'0\.1\.0-rc\.[1-9][0-9]*', version):
        raise ValueError('use a candidate version 0.1.0-rc.N while Linux gates are open')
    return version


def artifact_version(version):
    return version if version == '0.1.0' else candidate_version(version)


def linux_receipt(root, evidence):
    with tempfile.TemporaryDirectory(prefix='routeproof-linux-check-') as temporary:
        checked = Path(temporary) / 'checked'
        if check_linux(evidence / 'first', evidence / 'second', checked) != 0:
            raise ValueError('final source requires passing raw Linux acceptance and reproduction')
        acceptance = json.loads((checked / 'acceptance.json').read_text())
    matrix = json.loads((evidence / 'second/frr/matrix-report.json').read_text())
    tested = matrix['cells'][0]['manifest']['source_hashes'].copy()
    bench = json.loads((evidence / 'second/bench-small/manifest.json').read_text())
    tested.update(bench['host']['source_inputs']['files'])
    # Completion docs and artifact packaging change after evidence is collected.
    # Bind final acceptance to every routing, lab and measurement implementation
    # input, while recording the exact tested revision separately.
    folders = ('app/', 'src/', 'include/', 'cmake/', 'schemas/', 'labs/',
               'benchmarks/', 'tools/frr/', 'tools/bench/')
    tested = {name: digest for name, digest in tested.items()
              if name.startswith(folders) or name in ('CMakeLists.txt', 'CMakePresets.json')}
    if not tested or any(not (root / name).is_file() or sha((root / name).read_bytes()) != digest
                         for name, digest in tested.items()):
        raise ValueError('source implementation differs from tested Linux inputs')
    current = {path.relative_to(root).as_posix() for path in source_files(root)
               if path.relative_to(root).as_posix().startswith(folders)
               or path.name in ('CMakeLists.txt', 'CMakePresets.json') and path.parent == root}
    if current != set(tested):
        raise ValueError('source implementation inventory differs from tested Linux inputs')
    return {'acceptance': acceptance, 'tested_source_files': tested,
            'tested_source_revision': matrix['cells'][0]['manifest']['git_revision']}


def source_files(root):
    if not root.is_dir():
        raise ValueError('source directory does not exist: ' + str(root))
    missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
    if missing:
        raise ValueError('source is missing required project files: ' + ', '.join(missing))
    paths = [root / name for name in FILES if (root / name).is_file()]
    for path in paths:
        if path.is_symlink():
            raise ValueError('source package refuses symlinks: ' + str(path.relative_to(root)))
    for directory in DIRECTORIES:
        for path in (root / directory).rglob('*'):
            relative = path.relative_to(root)
            if ('.git' in relative.parts or '__pycache__' in relative.parts or path.suffix == '.pyc' or
                    path.name == '.DS_Store' or relative.parts[:2] == ('evidence', 'release')):
                continue
            if path.is_symlink():
                raise ValueError('source package refuses symlinks: ' + str(relative))
            if path.is_file():
                paths.append(path)
    return sorted(paths)


def create(root, out, version, linux_evidence=None):
    artifact_version(version)
    root, out = root.resolve(), out.resolve()
    receipt = None
    if version == '0.1.0':
        if linux_evidence is None:
            raise ValueError('final version requires --linux-evidence with two complete raw Linux runs')
        receipt = linux_receipt(root, linux_evidence.resolve())
    # Resolve symlinked output parents and reject self-inclusion before creating
    # anything. The external receipt subtree is deliberately not source input.
    receipts = root / 'evidence/release'
    if out == root or (not out.is_relative_to(receipts) and
                       any(out.is_relative_to(root / name) for name in DIRECTORIES)):
        raise ValueError('output must be outside packaged source directories')
    paths = source_files(root)
    out.mkdir(parents=True, exist_ok=False)
    prefix = 'routeproof-' + version
    archive = out / (prefix + '-source.tar.gz')
    inputs = {}
    with archive.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode='w', format=tarfile.PAX_FORMAT) as tar:
            for path in paths:
                relative = path.relative_to(root).as_posix()
                data = path.read_bytes()
                # Scripts are invoked through Python; all source files have stable permissions.
                info = tarfile.TarInfo(prefix + '/' + relative)
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                tar.addfile(info, io.BytesIO(data))
                inputs[relative] = sha(data)
    try:
        revision = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True, stderr=subprocess.DEVNULL).strip()
        status = subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain'], text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        revision, status = None, 'unavailable'
    manifest = {'schema_version': 1, 'version': version, 'status': 'release' if receipt else 'candidate',
                'release_complete': bool(receipt), 'open_gates': [] if receipt else OPEN_GATES,
                'archive': archive.name, 'archive_sha256': sha(archive.read_bytes()),
                'source_revision': revision, 'source_git_status': status,
                'source_files': inputs,
                'source_files_sha256': sha(json.dumps(inputs, sort_keys=True, separators=(',', ':')).encode()),
                'excluded': ['.git', 'build', 'results', 'local CMakeUserPresets.json',
                             'Python caches', 'evidence/release (external candidate receipts)']}
    if receipt:
        report = out / 'linux-acceptance.json'
        report.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
        manifest['linux_acceptance_sha256'] = sha(report.read_bytes())
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    sums = f"{manifest['archive_sha256']}  {archive.name}\n{sha((out / 'manifest.json').read_bytes())}  manifest.json\n"
    if receipt:
        sums += f"{manifest['linux_acceptance_sha256']}  linux-acceptance.json\n"
    (out / 'SHA256SUMS').write_text(sums)
    check(out)
    return manifest


def check(out):
    manifest = json.loads((out / 'manifest.json').read_text())
    version = artifact_version(manifest['version'])
    if version == '0.1.0':
        if not (out / 'linux-acceptance.json').is_file():
            raise ValueError('final version requires a checked Linux acceptance receipt')
        report = (out / 'linux-acceptance.json').read_bytes()
        receipt = json.loads(report)
        if (manifest.get('status') != 'release' or manifest.get('release_complete') is not True
                or manifest.get('open_gates') != [] or sha(report) != manifest.get('linux_acceptance_sha256')
                or receipt['acceptance'].get('status') != 'pass'
                or receipt['acceptance'].get('release_complete') is not True
                or receipt['acceptance'].get('open_gates') != []
                or not receipt['tested_source_files']
                or any(manifest['source_files'].get(name) != digest
                       for name, digest in receipt['tested_source_files'].items())):
            raise ValueError('invalid final Linux acceptance receipt')
    elif (manifest.get('status') != 'candidate' or manifest.get('release_complete') is not False
          or manifest.get('open_gates') != OPEN_GATES):
        raise ValueError('candidate must retain its open acceptance gates')
    archive_name = manifest['archive']
    if Path(archive_name).name != archive_name:
        raise ValueError('archive must be a local filename')
    archive = out / archive_name
    if sha(archive.read_bytes()) != manifest['archive_sha256']:
        raise ValueError('archive checksum mismatch')
    prefix = 'routeproof-' + version + '/'
    inputs = {}
    seen = set()
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar:
            path = PurePosixPath(member.name)
            relative = member.name.removeprefix(prefix)
            if (not member.name.startswith(prefix) or not member.isfile() or
                    path.is_absolute() or '..' in path.parts or '\\' in member.name or
                    path.as_posix() != member.name or path in seen):
                raise ValueError('unsafe or duplicate archive entry: ' + member.name)
            seen.add(path)
            inputs[relative] = sha(tar.extractfile(member).read())
    if inputs != manifest['source_files']:
        raise ValueError('archive source file hashes mismatch')
    if sha(json.dumps(inputs, sort_keys=True, separators=(',', ':')).encode()) != manifest['source_files_sha256']:
        raise ValueError('source manifest checksum mismatch')
    missing = [name for name in REQUIRED_FILES if name not in inputs]
    if missing:
        raise ValueError('archive is missing required project files: ' + ', '.join(missing))
    sums = (out / 'SHA256SUMS').read_text()
    expected = f"{manifest['archive_sha256']}  {archive.name}\n{sha((out / 'manifest.json').read_bytes())}  manifest.json\n"
    if version == '0.1.0':
        expected += f"{manifest['linux_acceptance_sha256']}  linux-acceptance.json\n"
    if sums != expected:
        raise ValueError('SHA256SUMS mismatch')
    return {'status': 'pass', 'version': manifest['version'], 'files': len(inputs),
            'archive_sha256': manifest['archive_sha256'],
            'source_files_sha256': manifest['source_files_sha256']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--version', default='0.1.0-rc.1')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--linux-evidence', type=Path, help='raw first/second Linux acceptance directory; required for final 0.1.0')
    args = parser.parse_args()
    try:
        result = check(args.out) if args.check else create(args.source.resolve(), args.out.resolve(), args.version, args.linux_evidence)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, tarfile.TarError) as error:
        print(json.dumps({'status': 'fail', 'reason': str(error)}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
