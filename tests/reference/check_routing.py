#!/usr/bin/env python3
"""Independent Floyd-Warshall oracle, using only the Python standard library.

First hops are derived by testing each physical outgoing interface against a
neighbor-to-origin distance, never by propagating the C++ shortest-path DAG.
Generated cases use a specified 32-bit LCG rather than library PRNG behavior.
"""
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def scenario(name, count, edges, down_routers=(), down_links=()):
    ids = [f'r{i}' for i in range(count)]
    return {
        'schema_version': 1, 'model': 'ospf_spf_v1', 'name': name,
        'routers': [{'id': r, 'router_id': f'0.0.0.{i+1}',
                     'initial_state': 'down' if i in down_routers else 'up'}
                    for i, r in enumerate(ids)],
        'links': [{'id': f'l{i}', 'a': ids[a], 'b': ids[b],
                   'cost_ab': ab, 'cost_ba': ba,
                   'initial_state': 'down' if i in down_links else 'up'}
                  for i, (a, b, ab, ba) in enumerate(edges)],
        'prefixes': [{'prefix': f'10.0.{i}.0/24', 'origin': r, 'stub_cost': i+1}
                     for i, r in enumerate(ids)],
        'events': [], 'assertions': []}


def oracle(case):
    ids = sorted(r['id'] for r in case['routers'])
    up = {r['id'] for r in case['routers'] if r.get('initial_state', 'up') == 'up'}
    infinity = 10**30
    distance = {(a, b): 0 if a == b and a in up else infinity for a in ids for b in ids}
    arcs = {r: [] for r in ids}
    for link in case['links']:
        a, b = link['a'], link['b']
        if link.get('initial_state', 'up') == 'down' or a not in up or b not in up:
            continue
        for source, target, cost in ((a, b, link['cost_ab']), (b, a, link['cost_ba'])):
            distance[source, target] = min(distance[source, target], cost)
            arcs[source].append((target, cost, link['id'], f"{link['id']}@{source}"))
    for middle in ids:
        for a in ids:
            for b in ids:
                distance[a, b] = min(distance[a, b], distance[a, middle] + distance[middle, b])
    rows = []
    for source in ids:
        for prefix in sorted(case['prefixes'], key=lambda p: p['prefix']):
            origin = prefix['origin']
            d = distance[source, origin]
            if d == infinity:
                continue
            hops = []
            if source != origin:
                for neighbor, cost, link, interface in sorted(arcs[source]):
                    if cost + distance[neighbor, origin] == d:
                        hops.append({'neighbor': neighbor, 'link': link, 'interface': interface})
                hops.sort(key=lambda h: (h['neighbor'], h['link'], h['interface']))
            rows.append({'router': source, 'prefix': prefix['prefix'], 'origin': origin,
                         'kind': 'connected' if source == origin else 'ospf',
                         'distance_to_origin': d,
                         'metric': 0 if source == origin else d + prefix['stub_cost'],
                         'protocol_cost': d + prefix['stub_cost'], 'next_hops': hops})
    return rows


def permuted(case):
    result = copy.deepcopy(case)
    for field in ('routers', 'links', 'prefixes'):
        result[field].reverse()
    for link in result['links']:
        link['a'], link['b'] = link['b'], link['a']
        link['cost_ab'], link['cost_ba'] = link['cost_ba'], link['cost_ab']
    return result


class LCG:
    def __init__(self, seed):
        self.state = seed

    def take(self, bound):
        self.state = (1664525 * self.state + 1013904223) & 0xffffffff
        return (self.state >> 8) % bound


def cases():
    for path in sorted((ROOT / 'examples/routing').glob('*.json')):
        yield json.loads(path.read_text())
    generator = LCG(0x52504632)
    for i in range(80):
        count = 1 + generator.take(8)
        edges = []
        for a in range(count):
            for b in range(a+1, count):
                if generator.take(4) != 0:
                    continue
                for _ in range(1 + generator.take(2)):
                    edges.append((a, b, 1 + generator.take(7), 1 + generator.take(7)))
        down_routers = [r for r in range(count) if generator.take(9) == 0]
        down_links = [e for e in range(len(edges)) if generator.take(7) == 0]
        yield scenario(f'generated-{i:02}', count, edges, down_routers, down_links)


def run(binary):
    digest = hashlib.sha256()
    row_count = hop_count = case_count = 0
    with tempfile.TemporaryDirectory(prefix='routeproof-oracle-') as directory:
        path = Path(directory) / 'scenario.json'
        for case in cases():
            expected = oracle(case)
            outputs = []
            for variant in (case, permuted(case)):
                path.write_text(json.dumps(variant))
                process = subprocess.run([binary, 'routes', str(path)], capture_output=True, text=True, timeout=10)
                assert process.returncode == 0, (case['name'], process.stderr)
                assert process.stderr == '', process.stderr
                actual = json.loads(process.stdout)
                assert actual['routes'] == expected, (case['name'], actual['routes'], expected)
                assert actual['kind'] == 'baseline_routes'
                assert actual['schema_version'] == 1 and actual['model'] == 'ospf_spf_v1'
                assert actual['route_entries'] == len(expected)
                assert actual['next_hop_references'] == sum(len(r['next_hops']) for r in expected)
                assert actual['available_routers'] == sorted(r['id'] for r in case['routers']
                    if r.get('initial_state', 'up') == 'up')
                assert actual['administratively_up_links'] == sorted(l['id'] for l in case['links']
                    if l.get('initial_state', 'up') == 'up')
                outputs.append(process.stdout)
            assert outputs[0] == outputs[1], f"input order changed baseline: {case['name']}"
            path.write_text(json.dumps(case))
            timed = subprocess.run([binary, 'routes', str(path), '--timing'], capture_output=True,
                                   text=True, timeout=10)
            assert timed.returncode == 0 and timed.stdout == outputs[0]
            timing = json.loads(timed.stderr)
            assert set(timing) == {'baseline_compute_ns'} and timing['baseline_compute_ns'] >= 0
            digest.update(outputs[0].encode())
            row_count += len(expected)
            hop_count += sum(len(r['next_hops']) for r in expected)
            case_count += 1
    print(f'PASS Floyd-Warshall oracle: {case_count} cases, {row_count} route rows, {hop_count} next-hop references')
    print('PASS declaration/endpoint reversal, repeat/timing invariance; corpus sha256=' + digest.hexdigest())


if __name__ == '__main__':
    run(str(Path(sys.argv[1]).resolve()))
