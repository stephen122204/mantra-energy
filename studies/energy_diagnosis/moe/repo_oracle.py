"""Parent-owned graph oracles: candidate code never receives references or tests.

Only graph inputs enter a read-only, no-network/no-process Landlock child. Its
reported status and stdout are untrusted; the parent compares every returned
value with independently computed results. A zero process exit is not success.
These checks supplement regression tests, not a certification of arbitrary code.
"""
import math
import random
import secrets
from pathlib import Path

from . import sandbox

VERSION = 'repo-external-oracle-v1'

# No expected values, assertions, grader source or seed are sent to this code.
CANDIDATE = '''
import sys
sys.path.insert(0, ROOT)
import networkx as nx

def evaluate(case, d):
    cls = nx.MultiDiGraph if d['multi'] else (nx.DiGraph if d['directed'] else nx.Graph)
    g = cls()
    g.add_nodes_from(range(d['n']))
    for u, v, w in d['edges']:
        g.add_edge(u, v, weight=w)
    if case == 'degree-centrality-normalization':
        value = nx.degree_centrality(g)
        return [value[v] for v in range(d['n'])]
    if case == 'core-number-comparison':
        value = nx.core_number(g)
        return [value[v] for v in range(d['n'])]
    if case == 'bfs-layers-visited':
        return [sorted(layer) for layer in nx.bfs_layers(g, d['sources'])]
    if case == 'dag-longest-path-multigraph':
        return nx.dag_longest_path_length(g)
    if case == 'connected-components-bfs':
        return [sorted(sorted(c) for c in nx.connected_components(g)), nx.number_connected_components(g)]
    if case == 'dijkstra-tentative-distance':
        return sorted([v, w] for v, w in nx.single_source_dijkstra_path_length(g, d['sources'][0]).items())
    if case == 'topological-generations-multiedge':
        return [sorted(layer) for layer in nx.topological_generations(g)]
    if case == 'edge-boundary-symmetric':
        return sorted([u, v] for u, v in nx.edge_boundary(g, d['sources']))
    if case == 'overall-reciprocity-overlap':
        return nx.overall_reciprocity(g)
    raise ValueError('unknown case')
'''

CASES = (
    'degree-centrality-normalization', 'core-number-comparison', 'bfs-layers-visited',
    'dag-longest-path-multigraph', 'connected-components-bfs', 'dijkstra-tentative-distance',
    'topological-generations-multiedge', 'edge-boundary-symmetric', 'overall-reciprocity-overlap',
)


def inputs(case, seed, count=32):
    if case not in CASES:
        raise ValueError('unknown repository case')
    rng = random.Random(seed)
    values = []
    for i in range(count):
        n = rng.randint(3, 18)
        multi = case in ('dag-longest-path-multigraph', 'topological-generations-multiedge')
        directed = multi or case == 'overall-reciprocity-overlap' or (
            case in ('dijkstra-tentative-distance', 'edge-boundary-symmetric') and i % 2 == 1)
        edges = []
        probability = rng.uniform(.15, .65)
        for u in range(n):
            for v in range(n):
                if u == v or ((multi or not directed) and u > v):
                    continue
                if rng.random() < probability:
                    for _ in range(rng.randint(1, 3) if multi else 1):
                        edges.append([u, v, rng.randint(1, 15)])
        if not edges:
            edges = [[0, 1, 1]]
        sources = rng.sample(range(n), rng.randint(1, min(3, n)))
        values.append(dict(n=n, directed=directed, multi=multi, edges=edges, sources=sources))
    # Deterministic witnesses supplement—not replace—fresh generated cases.
    if case == 'connected-components-bfs':
        values.append(dict(n=4, directed=False, multi=False,
                           edges=[[0, 1, 1], [1, 2, 1], [2, 3, 1]], sources=[0]))
    return values


def reference(case, d):
    n, edges = d['n'], d['edges']
    adj = [set() for _ in range(n)]
    for u, v, _ in edges:
        adj[u].add(v)
        if not d['directed']:
            adj[v].add(u)
    if case == 'degree-centrality-normalization':
        return [len(a)/(n-1) for a in adj]
    if case == 'core-number-comparison':
        alive, out, level = set(range(n)), [0]*n, 0
        while alive:
            level = max(level, min(len(adj[v] & alive) for v in alive))
            while True:
                removed = {v for v in alive if len(adj[v] & alive) <= level}
                if not removed:
                    break
                for v in removed:
                    out[v] = level
                alive -= removed
        return out
    if case in ('bfs-layers-visited', 'connected-components-bfs'):
        def distances(starts):
            dist = {v: 0 for v in starts}
            for level in range(n):
                new = {w for v in list(dist) if dist[v] == level for w in adj[v] if w not in dist}
                if not new:
                    break
                dist.update({w: level+1 for w in new})
            return dist
        if case == 'bfs-layers-visited':
            ds = distances(d['sources'])
            return [sorted(v for v in ds if ds[v] == k) for k in range(max(ds.values())+1)]
        remaining, components = set(range(n)), []
        while remaining:
            comp = set(distances([min(remaining)]))
            components.append(sorted(comp)); remaining -= comp
        return [sorted(components), len(components)]
    if case in ('dag-longest-path-multigraph', 'topological-generations-multiedge'):
        # Generated DAG vertices are already in topological order.
        longest, depth = [0]*n, [0]*n
        for v in range(n):
            incoming = [(u, w) for u, t, w in edges if t == v]
            if incoming:
                longest[v] = max(longest[u]+w for u, w in incoming)
                depth[v] = max(depth[u]+1 for u, _ in incoming)
        if case == 'dag-longest-path-multigraph':
            return max(longest)
        return [[v for v in range(n) if depth[v] == k] for k in range(max(depth)+1)]
    if case == 'dijkstra-tentative-distance':
        dist = {d['sources'][0]: 0}
        arcs = list(edges) + ([] if d['directed'] else [[v, u, w] for u, v, w in edges])
        for _ in range(n-1):
            for u, v, w in arcs:
                if u in dist and dist[u]+w < dist.get(v, math.inf):
                    dist[v] = dist[u]+w
        return sorted([v, w] for v, w in dist.items())
    if case == 'edge-boundary-symmetric':
        selected = set(d['sources'])
        return sorted([u, v] for u in selected for v in adj[u] if v not in selected)
    if case == 'overall-reciprocity-overlap':
        arcs = {(u, v) for u, v, _ in edges}
        return sum((v, u) in arcs for u, v in arcs)/len(arcs)
    raise ValueError('unknown repository case')


def same(actual, expected):
    if isinstance(expected, list):
        return type(actual) is list and len(actual) == len(expected) and all(same(a, b) for a, b in zip(actual, expected))
    if type(expected) is float:
        return type(actual) in (int, float) and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12)
    return type(actual) is type(expected) and actual == expected


def verify(workspace, case, *, seed=None, require_landlock=True, seconds=30):
    """Return evidence; production requires Landlock, false is only for portable tests."""
    root = Path(workspace).resolve()
    if any(p.is_symlink() for p in (root/'networkx').rglob('*')):
        return dict(passed=False, failure='mismatch', reason='candidate contains symlinks')
    seed = secrets.randbits(128) if seed is None else seed
    cases = inputs(case, seed)
    expected = [reference(case, d) for d in cases]
    source = 'ROOT = ' + repr(str(root)) + '\n' + CANDIDATE
    status, payload = sandbox.run(source, 'evaluate', [[case, d] for d in cases], seconds,
                                  require_landlock=require_landlock, read_paths=[root])
    evidence = dict(oracle_version=VERSION, challenge_seed=str(seed), checks=len(cases), sandbox_status=status)
    if status == 'refused':
        raise RuntimeError('repository oracle sandbox unavailable')
    if status != 'ok':
        return dict(evidence, passed=False, failure='budget' if status == 'timeout' else 'runtime_error',
                    reason='candidate did not return complete graph results')
    got = payload.get('outputs')
    passed = same(got, expected)
    return dict(evidence, passed=passed, failure=None if passed else 'mismatch',
                reason='parent-owned graph checks passed' if passed else 'independent graph result mismatch')
