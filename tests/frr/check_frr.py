#!/usr/bin/env python3
"""Offline harness contract checks; no claim of live FRR route agreement."""
import copy
import ipaddress
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/frr'))
from generate import check_image, generate
from normalize import (ObservationError, compare, normalize_kernel,
                       normalize_ospf, normalize_zebra)
import run_lab
import run_matrix
from run_matrix import summary
from compare_runs import compare_runs

BINARY = str(Path(sys.argv.pop(1)).resolve()) if len(sys.argv) > 1 else str(ROOT / 'build/host-debug/routeproof')
# This all-zero digest is an OFFLINE TEST placeholder, never a runnable image pin.
IMAGE = 'quay.io/frrouting/frr@sha256:' + '0' * 64


def canonical(path):
    return json.loads(subprocess.check_output([BINARY, 'validate', str(path), '--normalized'], text=True))


def simulation(path, out):
    result = subprocess.run([BINARY, 'simulate', str(path), '--out', str(out)], capture_output=True, text=True)
    assert result.returncode in (0, 1), result.stderr
    return json.loads((out / 'result.json').read_text())


def oracle(scenario, mapping, routers, links, source):
    """Independent Floyd-Warshall; fake transport data never comes from C++ FIBs."""
    infinity = 10**12
    ids = sorted(mapping['routers'])
    distances = {(a, b): 0 if a == b and a in routers else infinity for a in ids for b in ids}
    arcs = []
    for link in scenario['links']:
        if link['id'] not in links or link['a'] not in routers or link['b'] not in routers:
            continue
        for side, other in (('a', 'b'), ('b', 'a')):
            a, b, cost = link[side], link[other], link[f'cost_{side}{other}']
            distances[a, b] = min(distances[a, b], cost)
            arcs.append((a, b, link['id'], side, other, cost))
    for middle in ids:
        for a in ids:
            for b in ids:
                distances[a, b] = min(distances[a, b], distances[a, middle] + distances[middle, b])
    ospf, zebra, kernel = {'vrfName': 'default'}, {}, []
    for prefix in scenario['prefixes']:
        network, origin = prefix['prefix'], prefix['origin']
        cost = distances[source, origin]
        if cost == infinity:
            continue
        attachment = mapping['prefixes'][network]
        local = source == origin
        if local:
            ohops = [{'ip': ' ', 'directlyAttachedTo': attachment['interface']}]
            zhops = [{'interfaceName': attachment['interface'], 'active': True, 'fib': True}]
            khops = []
        else:
            ohops, zhops, khops = [], [], []
            for a, b, link, side, other, weight in arcs:
                if a == source and weight + distances[b, origin] == cost:
                    info = mapping['links'][link]
                    interface, gateway = info[side]['interface'], info[other]['address']
                    ohops.append({'via': interface, 'ip': gateway})
                    zhops.append({'interfaceName': interface, 'ip': gateway, 'active': True, 'fib': True})
                    khops.append({'dev': interface, 'gateway': gateway, 'flags': []})
        ospf[network] = {'routeType': 'N', 'area': '0.0.0.0', 'cost': cost + prefix['stub_cost'], 'nexthops': ohops}
        host = ipaddress.IPv4Network(network).prefixlen == 32
        zebra[network] = [{'prefix': network, 'vrfId': 0, 'protocol': ('local' if host else 'connected') if local else 'ospf',
                          'selected': True, 'installed': True, 'metric': 0 if local else cost + prefix['stub_cost'],
                          'nexthops': zhops}]
        if local:
            kernel.append({'dst': network, 'dev': attachment['interface'],
                           **({'type': 'local', 'table': 'local'} if host else {})})
        else:
            kernel.append({'dst': network, 'nexthops': khops})
    return {'ospf': ospf, 'zebra': zebra, 'kernel': kernel}


class Clock:
    def __init__(self):
        self.now = 0
    def clock(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


class FakeCommands:
    """Stateful Docker/FRR transport for event and cleanup failure injection."""
    def __init__(self, scenario, mapping, fail_deploy=False, fail_cleanup=False, stale=False):
        self.scenario, self.mapping = scenario, mapping
        self.calls, self.states = [], {}
        self.fail_deploy, self.fail_cleanup, self.stale = fail_deploy, fail_cleanup, stale
        self.deployed = False
        self.deadline = None
        self.routers, self.links = run_lab.initial_state(scenario)
        self.base_routers, self.base_links = self.routers.copy(), self.links.copy()

    def run(self, argv, allowed=(0,)):
        self.calls.append(argv)
        if argv[:2] == ['containerlab', 'deploy']:
            self.deployed = True
            if self.fail_deploy:
                raise run_lab.CommandError('partial deploy failed')
        if argv[:2] == ['containerlab', 'destroy']:
            if self.fail_cleanup:
                raise run_lab.CommandError('cleanup failed')
            self.deployed = False
        if argv[:2] == ['docker', 'ps']:
            return '\n'.join(i['container'] for i in self.mapping['routers'].values()) if self.deployed else ''
        if argv[:3] == ['docker', 'network', 'ls']:
            return self.mapping['lab_name'] + '-mgmt' if self.deployed else ''
        if argv[:2] == ['docker', 'exec'] and argv[3:6] == ['ip', 'link', 'set']:
            info = next((rid for rid, value in self.mapping['routers'].items() if value['container'] == argv[2]))
            self.states[info, argv[7]] = argv[8] == 'up'
        return ''

    def json(self, argv):
        self.calls.append(argv)
        if argv[:2] == ['docker', 'inspect']:
            return [{'Config': {'Labels': {'routeproof.run': self.mapping['lab_name']}}}]
        rid = next(rid for rid, value in self.mapping['routers'].items() if value['container'] == argv[2])
        query = argv[3:]
        if query == ['ip', '-j', 'link', 'show']:
            return [{'ifname': interface, 'flags': ['UP'] if up else []} for (router, interface), up in self.states.items() if router == rid]
        if query == ['vtysh', '-c', 'show ip ospf neighbor json']:
            neighbors = {}
            for other, interface, address in run_lab.expected_neighbors(rid, self.mapping, self.routers, self.links):
                neighbors.setdefault(other, []).append({'converged': 'Full', 'ifaceName': interface + ':local', 'ifaceAddress': address})
            return {'neighbors': neighbors}
        if query == ['vtysh', '-c', 'show ip ospf database router json']:
            return {'areas': {}}
        routers, links = (self.base_routers, self.base_links) if self.stale else (self.routers, self.links)
        raw = oracle(self.scenario, self.mapping, routers, links, rid)
        if query == ['vtysh', '-c', 'show ip ospf route json']:
            return raw['ospf']
        if query == ['vtysh', '-c', 'show ip route json']:
            return raw['zebra']
        if query == ['ip', '-j', '-4', 'route', 'show', 'table', 'all']:
            return raw['kernel']
        raise AssertionError(argv)


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.scenario = canonical(ROOT / 'examples/diamond-failures.yaml')
        self.mapping = generate(self.scenario, self.directory / 'lab', IMAGE, 'rp-offline')
        self.result = simulation(ROOT / 'examples/diamond-failures.yaml', self.directory / 'engine')

    def tearDown(self):
        self.temp.cleanup()

    def test_raw_normalization_hand_calculated(self):
        raw = json.loads((ROOT / 'tests/frr/fixtures/diamond-a.json').read_text())
        observation = {plane: function('a', raw[plane], self.mapping) for plane, function in
                       [('ospf', normalize_ospf), ('zebra', normalize_zebra), ('kernel', normalize_kernel)]}
        for plane, rows in observation.items():
            self.assertEqual(len(rows), 1)
            self.assertEqual([h['link'] for h in rows[0]['next_hops']], ['ab', 'ac'])
            if plane != 'kernel':
                self.assertEqual(rows[0]['metric'], 3)
        with self.assertRaises(ObservationError):
            changed = copy.deepcopy(raw['zebra'])
            changed['10.10.4.0/24'][0]['nexthops'][0]['fib'] = False
            normalize_zebra('a', changed, self.mapping)
        with self.assertRaises(ObservationError):
            changed = copy.deepcopy(raw['ospf'])
            changed['10.10.4.0/24']['nexthops'][0]['ip'] = '192.0.2.1'
            normalize_ospf('a', changed, self.mapping)
        for function, plane in [(normalize_ospf, 'ospf'), (normalize_zebra, 'zebra')]:
            with self.assertRaises(ObservationError):
                changed = copy.deepcopy(raw[plane])
                changed['10.99.0.0/24'] = changed['10.10.4.0/24']
                function('a', changed, self.mapping)
        with self.assertRaises(ObservationError):
            normalize_ospf('a', [], self.mapping)
        with self.assertRaises(ObservationError):
            changed = copy.deepcopy(raw['ospf'])
            changed['10.10.4.0/24']['nexthops'] *= 2
            normalize_ospf('a', changed, self.mapping)

    def observations(self, snapshot):
        routers, links = set(snapshot['available_routers']), set(snapshot['administratively_up_links'])
        result = {}
        for router in self.mapping['routers']:
            if router not in routers:
                result[router] = {'status': 'unavailable'}
            else:
                raw = oracle(self.scenario, self.mapping, routers, links, router)
                result[router] = {'status': 'available',
                                 'ospf': normalize_ospf(router, raw['ospf'], self.mapping),
                                 'zebra': normalize_zebra(router, raw['zebra'], self.mapping),
                                 'kernel': normalize_kernel(router, raw['kernel'], self.mapping)}
        return result

    def test_route_envelopes_cannot_become_successful_absence(self):
        raw = json.loads((ROOT / 'tests/frr/fixtures/diamond-a.json').read_text())
        # At origin-down every available router expects route absence. These
        # wrappers used to hide stale rows and let all nine slots pass.
        for name, function in [('ospf', normalize_ospf), ('zebra', normalize_zebra)]:
            for value in [{'error': 'daemon unavailable'}, {'default': raw[name]},
                          {'vrfs': {'default': raw[name]}}, {'routes': raw[name]}]:
                with self.subTest(plane=name, envelope=value):
                    with self.assertRaises(ObservationError):
                        function('a', value, self.mapping)
            self.assertEqual(function('a', {}, self.mapping), [])
        valid = {**raw['ospf'], 'vrfId': 0, '0.0.0.2': {'routeType': 'R '}}
        self.assertEqual(len(normalize_ospf('a', valid, self.mapping)), 1)
        for key, value in [('vrfName', 'other'), ('vrfId', True), ('ospfInstance', 1),
                           ('0.0.0.2', {'routeType': 'N'})]:
            with self.subTest(field=key):
                with self.assertRaises(ObservationError):
                    normalize_ospf('a', {key: value}, self.mapping)

    def test_generated_kernel_routes_require_inline_next_hops(self):
        for info in self.mapping['routers'].values():
            config = (self.directory / 'lab' / info['node'] / 'frr.conf').read_text()
            self.assertIn('\nno zebra nexthop kernel enable\n', config)
        with self.assertRaisesRegex(ObservationError, 'kernel nhid observed'):
            normalize_kernel('a', [{'dst': '10.10.4.0/24', 'nhid': 42, 'protocol': 'ospf'}], self.mapping)

    def test_host_prefix_local_delivery_across_all_snapshots(self):
        scenario = copy.deepcopy(self.scenario)
        scenario['prefixes'][0]['prefix'] = '10.10.4.1/32'
        source = self.directory / 'host-prefix.json'
        source.write_text(json.dumps(scenario))
        scenario = canonical(source)
        output = self.directory / 'host'
        output.mkdir()
        mapping = generate(scenario, output / 'lab', IMAGE, 'rp-host')
        result = simulation(source, output / 'engine')
        fake = FakeCommands(scenario, mapping)
        report = self.execute_fake(scenario, mapping, result, output, fake)
        self.assertEqual((report['status'], report['completed_snapshots']), ('pass', 6), report)
        routers, links = run_lab.initial_state(scenario)
        raw = oracle(scenario, mapping, routers, links, 'd')
        prefix = scenario['prefixes'][0]['prefix']
        self.assertEqual(normalize_zebra('d', raw['zebra'], mapping)[0]['kind'], 'connected')
        local = {**raw['kernel'][0], 'dst': '10.10.4.1'}
        main = {'dst': prefix, 'dev': mapping['prefixes'][prefix]['interface'], 'table': 254}
        # Both tables can contain the same /32; duplicate rows within either
        # table, extra gateways, and local delivery at a remote router must fail.
        for rows in ([local], [main], [local, main], [main, local]):
            self.assertEqual(len(normalize_kernel('d', rows, mapping)), 1)
        for rows in ([local, local], [local, main, local], [{**local, 'dev': 'eth1'}],
                     [{**main, 'gateway': '198.18.0.1'}], [{**local, 'table': 'main'}]):
            with self.subTest(rows=rows):
                with self.assertRaises(ObservationError):
                    normalize_kernel('d', rows, mapping)
        for changed in ('router', 'interface', 'gateway', 'mask'):
            table = copy.deepcopy(raw['zebra'])
            owner = 'd'
            if changed == 'router':
                owner = 'a'
            elif changed == 'interface':
                table[prefix][0]['nexthops'][0]['interfaceName'] = 'eth1'
            elif changed == 'gateway':
                table[prefix][0]['nexthops'][0]['ip'] = '198.18.0.1'
            else:
                table = {'10.10.4.0/24': {**table[prefix][0], 'prefix': '10.10.4.0/24'}}
                table['10.10.4.0/24'] = [table['10.10.4.0/24']]
            with self.subTest(invalid_local=changed):
                with self.assertRaises(ObservationError):
                    normalize_zebra(owner, table, self.mapping if changed == 'mask' else mapping)
        with self.assertRaises(ObservationError):
            normalize_kernel('a', [local], mapping)

    def test_comparison_all_slots_missing_extra_cost_and_ecmp(self):
        snapshot = self.result['snapshots'][0]
        observations = self.observations(snapshot)
        result = compare(snapshot, observations, self.mapping)
        self.assertEqual((result['status'], result['comparison_slots']), ('pass', 12))
        changed = copy.deepcopy(observations)
        changed['a']['ospf'][0]['metric'] = 999
        self.assertEqual(compare(snapshot, changed, self.mapping)['mismatches'][0]['reason'], 'route_mismatch')
        changed = copy.deepcopy(observations)
        changed['a']['zebra'][0]['next_hops'].pop()
        self.assertEqual(compare(snapshot, changed, self.mapping)['status'], 'fail')
        changed = copy.deepcopy(observations)
        changed['a']['kernel'].clear()
        self.assertEqual(compare(snapshot, changed, self.mapping)['mismatches'][0]['reason'], 'missing_route')
        partition = self.result['snapshots'][2]
        changed = self.observations(partition)
        changed['a']['ospf'] = observations['a']['ospf']
        self.assertEqual(compare(partition, changed, self.mapping)['mismatches'][0]['reason'], 'extra_route')
        down = self.result['snapshots'][4]
        changed = self.observations(down)
        self.assertEqual(compare(down, changed, self.mapping)['unavailable_routers'], ['d'])
        changed['d'] = {'status': 'available', 'ospf': [], 'zebra': [], 'kernel': []}
        with self.assertRaises(ObservationError):
            compare(down, changed, self.mapping)
        changed = self.observations(snapshot)
        del changed['a']
        with self.assertRaises(ObservationError):
            compare(snapshot, changed, self.mapping)

    def test_stability_reset_deadline_and_stable_mismatch(self):
        clock = Clock()
        observations = iter([{'route': 'old'}, {'route': 'new'}, {'route': 'new'}, {'route': 'new'}])
        directory = self.directory / 'stable'
        directory.mkdir()
        def observe(target):
            target.mkdir()
            return next(observations)
        value, metadata = run_lab.wait_stable(observe, directory, 8, 1, 2, 3, clock.clock, clock.sleep)
        self.assertEqual(value, {'route': 'new'})
        self.assertEqual(metadata['polls'], 4)
        clock = Clock()
        directory = self.directory / 'timeout'
        directory.mkdir()
        def broken(target):
            target.mkdir()
            raise ObservationError('post-event adjacency still stale')
        with self.assertRaises(run_lab.InfrastructureError):
            run_lab.wait_stable(broken, directory, 3, 1, 1, 2, clock.clock, clock.sleep)
        self.assertEqual(len(list(directory.glob('poll-*/error.json'))), 3)

    def test_event_noop_and_restoration(self):
        routers, links = run_lab.initial_state(self.scenario)
        self.assertTrue(run_lab.mutate({'type': 'link_down', 'link': 'cd'}, routers, links))
        self.assertFalse(run_lab.mutate({'type': 'link_down', 'link': 'cd'}, routers, links))
        run_lab.mutate({'type': 'router_down', 'router': 'd'}, routers, links)
        self.assertFalse(any(up for (rid, _), up in run_lab.interface_states(self.mapping, routers, links).items() if rid == 'd'))
        run_lab.mutate({'type': 'router_up', 'router': 'd'}, routers, links)
        states = run_lab.interface_states(self.mapping, routers, links)
        self.assertFalse(states['d', self.mapping['links']['cd']['b']['interface']])
        self.assertTrue(states['d', self.mapping['links']['bd']['b']['interface']])

    def execute_fake(self, scenario, mapping, result, output, commands):
        options = SimpleNamespace(timeout=10, poll_interval=1, stable_window=1, stable_polls=2)
        original_apply = run_lab.apply_state
        original_wait = run_lab.wait_stable
        def apply(m, routers, links, cmd):
            cmd.routers, cmd.links = routers.copy(), links.copy()
            original_apply(m, routers, links, cmd)
        def wait(*args):
            clock = Clock()
            return original_wait(*args, clock=clock.clock, sleep=clock.sleep)
        with patch.object(run_lab, 'environment', return_value={'fake_transport': True}), \
             patch.object(run_lab, 'initialize'), patch.object(run_lab, 'apply_state', side_effect=apply), \
             patch.object(run_lab, 'wait_stable', side_effect=wait):
            return run_lab.execute_live(scenario, mapping, result, output, commands, options)

    def test_partial_deploy_and_cleanup_failure_are_incomplete(self):
        for kind in ('deploy', 'cleanup'):
            with self.subTest(kind=kind):
                output = self.directory / kind
                output.mkdir()
                fake = FakeCommands(self.scenario, self.mapping, fail_deploy=kind == 'deploy', fail_cleanup=kind == 'cleanup')
                report = self.execute_fake(self.scenario, self.mapping, self.result, output, fake)
                self.assertEqual(report['status'], 'incomplete')
                self.assertTrue(any(call[:2] == ['containerlab', 'destroy'] for call in fake.calls))
                self.assertEqual(report['cleanup'], 'complete' if kind == 'deploy' else 'failed')

    def test_stable_stale_routes_fail_instead_of_being_accepted_or_timing_out(self):
        output = self.directory / 'stale'
        output.mkdir()
        fake = FakeCommands(self.scenario, self.mapping, stale=True)
        report = self.execute_fake(self.scenario, self.mapping, self.result, output, fake)
        self.assertEqual(report['status'], 'fail')
        self.assertEqual(report['completed_snapshots'], 6)
        self.assertEqual(report['cleanup'], 'complete')
        self.assertGreater(sum(len(s['mismatches']) for s in report['snapshots']), 0)

    def test_cleanup_refuses_unowned_resources(self):
        fake = FakeCommands(self.scenario, self.mapping)
        fake.deployed = True
        with patch.object(fake, 'json', return_value=[{'Config': {'Labels': {'routeproof.run': 'other-run'}}}]):
            with self.assertRaises(ObservationError):
                run_lab.cleanup(self.mapping, self.directory / 'lab/topology.clab.json', fake)
        self.assertFalse(any(call[:2] == ['containerlab', 'destroy'] for call in fake.calls))

    def test_matrix_all_profiles_and_generated_config_semantics(self):
        matrix = json.loads((ROOT / 'labs/profiles/matrix.json').read_text())
        self.assertEqual(len(matrix['profiles']), 5)
        snapshots = slots = 0
        cells = []
        for profile in matrix['profiles']:
            for index, source in enumerate(profile['scenarios']):
                with self.subTest(scenario=source):
                    scenario = canonical(ROOT / source)
                    output = self.directory / f"{profile['id']}-{index}"
                    output.mkdir()
                    mapping = generate(scenario, output / 'lab', IMAGE, 'rp-offline')
                    result = simulation(ROOT / source, output / 'engine')
                    # Independent config sanity check: read the emitted commands,
                    # validate costs/address families/passive attachment masks.
                    for router in scenario['routers']:
                        config = (output / 'lab' / mapping['routers'][router['id']]['node'] / 'frr.conf').read_text()
                        self.assertIn(f"ospf router-id {router['router_id']}", config)
                        self.assertIn('maximum-paths 64', config)
                        self.assertIn('\nno zebra nexthop kernel enable\n', config)
                        for link in scenario['links']:
                            for side, peer in (('a', 'b'), ('b', 'a')):
                                if link[side] == router['id']:
                                    endpoint = mapping['links'][link['id']][side]
                                    block = config.split(f"interface {endpoint['interface']}\n")[1].split('!')[0]
                                    self.assertIn(f"ip ospf cost {link[f'cost_{side}{peer}']}", block)
                                    self.assertIn('ip ospf network point-to-point', block)
                                    self.assertEqual(ipaddress.IPv4Interface(endpoint['address'] + '/30').network,
                                                     ipaddress.IPv4Network(mapping['links'][link['id']]['subnet']))
                        for prefix in scenario['prefixes']:
                            if prefix['origin'] == router['id']:
                                attachment = mapping['prefixes'][prefix['prefix']]
                                block = config.split(f"interface {attachment['interface']}\n")[1].split('!')[0]
                                self.assertIn('ip ospf passive', block)
                                self.assertIn(f"ip ospf cost {prefix['stub_cost']}", block)
                                self.assertEqual(str(ipaddress.IPv4Interface(attachment['address']).network), prefix['prefix'])
                    fake = FakeCommands(scenario, mapping)
                    report = self.execute_fake(scenario, mapping, result, output, fake)
                    self.assertEqual(report['status'], 'pass', report)
                    self.assertEqual(report['completed_snapshots'], len(scenario['events']) + 1)
                    self.assertEqual(report['cleanup'], 'complete')
                    cells.append({'profile': profile['id'], 'scenario': source, 'exit_code': 0, 'report': report})
                    snapshots += report['completed_snapshots']
                    slots += report['comparison_slots']
        self.assertEqual(snapshots, 27)
        self.assertEqual(slots, 687)
        # Transport reports without real provenance cannot satisfy the gate.
        first = summary(cells, 5, 6)
        self.assertEqual(compare_runs(first, first)['status'], 'incomplete')
        # Synthetic provenance contracts are used only inside these temporary
        # unit tests; they are not exported as live evidence.
        for index, cell in enumerate(first['cells']):
            cell['manifest'] = {
                'schema_version': 1, 'mode': 'live', 'platform': 'linux/amd64', 'frr_version': '10.2.1',
                'image': IMAGE, 'image_pin_status': 'provided_digest', 'lab_name': f'rp-first-{index}',
                'git_revision': '1' * 40, 'git_status': '', 'source_root': '/test/first',
                'binary_path': '/test/first/build/host-debug/routeproof', 'binary_sha256': '2' * 64,
                'source_hashes': {'test-source': '3' * 64}, 'generated_hashes': {'test-config': '4' * 64},
                'scenario_sha256': '5' * 64, 'result_sha256': '6' * 64}
            cell['report']['environment'] = {
                'system': 'Linux', 'architecture': 'x86_64', 'kernel': 'test-kernel',
                'containerlab': 'test-version', 'docker': {'Server': {'Version': 'test-version'}},
                'image': {'Architecture': 'amd64', 'Os': 'linux', 'RepoDigests': [IMAGE]}}
        second = copy.deepcopy(first)
        for index, cell in enumerate(second['cells']):
            cell['manifest'].update(lab_name=f'rp-second-{index}', source_root='/test/second',
                                    binary_path='/test/second/build/host-debug/routeproof', binary_sha256='7' * 64)
        second['cells'][0]['report']['snapshots'][0]['stability'] = {'polls': 999}
        self.assertEqual(compare_runs(first, second)['status'], 'pass')
        self.assertEqual(compare_runs(first, first)['status'], 'incomplete')
        for invalid in (None, [], {'status': 'pass'}):
            self.assertEqual(compare_runs(first, invalid)['status'], 'incomplete')
        for kind in ('dirty', 'nonlive', 'missing', 'image', 'source', 'environment', 'coverage', 'duplicate'):
            changed = copy.deepcopy(second)
            cell = changed['cells'][0]
            if kind == 'dirty':
                cell['manifest']['git_status'] = ' M README.md\n'
            elif kind == 'nonlive':
                cell['manifest']['mode'] = 'generate_only'
            elif kind == 'missing':
                del cell['manifest']
            elif kind == 'image':
                cell['report']['environment']['image']['RepoDigests'] = []
            elif kind == 'source':
                for value in changed['cells']:
                    value['manifest']['source_hashes']['test-source'] = '8' * 64
            elif kind == 'environment':
                cell['report']['environment'] = {'fake_transport': True}
            elif kind == 'coverage':
                cell['report']['snapshots'].pop()
            else:
                cell['report']['snapshots'][1] = copy.deepcopy(cell['report']['snapshots'][0])
            with self.subTest(rerun_rejection=kind):
                self.assertEqual(compare_runs(first, changed)['status'], 'incomplete')
        dirty_first = copy.deepcopy(first)
        for cell in dirty_first['cells']:
            cell['manifest']['git_status'] = ' M README.md\n'
        self.assertEqual(compare_runs(dirty_first, second)['status'], 'pass')
        changed = copy.deepcopy(second)
        changed['cells'][0]['report']['snapshots'][0]['snapshot_sha256'] = '0' * 64
        self.assertEqual(compare_runs(first, changed)['status'], 'fail')
        changed = copy.deepcopy(second)
        changed['cells'][0]['manifest']['result_sha256'] = '0' * 64
        self.assertEqual(compare_runs(first, changed)['status'], 'fail')
        changed['status'] = 'skipped'
        self.assertEqual(compare_runs(first, changed)['status'], 'incomplete')

    def test_generation_is_deterministic_and_rejects_invalid_pins(self):
        first = json.dumps(self.mapping, sort_keys=True)
        other = generate(self.scenario, self.directory / 'second', IMAGE, 'rp-offline')
        self.assertEqual(first, json.dumps(other, sort_keys=True))
        for image in ('quay.io/frrouting/frr:latest', 'quay.io/frrouting/frr:10.2.1', 'bad@sha256:ABC'):
            with self.assertRaises(ValueError):
                check_image(image)
        changed = copy.deepcopy(self.scenario)
        changed['prefixes'][0]['prefix'] = '198.18.0.0/15'
        with self.assertRaises(ValueError):
            generate(changed, self.directory / 'overlap', IMAGE, 'rp-offline')

    def test_cli_generation_invalid_input_and_preserved_artifacts(self):
        output = self.directory / 'cli'
        argv = [sys.executable, str(ROOT / 'tools/frr/run_lab.py'), '--scenario',
                str(ROOT / 'labs/profiles/pair.json'), '--routeproof', BINARY,
                '--generate-only', '--out', str(output)]
        process = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 3, process.stderr)
        report = (output / 'report.json').read_bytes()
        self.assertEqual(json.loads(report)['status'], 'skipped')
        self.assertEqual(json.loads((output / 'manifest.json').read_text())['image_pin_status'], 'unverified_candidate')
        self.assertEqual(json.loads((output / 'manifest.json').read_text())['source_root'], str(ROOT))
        process = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 2)
        self.assertEqual((output / 'report.json').read_bytes(), report)
        invalid = argv.copy()
        invalid[invalid.index(str(ROOT / 'labs/profiles/pair.json'))] = str(ROOT / 'examples/input/invalid/unknown-field.yaml')
        invalid[invalid.index(str(output))] = str(self.directory / 'invalid')
        process = subprocess.run(invalid, capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 2)
        self.assertEqual(json.loads((self.directory / 'invalid/report.json').read_text())['status'], 'invalid')
        invalid = argv + ['--timeout', 'nan']
        self.assertEqual(subprocess.run(invalid, capture_output=True, timeout=30).returncode, 2)
        matrix_output = self.directory / 'cli-matrix'
        process = subprocess.run([sys.executable, str(ROOT / 'tools/frr/run_matrix.py'),
                                  '--generate-only', '--routeproof', BINARY, '--out', str(matrix_output)],
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 3, process.stderr)
        matrix = json.loads((matrix_output / 'matrix-report.json').read_text())
        self.assertEqual((matrix['status'], len(matrix['cells'])), ('skipped', 6))
        for cell in matrix['cells']:
            self.assertEqual(cell['manifest']['mode'], 'generate_only')
            self.assertEqual(cell['manifest']['source_root'], str(ROOT))
        self.assertEqual(compare_runs(matrix, matrix)['status'], 'incomplete')

    def test_initial_unavailability_and_administrative_restoration(self):
        source = ROOT / 'examples/replay/initial-down-restoration.json'
        scenario = canonical(source)
        output = self.directory / 'initial'
        output.mkdir()
        mapping = generate(scenario, output / 'lab', IMAGE, 'rp-initial')
        result = simulation(source, output / 'engine')
        fake = FakeCommands(scenario, mapping)
        report = self.execute_fake(scenario, mapping, result, output, fake)
        self.assertEqual(report['status'], 'pass', report)
        self.assertTrue(any(action['disposition'] == 'noop' for action in report['event_actions']))

    def test_zero_links_and_long_model_ids_do_not_break_generation(self):
        scenario = canonical(ROOT / 'examples/routing/single-router.json')
        # Single-router/zero-link generation must not scan/retain an entire pool.
        mapping = generate(scenario, self.directory / 'single', IMAGE, 'rp-single')
        self.assertEqual(mapping['links'], {})
        changed = copy.deepcopy(self.scenario)
        old, new = changed['routers'][0]['id'], 'router-' + 'x' * 55
        changed['routers'][0]['id'] = new
        for link in changed['links']:
            for side in ('a', 'b'):
                if link[side] == old:
                    link[side] = new
        # Assertions/events are irrelevant to this generation-level boundary.
        changed['assertions'] = []
        mapping = generate(changed, self.directory / 'long', IMAGE, 'rp-long')
        self.assertTrue(all(len(interface) <= 15 for interface in mapping['routers'][new]['interfaces']))
        transit = [ipaddress.IPv4Network(link['subnet']) for link in mapping['links'].values()]
        self.assertTrue(all(not ipaddress.IPv4Network(mapping['management_subnet']).overlaps(n) for n in transit))

    def test_command_failures_preserve_raw_evidence(self):
        commands = run_lab.Commands(self.directory / 'commands', timeout=1)
        with self.assertRaises(run_lab.CommandError):
            commands.run([sys.executable, '-c', "import sys; print('raw-output'); sys.exit(7)"])
        record = json.loads((self.directory / 'commands/000001.json').read_text())
        self.assertEqual(record['returncode'], 7)
        self.assertIn('raw-output', record['stdout'])
        commands.deadline = 0
        with self.assertRaises(run_lab.CommandError):
            commands.run([sys.executable, '-c', 'print(0)'])

    def test_summary_never_turns_skips_or_errors_into_passes(self):
        self.assertEqual(summary([{'report': {'status': 'skipped'}}], 5, 1)['status'], 'skipped')
        self.assertEqual(summary([{'report': {'status': 'incomplete'}}], 5, 1)['status'], 'incomplete')
        self.assertEqual(summary([{'report': {'status': 'pass'}}], 5, 2)['status'], 'incomplete')

    def test_matrix_timeout_retains_partial_comparisons_and_cleanup(self):
        output = self.directory / 'matrix-timeout'
        output.mkdir()
        partial = {'status': 'incomplete', 'cleanup': 'complete', 'completed_snapshots': 1,
                   'comparison_slots': 12, 'matched_slots': 11,
                   'snapshots': [{'status': 'fail', 'mismatches': [{'reason': 'missing_route'}]}]}
        (output / 'report.json').write_text(json.dumps(partial))
        (output / 'manifest.json').write_text(json.dumps({'lab_name': 'rp-partial'}))
        child = Mock(returncode=3)
        child.poll.return_value = None
        child.communicate.side_effect = [subprocess.TimeoutExpired(['runner'], 1), ('raw stdout', 'raw stderr')]
        with patch.object(run_matrix.subprocess, 'Popen', return_value=child):
            cell, interrupted = run_matrix.collect_cell(['runner'], output, timeout=1)
        self.assertFalse(interrupted)
        child.terminate.assert_called_once()
        child.kill.assert_not_called()
        self.assertEqual(cell['exit_code'], 3)
        self.assertEqual(cell['report']['snapshots'], partial['snapshots'])
        self.assertEqual(cell['report']['comparison_slots'], 12)
        self.assertEqual(cell['report']['cleanup'], 'complete')
        self.assertEqual(cell['manifest']['lab_name'], 'rp-partial')
        self.assertEqual(cell['stderr'], 'raw stderr')
        # A broken manifest cannot erase already-readable comparison evidence.
        (output / 'manifest.json').write_text('[]')
        child = Mock(returncode=3)
        child.communicate.return_value = ('', '')
        with patch.object(run_matrix.subprocess, 'Popen', return_value=child):
            cell, _ = run_matrix.collect_cell(['runner'], output)
        self.assertEqual(cell['report']['snapshots'], partial['snapshots'])
        self.assertEqual(cell['report']['comparison_slots'], 12)
        self.assertIn('expected an evidence object', cell['report']['evidence_error'])

    def test_matrix_forced_kill_and_inconsistent_exit_cannot_pass(self):
        output = self.directory / 'matrix-kill'
        output.mkdir()
        (output / 'report.json').write_text(json.dumps({'status': 'pass', 'cleanup': 'complete'}))
        (output / 'manifest.json').write_text('{}')
        child = Mock(returncode=-9)
        child.poll.return_value = None
        child.communicate.side_effect = [subprocess.TimeoutExpired(['runner'], 1),
                                         subprocess.TimeoutExpired(['runner'], 180), ('', '')]
        with patch.object(run_matrix.subprocess, 'Popen', return_value=child):
            cell, _ = run_matrix.collect_cell(['runner'], output, timeout=1)
        child.kill.assert_called_once()
        self.assertEqual((cell['report']['status'], cell['report']['cleanup']), ('incomplete', 'unknown'))
        child = Mock(returncode=3)
        child.communicate.return_value = ('', '')
        with patch.object(run_matrix.subprocess, 'Popen', return_value=child):
            cell, _ = run_matrix.collect_cell(['runner'], output)
        self.assertEqual(cell['report']['status'], 'incomplete')
        self.assertIn('exit code', cell['report']['orchestration_error'])

    def test_matrix_sigterm_waits_for_child_cleanup_and_saves_evidence(self):
        self.check_matrix_signal(signal.SIGTERM)

    def test_matrix_process_group_signals_do_not_interrupt_cleanup(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=signum):
                self.check_matrix_signal(signum, process_group=True)

    def test_matrix_signals_during_cleanup_preserve_evidence(self):
        for timeout in (False, True):
            for signum in (signal.SIGINT, signal.SIGTERM):
                with self.subTest(timeout=timeout, signal=signum):
                    self.check_matrix_signal(signum, during_cleanup=True, timeout=timeout)

    def test_matrix_forced_kill_retains_real_checkpoint_totals(self):
        output = self.directory / 'matrix-checkpoint'
        output.mkdir()
        checkpoints = []
        original_write = run_lab.write_json
        def record(path, value):
            if path == output / 'report.json' and value['cleanup'] == 'not_started':
                checkpoints.append(copy.deepcopy(value))
            original_write(path, value)
        fake = FakeCommands(self.scenario, self.mapping)
        with patch.object(run_lab, 'write_json', side_effect=record):
            self.execute_fake(self.scenario, self.mapping, self.result, output, fake)
        self.assertEqual(len(checkpoints), 6)
        for checkpoint in checkpoints:
            self.assertEqual(checkpoint['completed_snapshots'], len(checkpoint['snapshots']))
            self.assertEqual(checkpoint['comparison_slots'], sum(s['comparison_slots'] for s in checkpoint['snapshots']))
            self.assertEqual(checkpoint['matched_slots'], sum(s['matched_slots'] for s in checkpoint['snapshots']))
            self.assertEqual(checkpoint['passing_snapshots'], sum(s['status'] == 'pass' for s in checkpoint['snapshots']))
        (output / 'report.json').write_text(json.dumps(checkpoints[-1]))
        (output / 'manifest.json').write_text(json.dumps({'lab_name': 'rp-checkpoint'}))
        child = Mock(returncode=-9)
        child.poll.return_value = None
        child.communicate.side_effect = [subprocess.TimeoutExpired(['runner'], 1),
                                         subprocess.TimeoutExpired(['runner'], 180), ('', '')]
        with patch.object(run_matrix.subprocess, 'Popen', return_value=child):
            cell, interrupted = run_matrix.collect_cell(['runner'], output, timeout=1)
        self.assertFalse(interrupted)
        child.kill.assert_called_once()
        report = summary([cell], 1, 1)
        self.assertEqual((report['status'], cell['report']['cleanup']), ('incomplete', 'unknown'))
        self.assertEqual((report['completed_snapshots'], report['passing_snapshots']), (6, 6))
        self.assertEqual((report['comparison_slots'], report['matched_slots']), (69, 69))
        self.assertEqual(cell['report']['snapshots'], checkpoints[-1]['snapshots'])

    def check_matrix_signal(self, signum, process_group=False, during_cleanup=False, timeout=False):
        temporary = tempfile.TemporaryDirectory(dir=self.directory)
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        root = directory / 'signal-root'
        (root / 'tools/frr').mkdir(parents=True)
        (root / 'labs/profiles').mkdir(parents=True)
        (root / 'labs/profiles/matrix.json').write_text(json.dumps(
            {'profiles': [{'id': 'pair', 'scenarios': ['pair.json', 'later.json']}]}))
        # Exercise the real execute_live exception, checkpoint, and cleanup
        # paths. Only the transport and its cleanup work are simulated.
        (root / 'tools/frr/run_lab.py').write_text(f'''import argparse, json, os, signal, sys, time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, {str(ROOT / 'tools/frr')!r})
import run_lab
p = argparse.ArgumentParser()
p.add_argument('--out', type=Path)
a, _ = p.parse_known_args()
a.out.mkdir()
signal.signal(signal.SIGTERM, run_lab.handle_termination)
(a.out / 'pid').write_text(str(os.getpid()))
(a.out / 'manifest.json').write_text(json.dumps({{'lab_name': 'rp-signal'}}))
class Commands:
    deadline = None
    def run(self, argv):
        return ''
def wait(*args):
    if (a.out / 'report.json').exists():
        (a.out / 'ready').touch()
        while True:
            time.sleep(0.01)
    return {{}}, {{}}
def cleanup(*args):
    (a.out / 'cleanup-started').touch()
    time.sleep(0.6)
    (a.out / 'resources-removed').touch()
run_lab.environment = lambda *args: {{}}
run_lab.check_fresh = lambda *args: None
run_lab.initialize = lambda *args: None
run_lab.apply_state = lambda *args: None
run_lab.wait_stable = wait
run_lab.compare = lambda *args: {{'status': 'pass', 'comparison_slots': 12, 'matched_slots': 12}}
run_lab.cleanup = cleanup
scenario = {{'routers': [], 'links': [], 'events': []}}
snapshots = [{{'id': name, 'sequence': index, 'available_routers': [], 'administratively_up_links': []}}
             for index, name in enumerate(('baseline', 'pending'))]
options = SimpleNamespace(timeout=10, poll_interval=1, stable_window=1, stable_polls=2)
report = run_lab.execute_live(scenario, {{'image': 'unused'}}, {{'snapshots': snapshots}}, a.out, Commands(), options)
sys.exit(3 if report['status'] == 'incomplete' else 0)
''')
        output = directory / 'signal-output'
        code = ('import sys; from pathlib import Path; '
                f'sys.path.insert(0, {str(ROOT / "tools/frr")!r}); import run_matrix; '
                f'run_matrix.ROOT = Path({str(root)!r}); ')
        if timeout:
            code += ('collect = run_matrix.collect_cell; '
                     'run_matrix.collect_cell = lambda argv, output, **kwargs: '
                     'collect(argv, output, timeout=0.5, cleanup_timeout=5, **kwargs); ')
        code += 'sys.exit(run_matrix.main())'
        parent = subprocess.Popen([sys.executable, '-c', code, '--generate-only', '--out', str(output)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        def wait_for(name):
            deadline = time.monotonic() + 5
            while not (output / 'pair' / name).exists() and parent.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue((output / 'pair' / name).exists(), f'child did not reach {name}')
        try:
            if timeout:
                wait_for('cleanup-started')
            else:
                wait_for('ready')
                if during_cleanup:
                    os.kill(parent.pid, signal.SIGTERM)
                    wait_for('cleanup-started')
            if process_group:
                os.killpg(parent.pid, signum)
            else:
                os.kill(parent.pid, signum)
            stdout, stderr = parent.communicate(timeout=5)
            self.assertEqual(parent.returncode, 3, (stdout, stderr))
            report = json.loads((output / 'matrix-report.json').read_text())
            self.assertEqual(report['status'], 'incomplete')
            self.assertEqual(len(report['cells']), 1)
            self.assertEqual(report['comparison_slots'], 12)
            self.assertEqual(report['cells'][0]['report']['cleanup'], 'complete')
            self.assertEqual(report['cells'][0]['manifest']['lab_name'], 'rp-signal')
            self.assertTrue((output / 'pair/resources-removed').exists())
            self.assertFalse((output / 'later').exists())
        finally:
            if parent.poll() is None:
                parent.terminate()
                try:
                    parent.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    parent.kill()
                    parent.communicate()
            # On a broken parent, its isolated child must not outlive the test.
            pid_file = output / 'pair/pid'
            if parent.returncode != 3 and pid_file.exists():
                try:
                    os.kill(int(pid_file.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass


if __name__ == '__main__':
    unittest.main()
