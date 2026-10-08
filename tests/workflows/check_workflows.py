#!/usr/bin/env python3
"""Protect the checked demo and Linux acceptance evidence contracts."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tools/linux'))
from demo import check_result, run
from check_acceptance import memory_evidence, same_implementation

BINARY = Path(sys.argv.pop(1)).resolve()


class WorkflowTests(unittest.TestCase):
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
        manifest = {'host': {'os_kernel': 'macOS-test'}}
        with self.assertRaisesRegex(ValueError, 'Linux host'):
            memory_evidence(manifest, {'cells': []})
        manifest['host']['os_kernel'] = 'Linux-test'
        summary = {'cells': [{'id': 'sparse-small-16', 'status': 'complete', 'samples': []}]}
        with self.assertRaisesRegex(ValueError, 'five distinct repetitions'):
            memory_evidence(manifest, summary)

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
