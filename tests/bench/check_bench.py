#!/usr/bin/env python3
"""Benchmark contracts: semantics, frozen dimensions, raw evidence and limits."""
import copy
import json
import os
import signal
import shutil
import time
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/bench'))
from generate import Random, generate, read_json
from run import execute, provenance, run_child, source_manifest, validate_profile
from compare_runs import compare, validate_run

BINARY = str(Path(sys.argv.pop(1)).resolve())
PROFILE = read_json(ROOT / 'benchmarks/profiles/sparse-small.json')


class BenchTests(unittest.TestCase):
    def test_instrumentation_preserves_canonical_bytes_and_actual_counters(self):
        with tempfile.TemporaryDirectory(prefix='bench spaces ') as name:
            tmp = Path(name)
            for index, path in enumerate([ROOT / 'examples/diamond-failures.yaml',
                    ROOT / 'examples/replay/parallel-restoration.json',
                    ROOT / 'examples/replay/initial-down-restoration.json']):
                outputs = []
                for mode in ('simulate', 'bench-sample'):
                    out = tmp / f'{index}-{mode}'
                    proc = subprocess.run([BINARY, mode, str(path), '--out', str(out)], capture_output=True)
                    self.assertIn(proc.returncode, (0, 1), proc.stderr)
                    outputs.append((out / 'result.json').read_bytes())
                self.assertEqual(*outputs)
                result = json.loads(outputs[0])
                sample = json.loads((out / 'sample.json').read_text())
                self.assertEqual(sample['result_sha256'], result['canonical_sha256'])
                self.assertEqual(sample['core_processing_ns'], sum(x['processing_ns'] for x in sample['snapshots']))
                self.assertLessEqual(sample['core_processing_ns'], sample['simulation_ns'])
                self.assertEqual(len(sample['snapshots']), len(result['snapshots']))
                for measured, snapshot in zip(sample['snapshots'], result['snapshots']):
                    self.assertEqual(measured['route_entries'], len(snapshot['routes']))
                    self.assertEqual(measured['next_hop_references'], sum(len(x['next_hops']) for x in snapshot['routes']))
                    assertions = [x for x in result['assertions'] if x['snapshot_id'] == snapshot['id']]
                    self.assertEqual(measured['assertion_evaluations'], len(assertions))
                    self.assertEqual(measured['failed_assertions'], sum(x['status'] == 'fail' for x in assertions))
                    self.assertGreater(measured['processing_ns'], 0)

    def test_frozen_shapes_coverage_and_trace(self):
        rng = Random(1)
        self.assertEqual([rng.next() for _ in range(3)], [270369, 67634689, 2647435461])
        with tempfile.TemporaryDirectory() as name:
            for shape in ('chain', 'ring', 'grid', 'diamond_ladder', 'sparse_random'):
                cell = dict(PROFILE['cells'][0], shape=shape, prefix_origins='all', assertions='all')
                scenario = generate(cell)
                self.assertEqual(len(scenario['routers']), 16)
                self.assertEqual(len(scenario['prefixes']), 16)
                self.assertEqual(len(scenario['assertions']), 256)
                self.assertEqual(len(scenario['events']), 8)
                self.assertEqual(scenario, generate(cell))
                path = Path(name) / 'scenario.json'
                path.write_text(json.dumps(scenario))
                out = Path(name) / shape
                proc = subprocess.run([BINARY, 'bench-sample', str(path), '--out', str(out)], capture_output=True)
                self.assertEqual(proc.returncode, 1, proc.stderr)
                data = json.loads((out / 'sample.json').read_text())
                self.assertEqual(data['snapshots'][0]['failed_assertions'], 0)
                self.assertEqual(data['snapshots'][-1]['failed_assertions'], 0)
                self.assertEqual(sum(x['applied'] for x in data['snapshots']), 6)
                self.assertEqual(data['analyzed_destinations'], 16)
                result = json.loads((out / 'result.json').read_text())
                kinds = {f['kind'] for a in result['assertions'] for f in a['findings']}
                self.assertTrue({'source_down', 'destination_down', 'no_route'} <= kinds)

    def test_profile_validation_and_duplicate_keys(self):
        for edit in (lambda x: x.update(repetitions=4), lambda x: x.update(schema_version=True),
                     lambda x: x['cells'][0].update(routers=True),
                     lambda x: x['cells'][0].update(unknown=True),
                     lambda x: x['cells'][0].update(routers=4096, assertions='all', prefix_origins='all'),
                     lambda x: x['cells'].append(copy.deepcopy(x['cells'][0]))):
            bad = copy.deepcopy(PROFILE)
            edit(bad)
            with self.assertRaises(ValueError):
                validate_profile(bad)
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'bad.json'
            path.write_text('{"schema_version":1,"schema_version":2}')
            with self.assertRaises(ValueError):
                read_json(path)

    def test_timeout_and_nonzero_exit_preserve_process_artifacts(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            result = run_child([sys.executable, '-c', 'import time; time.sleep(10)'], tmp / 'timeout', 0.1, 1024**3)
            self.assertEqual(result['status'], 'timeout')
            self.assertTrue((tmp / 'timeout/process.json').exists())
            with self.assertRaises(ProcessLookupError):
                # A terminated child was reaped; no owned sleeper survives.
                os.kill(result['pid'], 0)
            result = run_child([sys.executable, '-c', 'raise SystemExit(3)'], tmp / 'error', 5, 1024**3)
            self.assertEqual(result['status'], 'incomplete')
            self.assertEqual(result['exit_code'], 3)
            result = run_child([sys.executable, '-c', 'x=bytearray(20000000)'], tmp / 'memory', 5, 1024)
            self.assertEqual(result['status'], 'memory_limit')

    def test_completed_worker_still_obeys_final_timeout(self):
        # Model a worker reaped before the monitor gets its first timeslice.
        class ImmediateWaiter:
            def __init__(self, target, daemon):
                self.target = target

            def start(self):
                self.target()

            def join(self):
                pass

        with tempfile.TemporaryDirectory() as name, \
                mock.patch('run.subprocess.Popen', return_value=SimpleNamespace(pid=1234, returncode=None)), \
                mock.patch('run.os.wait4', return_value=(1234, 0, SimpleNamespace(ru_maxrss=0))), \
                mock.patch('run.threading.Thread', ImmediateWaiter), \
                mock.patch('run.time.perf_counter_ns', side_effect=[0, 2000000000]):
            result = run_child(['worker'], Path(name) / 'finished', 1, 1024**3)
            self.assertEqual(result['exit_code'], 0)
            self.assertEqual(result['elapsed_ns'], 2000000000)
            self.assertEqual(result['status'], 'timeout')
            self.assertEqual(json.loads((Path(name) / 'finished/process.json').read_text()), result)

    def test_external_binary_provenance_uses_its_cmake_checkout(self):
        with tempfile.TemporaryDirectory() as name:
            source = (Path(name) / 'external source').resolve()
            source.mkdir()
            (source / 'CMakeLists.txt').write_text('# external source\n')
            (source / 'CMakePresets.json').write_text('{}\n')
            build = Path(name) / 'external build'
            build.mkdir()
            binary = build / 'routeproof'
            binary.write_bytes(b'synthetic binary')
            (build / 'CMakeCache.txt').write_text(f'CMAKE_HOME_DIRECTORY:INTERNAL={source}\n')
            def capture(args):
                return str(args[2]) if args[0] == 'git' else 'available'
            with mock.patch('run.capture', side_effect=capture):
                host = provenance(binary)
            self.assertEqual(host['source_root'], str(source))
            self.assertEqual(host['source_revision'], str(source))
            self.assertEqual(host['git_status'], str(source))
            self.assertEqual(host['source_inputs'], source_manifest(source))
            self.assertEqual(host['harness']['source_root'], str(ROOT))
            self.assertEqual(host['harness']['source_inputs'], source_manifest(ROOT))
            self.assertNotEqual(host['source_inputs'], host['harness']['source_inputs'])
            (build / 'CMakeCache.txt').unlink()
            with mock.patch('run.capture', side_effect=capture):
                host = provenance(binary)
            self.assertIsNone(host['source_root'])
            self.assertIsNone(host['source_inputs'])

    def test_interruption_between_cells_cannot_publish_a_complete_sweep(self):
        profile = copy.deepcopy(PROFILE)
        profile['cells'].append(dict(profile['cells'][0], id='second-cell'))
        calls = {}
        def interrupted_generation(cell):
            calls[cell['id']] = calls.get(cell['id'], 0) + 1
            # The first call validates the profile; the second starts its cell.
            if cell['id'] == 'second-cell' and calls[cell['id']] == 2:
                raise KeyboardInterrupt
            return generate(cell)
        with tempfile.TemporaryDirectory() as name, mock.patch('run.generate', side_effect=interrupted_generation):
            out = Path(name) / 'out'
            with self.assertRaises(KeyboardInterrupt):
                execute(profile, Path(BINARY), out, allow_debug=True)
            summary = json.loads((out / 'summary.json').read_text())
            self.assertEqual(summary['status'], 'partial')
            self.assertEqual(summary['completed_cells'], 1)
            self.assertEqual(summary['attempted_cells'], 1)
            self.assertEqual(summary['declared_cells'], 2)
            self.assertEqual(summary['cells'][0]['status'], 'complete')

    def test_interrupt_checkpoints_and_reaps_owned_worker(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            marker = tmp / 'worker.pid'
            fake = tmp / 'fake.py'
            fake.write_text('#!/usr/bin/env python3\nimport sys,os,time\n'
                'if sys.argv[1] == "validate":\n print("{}")\nelse:\n'
                f' open({str(marker)!r}, "w").write(str(os.getpid()))\n time.sleep(30)\n')
            fake.chmod(0o755)
            profile = tmp / 'profile.json'
            profile.write_text(json.dumps(PROFILE))
            # Host discovery (notably macOS system_profiler) is unrelated to
            # interruption and can exhaust the worker-start deadline under load.
            # Keep the real CLI, signals, checkpointing and child lifecycle;
            # replace only the provenance query in this isolated subprocess.
            launcher = ('import sys; sys.path.insert(0, ' + repr(str(ROOT / 'tools/bench')) + '); '
                        'import run; run.provenance = lambda binary: {"build_cache": {}, "source_inputs": None}; '
                        'raise SystemExit(run.main())')
            process = subprocess.Popen([sys.executable, '-c', launcher,
                '--binary', str(fake), '--profile', str(profile), '--out', str(tmp / 'out'), '--allow-debug'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            try:
                deadline = time.monotonic() + 8
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(marker.exists())
                os.kill(process.pid, signal.SIGTERM)
                _, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 3, stderr)
                summary = json.loads((tmp / 'out/summary.json').read_text())
                self.assertEqual(summary['cells'][0]['status'], 'interrupted')
                self.assertEqual(summary['cells'][0]['warmups'][0]['process']['status'], 'interrupted')
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(marker.read_text()), 0)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                process.stdout.close()
                process.stderr.close()

    def test_harness_fresh_processes_hashes_and_budget_skips(self):
        with tempfile.TemporaryDirectory() as name:
            profile = copy.deepcopy(PROFILE)
            profile['cells'].append(dict(profile['cells'][0], id='budget-probe', routers=1024))
            out = Path(name) / 'evidence'
            self.assertEqual(execute(profile, Path(BINARY), out, allow_debug=True), 3)
            summary = json.loads((out / 'summary.json').read_text())
            self.assertEqual([x['status'] for x in summary['cells']], ['complete', 'budget_skipped'])
            cell = summary['cells'][0]
            self.assertEqual(len(cell['samples']), 10)
            self.assertEqual(len(cell['warmups']), 2)
            self.assertEqual(len({x['result_file_sha256'] for x in cell['samples']}), 1)
            self.assertEqual(cell['counters']['applied_events'], 6)
            self.assertEqual(cell['counters']['noop_events'], 2)
            self.assertTrue((out / 'event-timings.csv').exists())
            self.assertTrue((out / 'memory.csv').exists())
            # The reproducibility validator rejects insufficient/forged runs,
            # including alteration of a raw sample independently of summary.
            manifest_path = out / 'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['host']['build_cache']['CMAKE_BUILD_TYPE'] = 'Release'
            manifest['host']['build_cache'].pop('CMAKE_CXX_FLAGS', None)
            manifest_path.write_text(json.dumps(manifest))
            validate_run(out, cell['id'])
            summary_path = out / 'summary.json'
            baseline_summary = summary_path.read_bytes()
            # Every displayed counter and diagnostic must reconcile with raw
            # run/sample manifests and the retained canonical result.
            for key in ('counters', 'instrumentation_median_ratio', 'instrumented_simulation_ns',
                        'cli_simulation_ns', 'sample_simulation_ns', 'dimensions'):
                with self.subTest(corruption=key):
                    altered = json.loads(baseline_summary)
                    altered_cell = altered['cells'][0]
                    if key == 'counters':
                        altered_cell[key]['baseline_routes'] += 1
                    elif key == 'instrumentation_median_ratio':
                        altered_cell[key] += 1
                    elif key == 'sample_simulation_ns':
                        altered_cell['samples'][1]['simulation_ns'] += 1
                    elif key == 'dimensions':
                        altered_cell[key]['prefixes'] += 1
                    else:
                        altered_cell[key]['median'] += 1
                    summary_path.write_text(json.dumps(altered))
                    with self.assertRaises(ValueError):
                        validate_run(out, cell['id'])
                    summary_path.write_bytes(baseline_summary)
            run_path = out / cell['id'] / 'cli-000/output/run.json'
            baseline_run = run_path.read_bytes()
            altered_run = json.loads(baseline_run)
            altered_run['simulation_ns'] += 1
            run_path.write_text(json.dumps(altered_run))
            with self.assertRaises(ValueError):
                validate_run(out, cell['id'])
            run_path.write_bytes(baseline_run)
            metrics_path = out / cell['id'] / 'instrumented-000/output/sample.json'
            baseline_metrics = metrics_path.read_bytes()
            for key in ('route_entries', 'simulation_ns'):
                with self.subTest(raw_metrics=key):
                    altered_metrics = json.loads(baseline_metrics)
                    if key == 'simulation_ns':
                        altered_metrics[key] += 1
                    else:
                        altered_metrics['snapshots'][0][key] += 1
                    altered = json.loads(baseline_summary)
                    altered['cells'][0]['samples'][0]['metrics'] = altered_metrics
                    metrics_path.write_text(json.dumps(altered_metrics))
                    summary_path.write_text(json.dumps(altered))
                    with self.assertRaises(ValueError):
                        validate_run(out, cell['id'])
                    metrics_path.write_bytes(baseline_metrics)
                    summary_path.write_bytes(baseline_summary)
            reproduction = Path(name) / 'reproduction'
            shutil.copytree(out, reproduction)
            reproduced_manifest = copy.deepcopy(manifest)
            reproduced_manifest['host']['binary_path'] += '-distinct'
            reproduced_manifest['host']['git_status'] = ''
            reproduced_manifest['host']['harness']['git_status'] = ''
            reproduction_manifest_path = reproduction / 'manifest.json'
            reproduction_manifest_path.write_text(json.dumps(reproduced_manifest))
            self.assertEqual(compare(out, reproduction, cell['id'])['status'], 'pass')
            for key in ('git_status', 'source_inputs'):
                with self.subTest(harness=key):
                    altered_manifest = copy.deepcopy(reproduced_manifest)
                    altered_manifest['host']['harness'][key] = 'dirty' if key == 'git_status' else {}
                    reproduction_manifest_path.write_text(json.dumps(altered_manifest))
                    with self.assertRaises(ValueError):
                        compare(out, reproduction, cell['id'])
            raw_path = out / cell['id'] / 'cli-000/process.json'
            raw = json.loads(raw_path.read_text())
            raw['exit_code'] = 3
            raw_path.write_text(json.dumps(raw))
            with self.assertRaises(ValueError):
                validate_run(out, cell['id'])
            with self.assertRaises(ValueError):
                execute(profile, Path(BINARY), out, allow_debug=True)

    def test_cli_dispatch_preserves_arguments(self):
        with tempfile.TemporaryDirectory(prefix='bench spaces ') as name:
            profile = Path(name) / 'profile.json'
            profile.write_text(json.dumps(PROFILE))
            result = subprocess.run([BINARY, 'bench', '--profile', str(profile), '--out', str(Path(name) / 'out'), '--allow-debug'], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
