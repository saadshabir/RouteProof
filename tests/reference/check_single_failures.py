#!/usr/bin/env python3
"""Independently check each N-1 snapshot with Floyd-Warshall and physical BFS."""
import copy
import ipaddress
import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from check_replay import canonical, digest, validate_finding
from check_routing import cases, oracle, permuted, scenario

ROOT = Path(__file__).resolve().parents[2]


def verify(result, normalized):
    assert result['analysis_mode'] == 'n-1'
    assert result['scenario_sha256'] == digest(normalized)
    assert result['events_sha256'] == digest(normalized['events'])
    assert result['assertions_sha256'] == digest(normalized['assertions'])
    projection = copy.deepcopy(result)
    projection.pop('canonical_sha256')
    for record in projection['assertions']:
        for finding in record['findings']:
            finding.pop('result_sha256')
    assert result['canonical_sha256'] == digest(projection)
    up = {r['id'] for r in normalized['routers'] if r['initial_state'] == 'up'}
    plan, excluded = [], []
    for link in normalized['links']:
        if link['initial_state'] == 'down' or link['a'] not in up or link['b'] not in up:
            excluded.append({'kind': 'link', 'target': link['id'],
                             'reason': 'already_down' if link['initial_state'] == 'down' else 'endpoint_unavailable'})
        else:
            plan.append(('link', link['id']))
    for router in normalized['routers']:
        if router['id'] in up:
            plan.append(('router', router['id']))
        else:
            excluded.append({'kind': 'router', 'target': router['id'], 'reason': 'already_down'})
    report = result['resilience']
    assert report['requested_cases'] == report['completed_cases'] == len(plan)
    assert report['authored_events_ignored'] == len(normalized['events'])
    assert report['excluded_components'] == excluded
    assert report['redundancy_definition'] == 'ecmp_first_hops'
    assert len(result['snapshots']) == len(plan) + 1
    assert len(result['events']) == len(report['cases']) == len(plan)
    width = len(normalized['assertions'])
    assert len(result['assertions']) == width * (len(plan) + 1)
    baseline_rows = oracle(normalized)
    baseline_failures = set()
    fail = False
    for index, snapshot in enumerate(result['snapshots']):
        # Rebuild from the original input each time, independently of the engine.
        state = copy.deepcopy(normalized)
        if index:
            kind, target = plan[index - 1]
            collection = 'links' if kind == 'link' else 'routers'
            next(item for item in state[collection] if item['id'] == target)['initial_state'] = 'down'
            case = report['cases'][index - 1]
            event = result['events'][index - 1]
            assert case['failure'] == {'kind': kind, 'target': target}
            assert case['snapshot_id'] == snapshot['id'] == f'event-{index}'
            assert event['id'] == snapshot['event_id'] == f'n-1-{index}'
            assert event['type'] == kind + '_down' and event['disposition'] == 'applied'
            assert event['sequence'] == snapshot['sequence'] == index and event['at_ns'] == 0
            assert event['snapshot_sha256'] == snapshot['sha256']
        else:
            assert snapshot['id'] == 'baseline' and snapshot['event_id'] is None and snapshot['sequence'] is None
        expected = oracle(state)
        physical = {key: snapshot[key] for key in ('available_routers', 'administratively_up_links', 'routes')}
        assert snapshot['sha256'] == digest(physical)
        assert snapshot['routes'] == expected, (normalized['name'], index)
        assert snapshot['available_routers'] == sorted(r['id'] for r in state['routers'] if r['initial_state'] == 'up')
        assert snapshot['administratively_up_links'] == sorted(l['id'] for l in state['links'] if l['initial_state'] == 'up')
        rows = {(r['router'], r['prefix']): r for r in expected}
        failed, preexisting, endpoints = [], [], []
        for record, assertion in zip(result['assertions'][index*width:(index+1)*width], normalized['assertions']):
            prefix = next(p for p in state['prefixes'] if ipaddress.ip_address(assertion['destination']) in ipaddress.ip_network(p['prefix']))
            passing = (assertion['source'], prefix['prefix']) in rows
            assert record['assertion_id'] == assertion['id'] and record['snapshot_id'] == snapshot['id']
            assert record['snapshot_sha256'] == snapshot['sha256']
            assert record['status'] == ('pass' if passing else 'fail')
            scope = 'none'
            if not passing:
                if not index:
                    baseline_failures.add(assertion['id'])
                    scope = 'baseline'
                elif kind == 'router' and target == assertion['source']:
                    scope = 'source_outage'
                elif kind == 'router' and target == prefix['origin'] and assertion['source'] in snapshot['available_routers']:
                    scope = 'destination_outage'
                else:
                    scope = 'baseline' if assertion['id'] in baseline_failures else 'network'
                assert len(record['findings']) == 1
                validate_finding(record['findings'][0], assertion, state, snapshot, rows, result, command='n-1')
            else:
                assert not record['findings']
            assert record['failure_scope'] == scope
            if scope in ('network', 'baseline'):
                fail = True
                (failed if scope == 'network' else preexisting).append(assertion['id'])
            elif scope != 'none':
                endpoints.append({'assertion_id': assertion['id'], 'kind': scope})
        if index:
            assert case['failed_requirements'] == failed and case['preexisting_failures'] == preexisting
            assert case['endpoint_outages'] == endpoints
            lost, reductions = [], []
            for route in baseline_rows:
                if route['router'] not in snapshot['available_routers'] or route['origin'] not in snapshot['available_routers']:
                    continue
                remaining = rows.get((route['router'], route['prefix']))
                identity = {'source': route['router'], 'prefix': route['prefix'], 'origin': route['origin']}
                if remaining is None:
                    lost.append(identity)
                before = len(route['next_hops'])
                after = len(remaining['next_hops']) if remaining else 0
                if before > 1 and after < before:
                    reductions.append(dict(identity, baseline_next_hops=before, remaining_next_hops=after,
                                           redundancy_lost=after < 2, reachable=remaining is not None))
            assert sorted(case['unreachable_routes'], key=canonical) == sorted(lost, key=canonical)
            assert sorted(case['redundancy_reductions'], key=canonical) == sorted(reductions, key=canonical)
    assert report['baseline_failed_requirements'] == sorted(baseline_failures)
    assert result['status'] == ('fail' if fail else 'pass')
    return len(plan)


def check_explain_rejections(binary, original, directory):
    def mislabel_endpoint(result, index, scope):
        record = result['assertions'][index]
        record['failure_scope'] = scope
        case = next(c for c in result['resilience']['cases'] if c['snapshot_id'] == record['snapshot_id'])
        case['endpoint_outages'] = [o for o in case['endpoint_outages'] if o['assertion_id'] != record['assertion_id']]
        case['failed_requirements' if scope == 'network' else 'preexisting_failures'].append(record['assertion_id'])
        if scope == 'baseline':
            result['resilience']['baseline_failed_requirements'].append(record['assertion_id'])
        result['status'] = 'fail'

    mutations = [lambda r: r.update(analysis_mode='unknown'),
                 lambda r: r.pop('resilience'),
                 lambda r: r['resilience'].update(completed_cases=0),
                 lambda r: r['resilience']['cases'][0]['failure'].update(kind='router'),
                 lambda r: r['assertions'][0].update(failure_scope='network'),
                 lambda r: r.update(status='fail')]
    endpoint_index = next(i for i, r in enumerate(original['assertions']) if r['failure_scope'] == 'source_outage')
    mutations.append(lambda r: r['assertions'][endpoint_index].update(failure_scope='destination_outage'))
    destination_index = next(i for i, r in enumerate(original['assertions']) if r['failure_scope'] == 'destination_outage')
    mutations.extend([lambda r: mislabel_endpoint(r, endpoint_index, 'network'),
                      lambda r: mislabel_endpoint(r, destination_index, 'network'),
                      lambda r: mislabel_endpoint(r, endpoint_index, 'baseline'),
                      lambda r: r['resilience']['baseline_failed_requirements'].append(original['assertions'][0]['assertion_id'])])
    for mutate in mutations:
        result = copy.deepcopy(original)
        result.pop('canonical_sha256')
        for record in result['assertions']:
            for finding in record['findings']:
                finding.pop('result_sha256')
        mutate(result)
        result['canonical_sha256'] = digest(result)
        for record in result['assertions']:
            for finding in record['findings']:
                finding['result_sha256'] = result['canonical_sha256']
        path = directory / 'bad-result.json'
        path.write_bytes(canonical(result))
        process = subprocess.run([binary, 'explain', str(path), '--assertion', original['assertions'][0]['assertion_id']],
                                 capture_output=True, text=True)
        assert process.returncode == 2 and not process.stdout, (process.returncode, process.stderr)


def run(binary):
    count = total = 0
    with tempfile.TemporaryDirectory(prefix='routeproof-n-1-') as temporary:
        directory = Path(temporary)
        source = directory / 'scenario.json'
        # Include a multi-access parallel-link case and a 3-to-2 ECMP reduction.
        corpus = [scenario('parallel', 2, [(0, 1, 1, 1), (0, 1, 1, 1)]),
                  scenario('three-branches', 5, [(0, i, 1, 1) for i in (1, 2, 3)] +
                           [(i, 4, 1, 1) for i in (1, 2, 3)])]
        corpus += list(itertools.islice(cases(), 35))
        for case in corpus:
            case['assertions'] = [{'id': f'check-{i}-{j}', 'type': 'must_reach', 'source': router['id'],
                                   'destination': str(ipaddress.ip_network(prefix['prefix']).network_address),
                                   'quantifier': 'all', 'scope': 'every_snapshot'}
                                  for i, router in enumerate(case['routers']) for j, prefix in enumerate(case['prefixes'])]
            # This authored failure must never accumulate into the generated sweep.
            case['events'] = [{'id': 'ignored', 'seq': 9, 'at_ns': 100,
                               'type': 'router_down', 'router': case['routers'][0]['id']}]
            outputs = []
            for variant_index, variant in enumerate((case, permuted(case))):
                if variant_index:
                    variant['assertions'].reverse()
                source.write_text(json.dumps(variant))
                out = directory / f'run-{count}-{variant_index}'
                process = subprocess.run([binary, 'n-1', str(source), '--out', str(out)], capture_output=True, text=True, timeout=10)
                assert process.returncode in (0, 1), process.stderr
                raw = (out / 'result.json').read_bytes()
                result = json.loads(raw)
                normalized = subprocess.run([binary, 'validate', str(source), '--normalized'], capture_output=True, text=True, check=True)
                tested = verify(result, json.loads(normalized.stdout))
                assert process.returncode == (1 if result['status'] == 'fail' else 0)
                manifest = json.loads((out / 'run.json').read_text())
                assert manifest['analysis_mode'] == 'n-1' and manifest['result_sha256'] == result['canonical_sha256']
                assert manifest['completed_snapshots'] == tested + 1 and manifest['applied_events'] == tested
                outputs.append(raw)
                if case['assertions']:
                    explanation = subprocess.run([binary, 'explain', str(out / 'result.json'), '--assertion', case['assertions'][0]['id']],
                                                 capture_output=True, text=True, timeout=10)
                    assert explanation.returncode == process.returncode, explanation.stderr
                    assert 'source_outage' in explanation.stdout or report_has_unavailable_source(result, case['assertions'][0]['id'])
            assert outputs[0] == outputs[1], case['name']
            if count == 0:
                check_explain_rejections(binary, json.loads(outputs[0]), directory)
                target = directory / 'run-0-0/result.json'
                before = target.read_bytes()
                process = subprocess.run([binary, 'n-1', str(source), '--out', str(target.parent)], capture_output=True, text=True)
                assert process.returncode == 3 and target.read_bytes() == before
            total += tested
            count += 1
        source.write_text('{}')
        process = subprocess.run([binary, 'n-1', str(source), '--out', str(directory / 'invalid')], capture_output=True, text=True)
        assert process.returncode == 2 and not (directory / 'invalid').exists()
        for args in (['n-1'], ['n-1', str(source)], ['n-1', str(source), '--bad', 'out']):
            assert subprocess.run([binary, *args], capture_output=True).returncode == 2
    print(f'PASS independent N-1: {count} topologies, {total} isolated failures; full route oracle, witnesses, endpoint scopes, ECMP reductions, order invariance, CLI')


def report_has_unavailable_source(result, assertion):
    return any(r['snapshot_id'] == 'baseline' and r['assertion_id'] == assertion and r['status'] == 'fail'
               for r in result['assertions'])


if __name__ == '__main__':
    run(str(Path(sys.argv[1]).resolve()))
