#!/usr/bin/env python3
"""Protect package integrity and the demo's expected-failure contract."""
import copy
import hashlib
import io
import json
import sys
import tempfile
import tarfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/release'))
from package import REQUIRED_FILES, check, create
from demo import check_result, run
from check_linux import memory_evidence, same_implementation

BINARY = Path(sys.argv.pop(1)).resolve()


def source_tree(root):
    for name in REQUIRED_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name + '\n')
    return set(REQUIRED_FILES)


def archive_bundle(out, manifest, names, version=None):
    """Keep adversarial bundles self-consistent so only path validation rejects them."""
    if version is not None:
        manifest['version'] = version
    archive = out / manifest['archive']
    prefix = 'routeproof-' + manifest['version'] + '/'
    inputs = {}
    with tarfile.open(archive, 'w:gz') as tar:
        for index, entry in enumerate(names):
            data = str(index).encode()
            info = tarfile.TarInfo(entry)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
            inputs[entry.removeprefix(prefix)] = hashlib.sha256(data).hexdigest()
    manifest['archive_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest['source_files'] = inputs
    manifest['source_files_sha256'] = hashlib.sha256(
        json.dumps(inputs, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    path = out / 'manifest.json'
    path.write_text(json.dumps(manifest))
    (out / 'SHA256SUMS').write_text(
        f"{manifest['archive_sha256']}  {archive.name}\n"
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  manifest.json\n")


class ReleaseTests(unittest.TestCase):
    def test_linux_gate_rejects_unrelated_lab_and_memory_builds(self):
        files = {name: 'a' * 64 for name in ('CMakeLists.txt', 'CMakePresets.json', 'app/main.cpp')}
        manifest = {'host': {'source_revision': '1' * 40, 'binary_sha256': 'b' * 64,
                             'source_inputs': {'files': files}}}
        lab = {'git_revision': '1' * 40, 'binary_sha256': 'b' * 64, 'source_hashes': files.copy()}
        same_implementation(manifest, {'cells': [{'manifest': lab}]})
        for mutation in ('revision', 'binary', 'input', 'unrelated-inputs'):
            changed = copy.deepcopy(lab)
            if mutation == 'revision':
                changed['git_revision'] = '2' * 40
            elif mutation == 'binary':
                changed['binary_sha256'] = 'c' * 64
            elif mutation == 'input':
                changed['source_hashes']['app/main.cpp'] = 'd' * 64
            else:
                changed['source_hashes'] = {'other.cpp': 'a' * 64}
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'same source and binary'):
                same_implementation(manifest, {'cells': [{'manifest': changed}]})

    def test_linux_memory_gate_rejects_native_or_missing_samples(self):
        # A recorded native run must never close the Linux memory gate.
        # This rejection is independent of external candidate receipts.
        manifest = {'host': {'os_kernel': 'macOS-test'}}
        with self.assertRaisesRegex(ValueError, 'Linux host'):
            memory_evidence(manifest, {'cells': []})
        manifest['host']['os_kernel'] = 'Linux-test'
        summary = {'cells': [{'id': 'sparse-small-16', 'status': 'complete', 'samples': []}]}
        with self.assertRaisesRegex(ValueError, 'five distinct repetitions'):
            memory_evidence(manifest, summary)

    def test_package_is_deterministic_and_detects_tampering(self):
        with tempfile.TemporaryDirectory(prefix='release spaces ') as name:
            tmp = Path(name)
            source = tmp / 'source'
            required = source_tree(source)
            for folder in ('src', 'build', 'results', 'evidence/release', 'tools/__pycache__'):
                path = source / folder
                path.mkdir(parents=True)
                (path / 'file.txt').write_text(folder)
            a = create(source, tmp / 'a', '0.1.0-rc.1')
            b = create(source, tmp / 'b', '0.1.0-rc.1')
            self.assertEqual(a['archive_sha256'], b['archive_sha256'])
            self.assertEqual(set(a['source_files']), required | {'src/file.txt'})
            self.assertEqual(check(tmp / 'a')['status'], 'pass')
            archive = tmp / 'a' / a['archive']
            archive.write_bytes(archive.read_bytes() + b'altered')
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                check(tmp / 'a')
            manifest = tmp / 'b/manifest.json'
            value = json.loads(manifest.read_text())
            value['source_files']['src/file.txt'] = '0' * 64
            manifest.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'file hashes mismatch'):
                check(tmp / 'b')

    def test_package_refuses_final_version_symlink_and_overwrite(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            source = tmp / 'source'
            source_tree(source)
            (source / 'src').mkdir(parents=True)
            with self.assertRaises(ValueError):
                create(source, tmp / 'final', '0.1.0')
            # An asserted pass without both raw runs cannot authorize a final artifact.
            evidence = tmp / 'linux'
            evidence.mkdir()
            (evidence / 'acceptance.json').write_text(json.dumps({'status': 'pass', 'release_complete': True}))
            with self.assertRaisesRegex(ValueError, 'raw Linux acceptance'):
                create(source, tmp / 'false-final', '0.1.0', evidence)
            self.assertFalse((tmp / 'false-final').exists())
            (source / 'src/link').symlink_to(source / 'CMakeLists.txt')
            with self.assertRaisesRegex(ValueError, 'symlinks'):
                create(source, tmp / 'linked', '0.1.0-rc.1')
            self.assertFalse((tmp / 'linked').exists())
            (source / 'src/link').unlink()
            (tmp / 'existing').mkdir()
            with self.assertRaises(FileExistsError):
                create(source, tmp / 'existing', '0.1.0-rc.1')

    def test_package_refuses_missing_or_incomplete_source_before_output(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            (tmp / 'empty').mkdir()
            (tmp / 'file').write_text('not a directory')
            (tmp / 'incomplete').mkdir()
            (tmp / 'incomplete/CMakeLists.txt').write_text('project(RouteProof)\n')
            for source in ('missing', 'empty', 'file', 'incomplete'):
                with self.subTest(source=source):
                    out = tmp / (source + '-package')
                    with self.assertRaisesRegex(ValueError, 'source'):
                        create(tmp / source, out, '0.1.0-rc.1')
                    self.assertFalse(out.exists())

    def test_package_refuses_included_outputs_and_allows_external_receipts(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            source = tmp / 'source'
            source_tree(source)
            (source / 'docs').mkdir()
            (tmp / 'docs-alias').symlink_to(source / 'docs', target_is_directory=True)
            for out in (source, source / 'docs/package', source / 'src/package',
                        tmp / 'docs-alias/package'):
                with self.subTest(out=out):
                    with self.assertRaisesRegex(ValueError, 'outside packaged source'):
                        create(source, out, '0.1.0-rc.1')
                    if out != source:
                        self.assertFalse(out.exists())
            a = create(source, source / 'results/package', '0.1.0-rc.1')
            b = create(source, source / 'evidence/release/package', '0.1.0-rc.1')
            self.assertEqual(a['archive_sha256'], b['archive_sha256'])
            self.assertEqual(set(a['source_files']), set(REQUIRED_FILES))

    def test_checker_rejects_unsafe_and_duplicate_archive_entries(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            source = tmp / 'source'
            source_tree(source)
            for index, names in enumerate((['routeproof-0.1.0-rc.1/../escape'],
                                           ['routeproof-0.1.0-rc.1/duplicate'] * 2,
                                           ['routeproof-0.1.0-rc.1/a', 'routeproof-0.1.0-rc.1/./a'],
                                           ['routeproof-0.1.0-rc.1/a', 'routeproof-0.1.0-rc.1//a'],
                                           ['routeproof-0.1.0-rc.1/a/./b'],
                                           ['/routeproof-0.1.0-rc.1/absolute'],
                                           ['routeproof-0.1.0-rc.1/..\\escape'])):
                out = tmp / str(index)
                manifest = create(source, out, '0.1.0-rc.1')
                archive_bundle(out, manifest, names)
                with self.assertRaisesRegex(ValueError, 'unsafe or duplicate'):
                    check(out)

    def test_checker_refuses_invalid_version_and_empty_inventory(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            source = tmp / 'source'
            source_tree(source)
            for index, version in enumerate(('0.1.0', '0.1.0-rc.1/../..')):
                out = tmp / str(index)
                manifest = create(source, out, '0.1.0-rc.1')
                archive_bundle(out, manifest, ['routeproof-' + version + '/escape'], version)
                with self.assertRaisesRegex(ValueError, 'candidate version|Linux acceptance receipt'):
                    check(out)
            out = tmp / 'empty'
            manifest = create(source, out, '0.1.0-rc.1')
            archive_bundle(out, manifest, [])
            with self.assertRaisesRegex(ValueError, 'missing required project files'):
                check(out)

    def test_demo_checks_failures_restoration_and_repeat_bytes(self):
        with tempfile.TemporaryDirectory() as name:
            out = Path(name) / 'diamond'
            report = run(BINARY, out)
            self.assertEqual(report['status'], 'pass')
            result = json.loads((out / 'first/result.json').read_text())
            for edit in (lambda x: x.update(status='pass'),
                         lambda x: x['assertions'][2].update(status='pass'),
                         lambda x: x['snapshots'][-1]['administratively_up_links'].append('cd'),
                         lambda x: x['snapshots'][0]['routes'][0]['next_hops'].pop()):
                bad = copy.deepcopy(result)
                edit(bad)
                with self.assertRaises(ValueError):
                    check_result(bad)


if __name__ == '__main__':
    unittest.main()
