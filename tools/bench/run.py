#!/usr/bin/env python3
"""Budgeted fresh-process measurements. All attempted cells keep a report row."""
import argparse
import csv
import hashlib
import json
import os
import platform
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from generate import ALGORITHM, VERSION, estimates, generate, integer, read_json

ROOT = Path(__file__).resolve().parents[2]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def capture(args):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=10).strip()
    except (OSError, subprocess.SubprocessError) as error:
        return 'unavailable: ' + str(error)


def source_manifest(root=ROOT):
    files = []
    for folder in ('app', 'src', 'include', 'cmake', 'tools', 'tests', 'benchmarks', 'schemas'):
        files.extend(path for path in (root / folder).rglob('*')
                     if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc')
    files.extend(root / name for name in ('CMakeLists.txt', 'CMakePresets.json'))
    hashes = {str(path.relative_to(root)): sha(path.read_bytes()) for path in sorted(files)}
    return {'files': hashes, 'sha256': sha(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode())}


def checkout_provenance(root):
    if root is None:
        return {'source_root': None, 'source_revision': 'unavailable: no CMake source checkout',
                'git_status': 'unavailable: no CMake source checkout', 'source_inputs': None}
    return {'source_root': str(root),
            'source_revision': capture(['git', '-C', str(root), 'rev-parse', 'HEAD']),
            'git_status': capture(['git', '-C', str(root), 'status', '--porcelain']),
            'source_inputs': source_manifest(root)}


def provenance(binary):
    cache = binary.parent / 'CMakeCache.txt'
    entries = {}
    if cache.exists():
        for line in cache.read_text().splitlines():
            if not line.startswith(('#', '//')) and '=' in line and ':' in line.split('=', 1)[0]:
                key, value = line.split('=', 1)
                entries[key.split(':', 1)[0]] = value
    source = entries.get('CMAKE_HOME_DIRECTORY')
    checkout = checkout_provenance(Path(source).resolve() if source else None)
    dependencies = {}
    for name in ('yaml-cpp', 'nlohmann_json', 'picosha2'):
        dep = binary.parent / '_deps' / (name + '-src')
        if not dep.exists():
            dep = Path(entries.get('FETCHCONTENT_SOURCE_DIR_' + name.upper(), '/nonexistent'))
        dependencies[name] = capture(['git', '-C', str(dep), 'rev-parse', 'HEAD'])
    cpu, ram, power = 'unavailable', 'unavailable', 'unavailable'
    if sys.platform == 'darwin':
        cpu = capture(['sysctl', '-n', 'machdep.cpu.brand_string'])
        ram = capture(['sysctl', '-n', 'hw.memsize'])
        if cpu.startswith('unavailable') or ram.startswith('unavailable'):
            try:
                hardware = json.loads(capture(['/usr/sbin/system_profiler', 'SPHardwareDataType', '-json']))['SPHardwareDataType'][0]
                # Keep performance context without device identifiers.
                cpu = hardware.get('chip_type', hardware.get('cpu_type', cpu)) + '; ' + hardware.get('number_processors', '')
                ram = hardware.get('physical_memory', ram)
            except (ValueError, KeyError, IndexError):
                pass
        power = capture(['pmset', '-g', 'custom'])
    elif sys.platform.startswith('linux'):
        cpu = Path('/proc/cpuinfo').read_text()
        ram = Path('/proc/meminfo').read_text()
        governor = Path('/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor')
        power = governor.read_text().strip() if governor.exists() else 'governor unavailable'
    return {**checkout, 'harness': checkout_provenance(ROOT),
            'binary_path': str(binary), 'binary_sha256': sha(binary.read_bytes()),
            'compiler': capture([entries.get('CMAKE_CXX_COMPILER', 'c++'), '--version']),
            'cmake': capture(['cmake', '--version']), 'ninja': capture(['ninja', '--version']),
            'python': sys.version, 'build_cache': {k: v for k, v in entries.items()
                if k.startswith('CMAKE_CXX_') or k in ('CMAKE_BUILD_TYPE', 'CMAKE_GENERATOR')},
            'dependencies': dependencies, 'os_kernel': platform.platform(), 'machine': platform.machine(),
            'cpu': cpu, 'ram': ram, 'power_settings': power, 'clock_policy': 'monotonic perf_counter_ns / C++ steady_clock; frequency and boost uncontrolled'}


def rss(pid):
    try:
        if sys.platform.startswith('linux'):
            for line in Path(f'/proc/{pid}/status').read_text().splitlines():
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) * 1024
        elif sys.platform == 'darwin':
            return int(subprocess.check_output(['ps', '-o', 'rss=', '-p', str(pid)], stderr=subprocess.DEVNULL)) * 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return 0


def run_child(argv, directory, timeout, memory_bytes):
    directory.mkdir()
    write_json(directory / 'command.json', argv)
    started = time.perf_counter_ns()
    with (directory / 'stdout.txt').open('wb') as stdout, (directory / 'stderr.txt').open('wb') as stderr:
        process = subprocess.Popen(argv, stdout=stdout, stderr=stderr, start_new_session=True)
        status = None
        polled_peak = 0
        reaped = {}
        finished = threading.Event()
        def wait_for_exit():
            _, wait_status, usage = os.wait4(process.pid, 0)
            reaped.update(usage=usage, elapsed_ns=time.perf_counter_ns() - started)
            process.returncode = os.waitstatus_to_exitcode(wait_status)
            finished.set()
        waiter = threading.Thread(target=wait_for_exit, daemon=True)
        waiter.start()
        next_poll = 0
        try:
            while not finished.is_set():
                now = time.perf_counter_ns()
                if (now - started) / 1e9 > timeout:
                    status = 'timeout'
                if now >= next_poll:
                    polled_peak = max(polled_peak, rss(process.pid))
                    next_poll = now + 100000000
                if polled_peak > memory_bytes:
                    status = 'memory_limit'
                if status:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    finished.wait()
                    break
                finished.wait(0.01)
        except BaseException as error:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            finished.wait()
            if isinstance(error, KeyboardInterrupt):
                status = 'interrupted'
            else:
                raise
        waiter.join()
    elapsed = reaped['elapsed_ns']
    usage = reaped['usage']
    peak = int(usage.ru_maxrss) * (1 if sys.platform == 'darwin' else 1024)
    if peak > memory_bytes and status is None:
        status = 'memory_limit'
    if elapsed > timeout * 1e9 and status is None:
        status = 'timeout'
    result = {'argv': argv, 'pid': process.pid, 'elapsed_ns': elapsed, 'peak_rss_bytes': peak,
              'polled_peak_rss_bytes': polled_peak, 'exit_code': process.returncode,
              'status': status or ('complete' if process.returncode in (0, 1) else
                                   'oom_or_signal' if process.returncode < 0 else 'incomplete')}
    write_json(directory / 'process.json', result)
    return result


def validate_profile(profile):
    if not isinstance(profile, dict):
        raise ValueError('profile must be an object')
    if set(profile) != {'schema_version', 'name', 'warmups', 'repetitions', 'budgets', 'cells'} or type(profile['schema_version']) is not int or profile['schema_version'] != 1:
        raise ValueError('unsupported profile contract')
    if not isinstance(profile['name'], str) or not profile['name']:
        raise ValueError('profile name required')
    integer(profile['warmups'], 1, 10, 'warmups')
    integer(profile['repetitions'], 5, 100, 'repetitions')
    budget_keys = {'timeout_seconds', 'memory_mib', 'max_retained_routes', 'max_output_mib', 'max_spf_work_units'}
    if not isinstance(profile['budgets'], dict) or set(profile['budgets']) != budget_keys:
        raise ValueError('unsupported budget fields')
    for key, value in profile['budgets'].items():
        integer(value, 1, 1000000000, key)
    if not isinstance(profile['cells'], list) or not 1 <= len(profile['cells']) <= 32:
        raise ValueError('profile requires 1..32 cells')
    names = set()
    for cell in profile['cells']:
        generate(cell)
        if cell['id'] in names:
            raise ValueError('duplicate cell id')
        names.add(cell['id'])
    return profile


def dispersion(values):
    return {'median': statistics.median(values), 'min': min(values), 'max': max(values),
            'median_absolute_deviation': statistics.median(abs(x - statistics.median(values)) for x in values)}


def save_summary(out, manifest, cells):
    complete = [cell for cell in cells if cell['status'] == 'complete']
    summary = {'schema_version': 1, 'profile': manifest['profile']['name'], 'cells': cells,
               'completed_cells': len(complete), 'attempted_cells': len(cells),
               'declared_cells': len(manifest['profile']['cells']),
               'authoritative_memory': sys.platform.startswith('linux'),
               'status': 'complete' if len(complete) == len(cells) == len(manifest['profile']['cells']) else 'partial',
               'sample_policy': 'one or more fixed fresh-process warmups; >=5 measured fresh processes per mode; median/range/MAD only'}
    write_json(out / 'summary.json', summary)
    timing_rows, memory_rows, event_rows = [], [], []
    for cell in cells:
        for sample in cell.get('samples', []):
            timing_rows.append({'cell': cell['id'], 'repetition': sample['repetition'], 'mode': sample['mode'],
                'status': sample['process']['status'], 'exit_code': sample['process']['exit_code'],
                'cli_ns': sample['process']['elapsed_ns'], 'core_ns': sample.get('metrics', {}).get('core_processing_ns', ''),
                'simulation_ns': sample.get('simulation_ns', ''), 'result_sha256': sample.get('result_sha256', '')})
            memory_rows.append({'cell': cell['id'], 'repetition': sample['repetition'], 'mode': sample['mode'],
                'status': sample['process']['status'], 'peak_rss_bytes': sample['process']['peak_rss_bytes'],
                'loaded_rss_bytes': sample.get('metrics', {}).get('loaded_rss_bytes', ''),
                'authoritative': sys.platform.startswith('linux')})
            for snap in sample.get('metrics', {}).get('snapshots', []):
                event_rows.append({'cell': cell['id'], 'repetition': sample['repetition'], **snap})
    for name, rows in [('scenario-timings.csv', timing_rows), ('memory.csv', memory_rows), ('event-timings.csv', event_rows)]:
        with (out / name).open('w', newline='') as stream:
            if rows:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
    lines = ['# Measured workload report', '',
             'Core and CLI times are scenario processing, in milliseconds. RSS includes full canonical history.',
             'macOS RSS is provisional; authoritative memory requires Linux. Expected reachability failures count as completed work.', '',
             '| Cell | R/L/P | Events/assertions/destinations | Status | Core median [min,max] ms | CLI median [min,max] ms | Peak RSS median MiB |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    for cell in cells:
        d = cell['dimensions']
        core = cli = mem = '—'
        if cell['status'] == 'complete':
            def fmt(value):
                return f"{value['median'] / 1e6:.3f} [{value['min'] / 1e6:.3f},{value['max'] / 1e6:.3f}]"
            core, cli = fmt(cell['core_ns']), fmt(cell['cli_ns'])
            mem = f"{cell['peak_rss_bytes']['median'] / 1024**2:.2f}"
        lines.append(f"| {cell['id']} | {d['routers']}/{d['physical_links']}/{d['prefixes']} | {d['events']}/{d['assertions']}/{d['analyzed_destinations']} | {cell['status']} | {core} | {cli} | {mem} |")
    lines += ['', 'Actual counters (baseline / snapshot range; logical references include shared sets):', '',
              '| Cell | Route entries | Next-hop references | Applied/no-op events | Assertion evaluations | Destination analyses |',
              '| --- | --- | --- | --- | --- | --- |']
    for cell in complete:
        c = cell['counters']
        lines.append(f"| {cell['id']} | {c['baseline_routes']} / {c['route_range']} | {c['baseline_next_hops']} / {c['next_hop_range']} | {c['applied_events']}/{c['noop_events']} | {c['assertion_evaluations']} | {c['destination_analyses']} |")
    for cell in cells:
        if cell.get('reason'):
            lines += ['', f"{cell['id']}: {cell['reason']}"]
    (out / 'report.md').write_text('\n'.join(lines) + '\n')
    return summary


def execute(profile, binary, out, allow_debug=False):
    profile = validate_profile(profile)
    if out.exists():
        raise ValueError('output directory exists; use a fresh directory')
    out.mkdir(parents=True)
    manifest = {'schema_version': 1, 'profile': profile, 'generator_version': VERSION,
                'prng_algorithm': ALGORITHM, 'host': provenance(binary),
                'cli_boundary': 'fresh process launch through blocking wait4 return; parse, validation, simulation, JSON and file writes; thread scheduling overhead included',
                'instrumentation': 'clock reads per assertion and snapshot; RSS after load/checks; serial instrumented/uninstrumented processes; cache warmed, no fsync'}
    write_json(out / 'manifest.json', manifest)
    if not allow_debug and (manifest['host']['build_cache'].get('CMAKE_BUILD_TYPE') != 'Release' or
                            'sanitize' in json.dumps(manifest['host']['build_cache'])):
        raise ValueError('published benchmarks require an unsanitized Release build; --allow-debug is smoke-only')
    if not allow_debug and manifest['host']['source_inputs'] is None:
        raise ValueError('published benchmarks require the binary CMake cache and source checkout')
    cells = []
    save_summary(out, manifest, cells)
    budget = profile['budgets']
    for config in profile['cells']:
        scenario = generate(config)
        directory = out / config['id']
        directory.mkdir()
        source = directory / 'scenario.json'
        write_json(source, scenario)
        cell = {'id': config['id'], 'config': config, 'dimensions': estimates(scenario),
                'input_file_sha256': sha(source.read_bytes()), 'samples': [], 'warmups': [], 'status': 'pending'}
        cells.append(cell)
        d = cell['dimensions']
        reasons = []
        for field, limit in [('retained_route_upper_bound', min(budget['max_retained_routes'], 2000000)),
                              ('output_bytes_estimate', min(budget['max_output_mib'], 64) * 1024**2),
                              ('rss_bytes_estimate', budget['memory_mib'] * 1024**2),
                              ('spf_work_units', budget['max_spf_work_units'])]:
            if d[field] > limit:
                reasons.append(f'{field}={d[field]} exceeds {limit}')
        # Archive parser-normalized inputs even for budget-skipped cells.
        normalized = run_child([str(binary), 'validate', str(source), '--normalized'], directory / 'normalize',
                               budget['timeout_seconds'], budget['memory_mib'] * 1024**2)
        cell['normalization'] = normalized
        if normalized['status'] == 'interrupted':
            cell.update(status='interrupted', reason='interrupted during input normalization')
            save_summary(out, manifest, cells)
            return 3
        if normalized['status'] != 'complete' or normalized['exit_code'] != 0:
            cell.update(status='invalid_input', reason='generated workload normalization failed: ' + normalized['status'])
            save_summary(out, manifest, cells)
            continue
        normalized_bytes = (directory / 'normalize/stdout.txt').read_bytes()
        (directory / 'normalized.json').write_bytes(normalized_bytes)
        cell['normalized_file_sha256'] = sha(normalized_bytes)
        if reasons:
            cell.update(status='budget_skipped', reason='; '.join(reasons))
            save_summary(out, manifest, cells)
            print(config['id'] + ': budget_skipped', flush=True)
            continue
        hashes = set()
        instrumented, cli_times, peaks = [], [], []
        try:
            for repetition in range(-profile['warmups'], profile['repetitions']):
                for mode in ('instrumented', 'cli'):
                    label = f'{mode}-' + (f'warmup{-repetition}' if repetition < 0 else f'{repetition:03d}')
                    run_dir = directory / label
                    command = [str(binary), 'bench-sample' if mode == 'instrumented' else 'simulate', str(source), '--out', str(run_dir / 'output')]
                    process = run_child(command, run_dir, budget['timeout_seconds'], budget['memory_mib'] * 1024**2)
                    sample = {'repetition': repetition, 'mode': mode, 'process': process}
                    cell['warmups' if repetition < 0 else 'samples'].append(sample)
                    if process['status'] == 'interrupted':
                        raise KeyboardInterrupt
                    if process['status'] != 'complete':
                        raise RuntimeError(f"{label}: {process['status']} (exit {process['exit_code']})")
                    result_path = run_dir / 'output/result.json'
                    result = read_result(result_path)
                    sample['simulation_ns'] = read_result(run_dir / 'output/run.json')['simulation_ns']
                    sample['result_sha256'] = result['canonical_sha256']
                    sample['result_file_sha256'] = sha(result_path.read_bytes())
                    if result_path.stat().st_size > budget['max_output_mib'] * 1024**2:
                        raise RuntimeError('actual result exceeds declared output byte budget')
                    hashes.add(sample['result_file_sha256'])
                    if result['status'] == 'incomplete':
                        raise RuntimeError('incomplete canonical result')
                    if mode == 'instrumented':
                        metrics = json.loads((run_dir / 'output/sample.json').read_text())
                        sample['metrics'] = metrics
                        cell['scenario_sha256'] = metrics['scenario_sha256']
                        if repetition >= 0:
                            instrumented.append(metrics['core_processing_ns'])
                            if repetition == 0:
                                snapshots = metrics['snapshots']
                                cell['counters'] = {
                                    'baseline_routes': snapshots[0]['route_entries'],
                                    'baseline_next_hops': snapshots[0]['next_hop_references'],
                                    'route_range': [min(x['route_entries'] for x in snapshots), max(x['route_entries'] for x in snapshots)],
                                    'next_hop_range': [min(x['next_hop_references'] for x in snapshots), max(x['next_hop_references'] for x in snapshots)],
                                    'applied_events': sum(x['applied'] for x in snapshots[1:]),
                                    'noop_events': sum(not x['applied'] for x in snapshots[1:]),
                                    'assertion_evaluations': sum(x['assertion_evaluations'] for x in snapshots),
                                    'destination_analyses': sum(x['destination_analyses'] for x in snapshots)}
                                cell['counters']['max_ecmp_width'] = max(x['max_ecmp_width'] for x in snapshots)
                    elif repetition >= 0:
                        cli_times.append(process['elapsed_ns'])
                        peaks.append(process['peak_rss_bytes'])
                    # Keep one canonical result; every run keeps its hashes,
                    # run/sample manifests, process record, command and logs.
                    if not (mode == 'instrumented' and repetition == 0):
                        result_path.unlink()
                    save_summary(out, manifest, cells)
            if len(hashes) != 1:
                raise RuntimeError('instrumented/CLI/rerun canonical bytes differ')
            cell.update(status='complete', result_file_sha256=next(iter(hashes)),
                        core_ns=dispersion(instrumented), cli_ns=dispersion(cli_times), peak_rss_bytes=dispersion(peaks))
            for mode in ('instrumented', 'cli'):
                cell[mode + '_simulation_ns'] = dispersion([x['simulation_ns'] for x in cell['samples'] if x['mode'] == mode])
            cell['instrumentation_median_ratio'] = cell['instrumented_simulation_ns']['median'] / cell['cli_simulation_ns']['median']
        except KeyboardInterrupt:
            cell.update(status='interrupted', reason='signal or keyboard interruption; owned child terminated')
            save_summary(out, manifest, cells)
            raise
        except (OSError, ValueError, RuntimeError) as error:
            cell.update(status='failed', reason=str(error))
        save_summary(out, manifest, cells)
        print(config['id'] + ': ' + cell['status'], flush=True)
    summary = save_summary(out, manifest, cells)
    return 0 if summary['status'] == 'complete' else 3


def read_result(path):
    return json.loads(path.read_text())


def main():
    def interrupted(_signal, _frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', default=str(ROOT / 'build/host-release/routeproof'))
    parser.add_argument('--profile', type=Path, required=True, help='strict v1 JSON profile')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--allow-debug', action='store_true', help='smoke tests only; never published performance')
    args = parser.parse_args()
    binary = Path(shutil.which(args.binary) or args.binary).resolve()
    try:
        return execute(read_json(args.profile), binary, args.out.resolve(), args.allow_debug)
    except KeyboardInterrupt:
        print('benchmark interrupted; completed samples/checkpoints preserved', file=sys.stderr)
        return 3
    except (ValueError, OSError) as error:
        print('benchmark: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
