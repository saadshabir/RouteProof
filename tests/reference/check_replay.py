#!/usr/bin/env python3
"""Independent state replay, Floyd-Warshall routing, and witness validation.

No third-party Python dependencies. Includes generated scenarios, declaration
permutations, and byte comparisons across any binaries passed on the command line.
"""
import copy
import hashlib
import ipaddress
import json
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path
from check_routing import LCG, cases as routing_cases, oracle, permuted

ROOT = Path(__file__).resolve().parents[2]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def component(case, start):
    up = {r['id'] for r in case['routers'] if r.get('initial_state', 'up') == 'up'}
    adjacent = {r: [] for r in up}
    for link in case['links']:
        if link.get('initial_state', 'up') == 'up' and link['a'] in up and link['b'] in up:
            adjacent[link['a']].append(link['b'])
            adjacent[link['b']].append(link['a'])
    seen = {start} if start in up else set()
    queue = deque(seen)
    while queue:
        for neighbor in adjacent[queue.popleft()]:
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    frontier, down = [], set()
    for link in sorted(case['links'], key=lambda l: l['id']):
        if (link['a'] in seen) == (link['b'] in seen):
            continue
        state = 'administratively_down' if link.get('initial_state', 'up') == 'down' else 'endpoint_unavailable'
        frontier.append({'kind': 'link', 'link': link['id'], 'state': state})
        outside = link['b'] if link['a'] in seen else link['a']
        if outside not in up:
            down.add(outside)
    frontier += [{'kind': 'router', 'router': r, 'state': 'unavailable'} for r in sorted(down)]
    return sorted(seen), frontier


def validate_finding(finding, assertion, state, snapshot, rows, result):
    prefixes = [p for p in state['prefixes'] if ipaddress.ip_address(assertion['destination']) in ipaddress.ip_network(p['prefix'])]
    prefix = prefixes[0]
    assert finding['assertion_id'] == assertion['id']
    assert finding['source'] == assertion['source'] and finding['destination'] == assertion['destination']
    assert finding['destination_prefix'] == prefix['prefix'] and finding['destination_origin'] == prefix['origin']
    assert finding['ecmp_quantifier'] == 'all'
    assert finding['event_id'] == snapshot['event_id'] and finding['sequence'] == snapshot['sequence']
    assert finding['snapshot_sha256'] == snapshot['sha256']
    assert finding['scenario_sha256'] == result['scenario_sha256'] and finding['result_sha256'] == result['canonical_sha256']
    assert finding['reproduction_argv'] == ['routeproof', 'simulate', '<scenario>', '--out', '<output>']
    current = assertion['source']
    up = set(snapshot['available_routers'])
    links = {l['id']: l for l in state['links']}
    path = finding['path']
    assert path and path[0]['router'] == current
    for index, step in enumerate(path):
        assert step['router'] == current
        route = rows.get((current, prefix['prefix']))
        assert step['route_decision'] == ({'kind': route['kind'], 'metric': route['metric']} if route else {'kind': 'absent'})
        hop = step['next_hop']
        if 'action' in hop:
            assert index == len(path)-1 and hop['action'] == finding['kind']
            continue
        assert route and hop in route['next_hops'] and current in up
        link = links[hop['link']]
        assert {current, hop['neighbor']} == {link['a'], link['b']}
        assert hop['interface'] == f"{link['id']}@{current}"
        assert link.get('initial_state', 'up') == 'up' and hop['neighbor'] in up
        current = hop['neighbor']
    reason = finding['kind']
    if reason == 'source_down':
        assert assertion['source'] not in up and len(path) == 1
    elif reason == 'destination_down':
        assert prefix['origin'] not in up and assertion['source'] in up and len(path) == 1
    elif reason == 'no_route':
        assert (current, prefix['prefix']) not in rows
        expected_component, frontier = component(state, current)
        assert finding['reachable_component'] == expected_component and finding['frontier'] == frontier
        assert prefix['origin'] not in expected_component
        assert finding['unreachable_origin'] == prefix['origin']
    else:
        raise AssertionError(f'unexpected converged finding {reason}')


def verify(result, normalized):
    assert result['schema_version'] == 1 and result['model'] == 'ospf_spf_v1'
    assert result['scenario_name'] == normalized['name']
    assert result['scenario_sha256'] == digest(normalized)
    assert result['events_sha256'] == digest(normalized['events'])
    assert result['assertions_sha256'] == digest(normalized['assertions'])
    projection = copy.deepcopy(result)
    projection.pop('canonical_sha256')
    for record in projection['assertions']:
        for finding in record['findings']:
            finding.pop('result_sha256')
    assert result['canonical_sha256'] == digest(projection)
    state = copy.deepcopy(normalized)
    events = sorted(normalized['events'], key=lambda e: e['seq'])
    assert len(result['snapshots']) == len(events)+1 and len(result['events']) == len(events)
    assert len(result['assertions']) == len(normalized['assertions']) * (len(events)+1)
    failures = 0
    for index, snapshot in enumerate(result['snapshots']):
        if index == 0:
            assert snapshot['id'] == 'baseline' and snapshot['event_id'] is None and snapshot['sequence'] is None
        else:
            event = events[index-1]
            collection, field = ('routers', 'router') if event['type'].startswith('router_') else ('links', 'link')
            target = next(item for item in state[collection] if item['id'] == event[field])
            value = 'up' if event['type'].endswith('_up') else 'down'
            noop = target.get('initial_state', 'up') == value
            target['initial_state'] = value
            outcome = result['events'][index-1]
            assert outcome['id'] == event['id'] and outcome['sequence'] == event['seq'] and outcome['at_ns'] == event['at_ns']
            assert outcome['type'] == event['type'] and outcome['disposition'] == ('noop' if noop else 'applied')
            assert outcome['snapshot_sha256'] == snapshot['sha256']
            assert snapshot['id'] == f"event-{event['seq']}" and snapshot['event_id'] == event['id'] and snapshot['sequence'] == event['seq']
        physical = {k: snapshot[k] for k in ('available_routers', 'administratively_up_links', 'routes')}
        assert snapshot['sha256'] == digest(physical)
        assert snapshot['available_routers'] == sorted(r['id'] for r in state['routers'] if r.get('initial_state', 'up') == 'up')
        assert snapshot['administratively_up_links'] == sorted(l['id'] for l in state['links'] if l.get('initial_state', 'up') == 'up')
        expected = oracle(state)
        assert snapshot['routes'] == expected, (normalized['name'], index, snapshot['routes'], expected)
        if index:
            assert outcome['route_entries'] == len(expected)
            assert outcome['next_hop_references'] == sum(len(r['next_hops']) for r in expected)
        rows = {(r['router'], r['prefix']): r for r in expected}
        records = result['assertions'][index*len(normalized['assertions']):(index+1)*len(normalized['assertions'])]
        for record, assertion in zip(records, normalized['assertions']):
            assert record['snapshot_id'] == snapshot['id'] and record['snapshot_sha256'] == snapshot['sha256']
            assert record['assertion_id'] == assertion['id']
            prefix = next(p for p in state['prefixes'] if ipaddress.ip_address(assertion['destination']) in ipaddress.ip_network(p['prefix']))
            reachable, _ = component(state, assertion['source'])
            passing = assertion['source'] in snapshot['available_routers'] and prefix['origin'] in reachable
            assert record['status'] == ('pass' if passing else 'fail')
            if passing:
                assert not record['findings']
            else:
                failures += 1
                assert len(record['findings']) == 1
                validate_finding(record['findings'][0], assertion, state, snapshot, rows, result)
    assert result['status'] == ('fail' if failures else 'pass')
    return len(result['snapshots']), failures


def trace_cases(binary):
    process = subprocess.run([binary, 'validate', str(ROOT/'examples/diamond-failures.yaml'), '--normalized'],
                             capture_output=True, text=True, timeout=10, check=True)
    yield json.loads(process.stdout)
    for file in sorted((ROOT/'examples/replay').glob('*.json')):
        yield json.loads(file.read_text())
    generator = LCG(0x52504633)
    for index, case in enumerate(routing_cases()):
        if index >= 39:
            break
        case = copy.deepcopy(case)
        case['events'] = []
        for seq in range(1, 9):
            is_link = bool(case['links']) and generator.take(2) == 0
            collection = case['links'] if is_link else case['routers']
            target = collection[generator.take(len(collection))]['id']
            kind = 'link' if is_link else 'router'
            case['events'].append({'id': f'event-{seq}', 'seq': seq*2, 'at_ns': seq//3,
                                   'type': kind + ('_up' if generator.take(2) else '_down'), kind: target})
        case['assertions'] = [{'id': f"check-{i}-{j}", 'type': 'must_reach', 'source': router['id'],
                               'destination': str(ipaddress.ip_network(prefix['prefix']).network_address),
                               'quantifier': 'all', 'scope': 'every_snapshot'}
                              for i, router in enumerate(case['routers']) for j, prefix in enumerate(case['prefixes'])]
        yield case


def check_explain_regressions(binary, original, directory):
    """Valid digests must not hide contradictory outcomes or missing coverage."""
    def explain(value):
        result = copy.deepcopy(value)
        result.pop('canonical_sha256')
        for record in result['assertions']:
            for finding in record['findings']:
                finding.pop('result_sha256')
        result['canonical_sha256'] = digest(result)
        for record in result['assertions']:
            for finding in record['findings']:
                finding['result_sha256'] = result['canonical_sha256']
        path = directory/'rehash-result.json'
        path.write_bytes(canonical(result))
        return subprocess.run([binary, 'explain', str(path), '--assertion', 'a-to-d'],
                              capture_output=True, text=True, timeout=10)

    broken = []
    result = copy.deepcopy(original)
    result['status'] = 'pass'
    broken.append(result)
    result = copy.deepcopy(original)
    for record in result['assertions']:
        record['status'], record['findings'] = 'pass', []
    broken.append(result)  # top-level fail contradicts uniformly passing records
    for status, findings in (('pass', original['assertions'][2]['findings']), ('fail', []),
                             ('incomplete', original['assertions'][2]['findings'])):
        result = copy.deepcopy(original)
        result['assertions'][2]['status'] = status
        result['assertions'][2]['findings'] = copy.deepcopy(findings)
        broken.append(result)
    result = copy.deepcopy(original)
    finding = result['assertions'][2]['findings'][0]
    finding['kind'] = finding['terminal_reason'] = 'incomplete'
    broken.append(result)  # failed record must not conceal an incomplete finding
    for key, value in (('assertion_id', 'wrong-assertion'), ('event_id', 'wrong-event'),
                       ('sequence', 999), ('snapshot_sha256', '0'*64),
                       ('scenario_sha256', '0'*64), ('terminal_reason', 'loop'),
                       ('kind', 'unsupported')):
        result = copy.deepcopy(original)
        result['assertions'][2]['findings'][0][key] = value
        broken.append(result)
    result = copy.deepcopy(original)
    result['assertions'][2]['assertion_id'] = 'unselected-assertion'
    broken.append(result)  # validate finding references even outside the selected ID
    result = copy.deepcopy(original)
    result['status'] = 'pass'
    result['snapshots'], result['events'], result['assertions'] = [], [], []
    broken.append(result)

    incomplete = copy.deepcopy(original)
    incomplete['status'] = 'incomplete'
    incomplete['incomplete_reason'] = 'test resource budget exceeded'
    incomplete['requested_snapshots'] = len(original['snapshots'])
    for completed in (0, 3):
        incomplete['snapshots'] = original['snapshots'][:completed]
        incomplete['events'] = original['events'][:max(0, completed-1)]
        incomplete['assertions'] = original['assertions'][:completed]
        incomplete['completed_snapshots'] = completed
        process = explain(incomplete)
        assert process.returncode == 3 and 'test resource budget exceeded' in process.stdout, process.stderr
    for key in ('incomplete_reason', 'completed_snapshots', 'requested_snapshots'):
        result = copy.deepcopy(incomplete)
        del result[key]
        broken.append(result)
    for key, value in (('incomplete_reason', ''), ('incomplete_reason', 0),
                       ('completed_snapshots', -1), ('completed_snapshots', 0.5),
                       ('completed_snapshots', '3'), ('completed_snapshots', 2),
                       ('completed_snapshots', 2**64), ('requested_snapshots', 0),
                       ('requested_snapshots', 2)):
        result = copy.deepcopy(incomplete)
        result[key] = value
        broken.append(result)
    for result in broken:
        process = explain(result)
        assert process.returncode == 2 and not process.stdout, (process.returncode, process.stdout, process.stderr)


def run(binaries):
    corpus = hashlib.sha256()
    snapshots = failures = count = 0
    with tempfile.TemporaryDirectory(prefix='routeproof-replay-') as temporary:
        directory = Path(temporary)
        source = directory/'scenario.json'
        for case in trace_cases(binaries[0]):
            outputs = []
            for binary in binaries:
                for variant_index, variant in enumerate((case, permuted(case), copy.deepcopy(case))):
                    if variant_index == 1:
                        variant['events'].reverse()
                        variant['assertions'].reverse()
                    source.write_text(json.dumps(variant))
                    out = directory/f'run-{len(outputs)}-{count}'
                    process = subprocess.run([binary, 'simulate', str(source), '--out', str(out)],
                                             capture_output=True, text=True, timeout=10)
                    assert process.returncode in (0, 1), (case['name'], process.stderr)
                    raw = (out/'result.json').read_bytes()
                    result = json.loads(raw)
                    normalized = subprocess.run([binary, 'validate', str(source), '--normalized'],
                                                capture_output=True, text=True, timeout=10, check=True)
                    checked = verify(result, json.loads(normalized.stdout))
                    assert process.returncode == (1 if result['status'] == 'fail' else 0)
                    run = json.loads((out/'run.json').read_text())
                    assert run['schema_version'] == 1 and run['simulation_ns'] >= 0
                    outputs.append(raw)
            assert all(raw == outputs[0] for raw in outputs), f"canonical replay changed: {case['name']}"
            corpus.update(outputs[0])
            snapshots += checked[0]
            failures += checked[1]
            count += 1
            if count == 1:
                result = json.loads(outputs[0])
                a_hops = [[h['link'] for r in s['routes'] if r['router'] == 'a' for h in r['next_hops']] for s in result['snapshots']]
                assert a_hops == [['ab','ac'],['ac'],[],['ab'],[],['ab']]
                target = directory/'run-0-0/result.json'
                explanation = subprocess.run([binaries[0], 'explain', str(target), '--assertion', 'a-to-d'],
                                             capture_output=True, text=True, timeout=10)
                assert explanation.returncode == 1 and 'frontier:' in explanation.stdout and 'destination_down' in explanation.stdout
                unknown = subprocess.run([binaries[0], 'explain', str(target), '--assertion', 'unknown'],capture_output=True, text=True, timeout=10)
                assert unknown.returncode == 2
                check_explain_regressions(binaries[0], result, directory)
                # Corrupted results, duplicate keys, and unsupported schema fail explicitly.
                for broken in (outputs[0].decode().replace('"status":"fail"', '"status":"pass"', 1),
                               '{"schema_version":1,"schema_version":1}', '{"schema_version":2,"model":"ospf_spf_v1"}', '['*130 + '0' + ']'*130):
                    bad = directory/'bad.json'; bad.write_text(broken)
                    process = subprocess.run([binaries[0], 'explain', str(bad), '--assertion', 'a-to-d'], capture_output=True,text=True,timeout=10)
                    assert process.returncode == 2, process.stderr
                # Existing artifacts are preserved and invalid input creates no result.
                process = subprocess.run([binaries[0], 'simulate', str(source), '--out', str(target.parent)],capture_output=True,text=True,timeout=10)
                assert process.returncode == 3 and target.read_bytes() == outputs[0]
                bad = directory/'invalid.json'; bad.write_text('{}')
                process = subprocess.run([binaries[0], 'simulate', str(bad), '--out', str(directory/'invalid-out')],capture_output=True,text=True,timeout=10)
                assert process.returncode == 2 and not (directory/'invalid-out').exists()
    print(f'PASS independent replay: {count} traces, {snapshots} snapshots, {failures} validated failures; full Floyd-Warshall route domain, physical components/frontiers')
    print(f'PASS repeat/order/endpoint/compiler invariance ({len(binaries)} toolchains), CLI explain/errors; corpus sha256={corpus.hexdigest()}')


if __name__ == '__main__':
    run([str(Path(binary).resolve()) for binary in sys.argv[1:]])
