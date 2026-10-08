#!/usr/bin/env python3
"""Frozen v1 workload generator. Only integer arithmetic; no Python PRNG drift."""
import json
from pathlib import Path

VERSION = 'routeproof_workload_v1'
ALGORITHM = 'xorshift32 (13,17,5); nonzero uint32 state; modulo selection'


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    text = Path(path).read_text()
    if len(text.encode()) > 1024 * 1024:
        raise ValueError('profile byte budget exceeded')
    return json.loads(text, object_pairs_hook=unique)


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer in {low}..{high}')
    return value


def validate_cell(cell):
    if not isinstance(cell, dict):
        raise ValueError('cell must be an object')
    required = {'id', 'shape', 'routers', 'prefixes_per_origin', 'prefix_origins',
                'assertions', 'trace_cycles', 'ecmp_width', 'seed', 'extra_edges_per_router'}
    if set(cell) != required:
        raise ValueError('cell fields differ from v1 contract')
    if (not isinstance(cell['id'], str) or not cell['id'] or len(cell['id']) > 64 or
            any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in cell['id'])):
        raise ValueError('cell id must be a safe lowercase name')
    if cell['shape'] not in ('chain', 'ring', 'grid', 'diamond_ladder', 'sparse_random'):
        raise ValueError('unsupported shape')
    if cell['prefix_origins'] not in ('selected', 'all') or cell['assertions'] not in ('selected', 'all'):
        raise ValueError('unsupported prefix/assertion coverage')
    for key, low, high in [('routers', 4, 4096), ('prefixes_per_origin', 1, 4),
                           ('trace_cycles', 1, 32), ('ecmp_width', 2, 8),
                           ('seed', 1, 0xffffffff), ('extra_edges_per_router', 0, 4)]:
        integer(cell[key], low, high, key)
    prefixes = (cell['routers'] if cell['prefix_origins'] == 'all' else 2) * cell['prefixes_per_origin']
    if cell['assertions'] == 'all' and prefixes * cell['routers'] > 100000:
        raise ValueError('generator assertion budget exceeded (100000); narrow destination coverage')
    return cell


class Random:
    def __init__(self, seed):
        self.state = seed

    def next(self):
        x = self.state
        x ^= (x << 13) & 0xffffffff
        x ^= x >> 17
        x ^= (x << 5) & 0xffffffff
        self.state = x & 0xffffffff
        return self.state


def generate(cell):
    validate_cell(cell)
    n = cell['routers']
    edges = {(0, 1)}  # gateway leaf: a single link makes a partition at any size

    def add(a, b):
        if a != b:
            edges.add(tuple(sorted((a, b))))

    if cell['shape'] in ('chain', 'ring', 'sparse_random'):
        for i in range(1, n - 1):
            add(i, i + 1)
        if cell['shape'] == 'ring':
            add(1, n - 1)
        if cell['shape'] == 'sparse_random':
            rng = Random(cell['seed'])
            target = min((n - 1) * (n - 2) // 2 + 1,
                         len(edges) + cell['extra_edges_per_router'] * (n - 1))
            attempts = 0
            while len(edges) < target and attempts < 100 * n:
                add(1 + rng.next() % (n - 1), 1 + rng.next() % (n - 1))
                attempts += 1
            if len(edges) != target:
                raise ValueError('sparse generator edge budget exhausted')
    elif cell['shape'] == 'grid':
        width = 1
        while (width + 1) ** 2 <= n - 1:
            width += 1
        for i in range(1, n):
            if (i - 1) % width and i > 1:
                add(i - 1, i)
            if i - width >= 1:
                add(i - width, i)
    else:
        root, cursor = 1, 2
        while cursor + cell['ecmp_width'] < n:
            join = cursor + cell['ecmp_width']
            for branch in range(cursor, join):
                add(root, branch)
                add(branch, join)
            root, cursor = join, join + 1
        while cursor < n:
            add(root, cursor)
            root, cursor = cursor, cursor + 1
    ids = [f'r{i:04d}' for i in range(n)]
    links = [{'id': f'l{a:04d}-{b:04d}', 'a': ids[a], 'b': ids[b], 'cost_ab': 1, 'cost_ba': 1}
             for a, b in sorted(edges)]
    origins = list(range(n)) if cell['prefix_origins'] == 'all' else [0, n - 1]
    prefixes = []
    for origin in origins:
        for density in range(cell['prefixes_per_origin']):
            index = origin * 4 + density
            prefixes.append({'prefix': f'10.{index // 256}.{index % 256}.0/24',
                             'origin': ids[origin], 'stub_cost': 1})
    internal = next(link['id'] for link in links if link['a'] != ids[0])
    gateway = links[0]['id']
    trace = [('link_down', 'link', internal), ('link_up', 'link', internal),
             ('link_down', 'link', gateway), ('link_up', 'link', gateway),
             ('router_down', 'router', ids[-1]), ('router_up', 'router', ids[-1]),
             ('link_up', 'link', gateway), ('router_up', 'router', ids[-1])]
    events = []
    for _ in range(cell['trace_cycles']):
        for kind, target_type, target in trace:
            seq = len(events) + 1
            events.append({'id': f'e{seq:04d}', 'seq': seq, 'at_ns': seq * 1000000,
                           'type': kind, target_type: target})
    assertions = []
    for prefix in prefixes:
        sources = range(n) if cell['assertions'] == 'all' else ([0] if prefix['origin'] == ids[-1] else [])
        for source in sources:
            assertions.append({'id': f'a{len(assertions):06d}', 'type': 'must_reach',
                               'source': ids[source], 'destination': prefix['prefix'].replace('.0/24', '.1'),
                               'quantifier': 'all', 'scope': 'every_snapshot'})
    return {'schema_version': 1, 'model': 'ospf_spf_v1', 'name': cell['id'],
            'routers': [{'id': ids[i], 'router_id': f'0.0.{(i + 1) // 256}.{(i + 1) % 256}'} for i in range(n)],
            'links': links, 'prefixes': prefixes, 'events': events, 'assertions': assertions}


def estimates(scenario):
    r, p, links, events = (len(scenario[key]) for key in ('routers', 'prefixes', 'links', 'events'))
    a = len(scenario['assertions'])
    degrees = {router['id']: 0 for router in scenario['routers']}
    for link in scenario['links']:
        degrees[link['a']] += 1
        degrees[link['b']] += 1
    rows = (events + 1) * r * p
    hops = rows * max(degrees.values())
    output = rows * 512 + hops * 128 + (events + 1) * a * (1024 + r * 64)
    return {'routers': r, 'physical_links': links, 'directed_arcs': links * 2, 'prefixes': p,
            'events': events, 'assertions': a, 'analyzed_destinations': len({x['destination'] for x in scenario['assertions']}),
            'retained_route_upper_bound': rows, 'next_hop_reference_upper_bound': hops,
            'output_bytes_estimate': output, 'rss_bytes_estimate': output * 4 + r * p * 256 + 32 * 1024**2,
            'spf_work_units': (events + 1) * r * (r + 2 * links)}
