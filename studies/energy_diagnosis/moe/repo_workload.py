"""Bounded repository repair on a pinned real library with its real test suite.

A known, deterministic defect is injected into networkx 3.4.2 library code. The model
reads, searches and edits library source and runs pytest targets it chooses; running
broader suites is ordinary development work that takes seconds to about a minute.
Verification overlays only the model's source edits onto a pristine tree and runs the
case's original test module (including tests withheld from the workspace) plus
independently written checks that compare against brute-force references.

Isolation is best effort, not a security boundary: fresh workspace per attempt, edits
restricted to non-test library files, no shell, sockets disabled in test processes,
resource limits, and a declared CPU set for test runs (ALEMS_TOOL_CPUS).
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from studies.energy_diagnosis.workloads.pilot_tasks import PilotTask, _hash

VERSION = "repo-repair-networkx-v3"  # v3: regex search, explicit submit_answer wording; v2 added four cases
SOURCE_COMMIT = "2acf1590f82757c01a57b81b8c5dfb79e60aa416"  # networkx-3.4.2
PACKAGE = "networkx"
READ_LINES = 150
SEARCH_MATCHES = 40
TEST_SECONDS = 240
OUTPUT_BYTES = 6000
ACTIONS = {
    "list": ("path",),
    "read": ("path", "start"),
    "search": ("pattern",),
    "replace": ("path", "old", "new"),
    "test": ("target",),
}

# Each case: one injected defect (exact unique text), the test module that exposes it,
# original tests withheld from the workspace, and independent held-out checks.
CASES = {
    "degree-centrality-normalization": dict(
        file="networkx/algorithms/centrality/degree_alg.py",
        old="    s = 1.0 / (len(G) - 1.0)\n    centrality = {n: d * s for n, d in G.degree()}",
        new="    s = 1.0 / len(G)\n    centrality = {n: d * s for n, d in G.degree()}",
        module="networkx/algorithms/centrality/tests/test_degree_centrality.py",
        withheld=("TestDegreeCentrality::test_degree_centrality_3", "TestDegreeCentrality::test_degree_centrality_4"),
        symptom="degree_centrality returns wrong values",
    ),
    "core-number-comparison": dict(
        file="networkx/algorithms/core.py",
        old="            if core[u] > core[v]:",
        new="            if core[u] >= core[v]:",
        module="networkx/algorithms/tests/test_core.py",
        withheld=("TestCore::test_k_crust", "TestCore::test_k_corona", "TestCore::test_main_shell"),
        symptom="core_number and the k-core family return wrong results",
    ),
    "bfs-layers-visited": dict(
        file="networkx/algorithms/traversal/breadth_first_search.py",
        old="                if child not in visited:\n                    visited.add(child)\n                    next_layer.append(child)\n        current_layer = next_layer",
        new="                if child not in visited:\n                    next_layer.append(child)\n        visited.update(next_layer)\n        current_layer = next_layer",
        module="networkx/algorithms/traversal/tests/test_bfs.py",
        withheld=(),
        symptom="bfs_layers returns wrong layers for some graphs",
    ),
    "dag-longest-path-multigraph": dict(
        file="networkx/algorithms/dag.py",
        old="                    max(data.values(), key=lambda x: x.get(weight, default_weight))\n                    if G.is_multigraph()",
        new="                    min(data.values(), key=lambda x: x.get(weight, default_weight))\n                    if G.is_multigraph()",
        module="networkx/algorithms/tests/test_dag.py",
        withheld=("TestDagLongestPathLength::test_multigraph_weighted",),
        symptom="dag_longest_path gives wrong results on weighted multigraphs",
    ),
    "connected-components-bfs": dict(
        file="networkx/algorithms/components/connected.py",
        old="            if len(seen) == n:\n                return seen\n    return seen",
        new="            if len(seen) >= n - 1:\n                return seen\n    return seen",
        module="networkx/algorithms/components/tests/test_connected.py",
        withheld=("TestConnected::test_node_connected_components", "TestConnected::test_connected_mutability"),
        symptom="connected component functions return incomplete components",
    ),
    "dijkstra-tentative-distance": dict(
        file="networkx/algorithms/shortest_paths/weighted.py",
        old="            elif u not in seen or vu_dist < seen[u]:\n                seen[u] = vu_dist",
        new="            elif u not in seen:\n                seen[u] = vu_dist",
        module="networkx/algorithms/shortest_paths/tests/test_weighted.py",
        withheld=("TestWeightedPath::test_all_pairs_dijkstra", "TestJohnsonAlgorithm::test_graphs",
                  "TestWeightedPath::test_weight_function"),
        symptom="Dijkstra shortest-path lengths are sometimes too long",
    ),
    "topological-generations-multiedge": dict(
        file="networkx/algorithms/dag.py",
        old="                    indegree_map[child] -= len(G[node][child]) if multigraph else 1",
        new="                    indegree_map[child] -= 1",
        module="networkx/algorithms/tests/test_dag.py",
        withheld=("TestDagLongestPathLength::test_multigraph_unweighted",
                  "TestDagLongestPath::test_multigraph_weighted_default_weight"),
        symptom="topological_generations and DAG longest-path functions fail on multigraphs with parallel edges",
    ),
    "edge-boundary-symmetric": dict(
        file="networkx/algorithms/boundary.py",
        old="        return (e for e in edges if (e[0] in nset1) ^ (e[1] in nset1))",
        new="        return (e for e in edges if (e[0] in nset1) or (e[1] in nset1))",
        module="networkx/algorithms/tests/test_boundary.py",
        withheld=("TestEdgeBoundary::test_multigraph", "TestEdgeBoundary::test_multidigraph"),
        symptom="edge_boundary returns edges that lie entirely inside the node set",
    ),
    "overall-reciprocity-overlap": dict(
        file="networkx/algorithms/reciprocity.py",
        old="    n_overlap_edge = (n_all_edge - G.to_undirected().number_of_edges()) * 2",
        new="    n_overlap_edge = n_all_edge - G.to_undirected().number_of_edges()",
        module="networkx/algorithms/tests/test_reciprocity.py",
        withheld=(),
        symptom="overall reciprocity of a directed graph is too small",
    ),
}

HELD_OUT = {
    "degree-centrality-normalization": '''
import random
import networkx as nx

def test_matches_degree_over_n_minus_one():
    rng = random.Random(11)
    for n in (2, 3, 7, 20):
        G = nx.gnp_random_graph(n, 0.4, seed=rng.randrange(10**6))
        got = nx.degree_centrality(G)
        for v in G:
            assert abs(got[v] - len(list(G.neighbors(v))) / (n - 1)) < 1e-12
''',
    "core-number-comparison": '''
import random
import networkx as nx

def peel(G):
    adj = {v: set(G[v]) - {v} for v in G}
    core, k, alive = {}, 0, set(adj)
    while alive:
        k = max(k, min(len(adj[v] & alive) for v in alive))
        while True:
            low = [v for v in alive if len(adj[v] & alive) <= k]
            if not low:
                break
            for v in low:
                core[v] = k
                alive.discard(v)
    return core

def test_matches_bruteforce_peeling():
    rng = random.Random(5)
    for _ in range(25):
        G = nx.gnp_random_graph(rng.randrange(2, 25), rng.random() * 0.5, seed=rng.randrange(10**6))
        assert nx.core_number(G) == peel(G)
''',
    "bfs-layers-visited": '''
import random
import networkx as nx

def layers(G, sources):
    dist = {s: 0 for s in sources}
    frontier = list(sources)
    while frontier:
        nxt = []
        for u in frontier:
            for w in G[u]:
                if w not in dist:
                    dist[w] = dist[u] + 1
                    nxt.append(w)
        frontier = nxt
    out = {}
    for v, d in dist.items():
        out.setdefault(d, set()).add(v)
    return out

def test_layers_partition_nodes_by_distance():
    rng = random.Random(3)
    for _ in range(30):
        G = nx.gnp_random_graph(rng.randrange(1, 30), rng.random() * 0.4, seed=rng.randrange(10**6))
        sources = rng.sample(list(G), rng.randrange(1, min(3, len(G)) + 1))
        got = list(nx.bfs_layers(G, sources))
        assert sum(len(layer) for layer in got) == len({v for layer in got for v in layer})
        assert {i: set(layer) for i, layer in enumerate(got)} == layers(G, sources)
''',
    "dag-longest-path-multigraph": '''
import itertools
import random
import networkx as nx

def best(G):
    top = 0
    nodes = list(G)
    def walk(v, total):
        nonlocal top
        top = max(top, total)
        for w in G.successors(v):
            walk(w, total + max(d.get("weight", 1) for d in G.get_edge_data(v, w).values()))
    for v in nodes:
        walk(v, 0)
    return top

def test_multigraph_length_matches_exhaustive_search():
    rng = random.Random(9)
    for _ in range(25):
        n = rng.randrange(2, 8)
        G = nx.MultiDiGraph()
        G.add_nodes_from(range(n))
        for u, v in itertools.combinations(range(n), 2):
            for _ in range(rng.randrange(0, 3)):
                G.add_edge(u, v, weight=rng.randrange(1, 10))
        assert nx.dag_longest_path_length(G) == best(G)
''',
    "connected-components-bfs": '''
import random
import networkx as nx

def components(G):
    parent = {v: v for v in G}
    def find(v):
        while parent[v] != v:
            parent[v] = parent[parent[v]]
            v = parent[v]
        return v
    for u, v in G.edges():
        parent[find(u)] = find(v)
    groups = {}
    for v in G:
        groups.setdefault(find(v), set()).add(v)
    return sorted(map(sorted, groups.values()))

def test_components_match_union_find():
    rng = random.Random(7)
    for _ in range(30):
        G = nx.gnp_random_graph(rng.randrange(1, 40), rng.random() * 0.15, seed=rng.randrange(10**6))
        assert sorted(map(sorted, nx.connected_components(G))) == components(G)
        assert nx.number_connected_components(G) == len(components(G))
''',
}

HELD_OUT["dijkstra-tentative-distance"] = '''
import random
import networkx as nx

def bellman_ford(G, source):
    dist = {source: 0}
    for _ in range(len(G)):
        changed = False
        for u, v, d in G.edges(data=True):
            w = d.get("weight", 1)
            pairs = ((u, v),) if G.is_directed() else ((u, v), (v, u))
            for a, b in pairs:
                if a in dist and dist[a] + w < dist.get(b, float("inf")):
                    dist[b] = dist[a] + w
                    changed = True
        if not changed:
            break
    return dist

def test_dijkstra_matches_bellman_ford():
    rng = random.Random(13)
    for _ in range(30):
        G = nx.gnp_random_graph(rng.randrange(2, 25), 0.3, seed=rng.randrange(10**6), directed=rng.random() < 0.5)
        for u, v in G.edges():
            G[u][v]["weight"] = rng.randrange(1, 20)
        source = rng.choice(list(G))
        assert nx.single_source_dijkstra_path_length(G, source) == bellman_ford(G, source)
'''

HELD_OUT["topological-generations-multiedge"] = '''
import random
import networkx as nx

def test_generations_match_longest_predecessor_depth():
    rng = random.Random(17)
    for _ in range(30):
        n = rng.randrange(1, 15)
        G = nx.MultiDiGraph()
        G.add_nodes_from(range(n))
        for u in range(n):
            for v in range(u + 1, n):
                for _ in range(rng.choice([0, 0, 1, 2, 3])):
                    G.add_edge(u, v)
        depth = {}
        for v in range(n):
            preds = list(G.predecessors(v))
            depth[v] = 1 + max(depth[p] for p in preds) if preds else 0
        expected = {}
        for v, d in depth.items():
            expected.setdefault(d, set()).add(v)
        assert {i: set(g) for i, g in enumerate(nx.topological_generations(G))} == expected
'''

HELD_OUT["edge-boundary-symmetric"] = '''
import random
import networkx as nx

def test_boundary_matches_bruteforce():
    rng = random.Random(19)
    for _ in range(30):
        directed = rng.random() < 0.5
        G = nx.gnp_random_graph(rng.randrange(2, 20), 0.3, seed=rng.randrange(10**6), directed=directed)
        S = set(rng.sample(list(G), rng.randrange(1, len(G) + 1)))
        expected = {(u, v) for u in S for v in (G.successors(u) if directed else G[u]) if v not in S}
        got = set(nx.edge_boundary(G, S))
        assert got == expected
'''

HELD_OUT["overall-reciprocity-overlap"] = '''
import random
import networkx as nx

def test_overall_reciprocity_matches_counting():
    rng = random.Random(23)
    for _ in range(30):
        G = nx.gnp_random_graph(rng.randrange(2, 25), rng.uniform(0.1, 0.6), seed=rng.randrange(10**6), directed=True)
        if G.number_of_edges() == 0:
            continue
        reciprocated = sum(1 for u, v in G.edges() if G.has_edge(v, u))
        assert abs(nx.overall_reciprocity(G) - reciprocated / G.number_of_edges()) < 1e-12
'''

SANDBOX = '''import socket

def _blocked(*args, **kwargs):
    raise OSError("network access is disabled in repository tests")

socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked
'''


def _tree_sha(root, suffixes=None):
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and (suffixes is None or path.suffix in suffixes):
            digest.update(str(path.relative_to(root)).encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _withhold(source, names):
    """Remove named test functions/methods (Class::name or name) from a module's source."""
    tree = ast.parse(source)
    spans = []
    for name in names:
        cls, _, fn = name.rpartition("::")
        scope = tree.body
        if cls:
            scope = next(n.body for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
        node = next(n for n in scope if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn)
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        spans.append((start, node.end_lineno))
    lines = source.splitlines(keepends=True)
    for start, end in sorted(spans, reverse=True):
        del lines[start - 1:end]
    return "".join(lines)


def _python_identity(python):
    freeze = subprocess.run([python, "-m", "pip", "freeze"], capture_output=True, text=True, check=True).stdout
    version = subprocess.run([python, "-c", "import sys;print(sys.version)"], capture_output=True, text=True, check=True).stdout
    return dict(python=python, version=version.strip(), freeze_sha256=hashlib.sha256(freeze.encode()).hexdigest())


def create_task(root, *, case, source, python):
    """Materialize pristine/visible/held-out assets for one case from a pinned source checkout."""
    if case not in CASES:
        raise ValueError("unknown repository repair case")
    spec, root, source = CASES[case], Path(root), Path(source)
    if not source.is_absolute() or not Path(python).is_absolute():
        raise ValueError("source and python must be absolute paths")
    if not (source / PACKAGE).is_dir():
        raise ValueError("source checkout does not contain the package")
    if not root.exists():
        with tempfile.TemporaryDirectory(dir=root.parent) as staging:
            stage = Path(staging) / "task"
            shutil.copytree(source / PACKAGE, stage / "pristine" / PACKAGE,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            visible = stage / "visible"
            shutil.copytree(stage / "pristine", visible)
            target = visible / spec["file"]
            text = target.read_text()
            if text.count(spec["old"]) != 1:
                raise ValueError("defect injection site is not unique")
            target.write_text(text.replace(spec["old"], spec["new"]))
            module = visible / spec["module"]
            module.write_text(_withhold(module.read_text(), spec["withheld"]))
            (stage / "heldout").mkdir()
            (stage / "heldout" / f"test_heldout_{case.replace('-', '_')}.py").write_text(HELD_OUT[case].lstrip())
            (stage / "sandbox").mkdir()
            (stage / "sandbox" / "sitecustomize.py").write_text(SANDBOX)
            (stage / "task.json").write_text(json.dumps(dict(
                version=VERSION, case=case, source_commit=SOURCE_COMMIT,
                source_sha256=_tree_sha(source / PACKAGE, {".py"}), tool_python=_python_identity(python)), indent=2) + "\n")
            stage.rename(root)
    meta = json.loads((root / "task.json").read_text())
    if meta["case"] != case or meta["version"] != VERSION or meta["tool_python"]["python"] != python:
        raise ValueError("existing repository task differs from the requested case")
    return PilotTask(
        f"repo-{case}-v3", "repository-repair", f"networkx-{SOURCE_COMMIT[:12]}", root, {}, _hash(root), (),
        f"A user reports: {spec['symptom']}. The repository is networkx 3.4.2 with its test suite. "
        "Find and fix the defect in the library source (do not edit tests), using the repo tool to list, read, "
        "search, replace and run pytest targets. Before finishing, run the complete networkx/algorithms test suite "
        "to check for regressions. Finish by calling submit_answer with answer {done:true}.",
    )


def _inside(workspace, relative, *, must_exist=True):
    if not isinstance(relative, str) or not relative or relative.startswith("/") or "\\" in relative:
        raise ValueError("paths are relative to the repository root, e.g. networkx/algorithms/dag.py")
    path = (workspace / relative).resolve()
    if path != workspace.resolve() and workspace.resolve() not in path.parents:
        raise ValueError("path is outside the repository")
    if not (path == workspace / PACKAGE or (workspace / PACKAGE).resolve() in path.parents or path == (workspace / PACKAGE).resolve()):
        raise ValueError(f"only paths under {PACKAGE}/ are available")
    if must_exist and not path.exists():
        raise ValueError(f"no such path: {relative}")
    return path


def _is_test_file(path):
    return "tests" in path.parts or path.name.startswith("test_") or path.name == "conftest.py"


def _limits():
    import resource
    # macOS does not support this Linux address-space bound reliably.
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (8 * 2**30, 8 * 2**30))
    resource.setrlimit(resource.RLIMIT_CPU, (TEST_SECONDS + 30, TEST_SECONDS + 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 2**20, 256 * 2**20))
    cpus = os.environ.get("ALEMS_TOOL_CPUS")
    if cpus:
        if not hasattr(os, "sched_setaffinity"):
            raise RuntimeError("ALEMS_TOOL_CPUS requires a platform with CPU affinity support")
        os.sched_setaffinity(0, _cpu_list(cpus))


def _cpu_list(text):
    cpus = set()
    for part in text.split(","):
        lo, _, hi = part.partition("-")
        cpus.update(range(int(lo), int(hi or lo) + 1))
    return cpus


def run_pytest(python, root, targets, sandbox, timeout=TEST_SECONDS):
    env = dict(PATH="/usr/bin:/bin", PYTHONPATH=f"{sandbox}{os.pathsep}{root}", PYTHONDONTWRITEBYTECODE="1",
               HOME=str(root), LANG="C.UTF-8", PYTHONHASHSEED="0")
    for key in ("SystemRoot", "SYSTEMROOT", "WINDIR"):
        if key in os.environ:env[key]=os.environ[key]
    return subprocess.run([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", "-rf",
                           "--color=no", *targets], cwd=root, env=env, capture_output=True, text=True,
                          timeout=timeout, preexec_fn=_limits if os.name == "posix" else None, start_new_session=False)


_DURATION = re.compile(r" in \d+(?:\.\d+)?s(?: \(\d+:\d\d:\d\d\))?")


def _normalize(text, root):
    """Model-visible tool output must be identical across paired arms: strip wall-clock
    durations and the per-attempt workspace path."""
    text = text.replace(str(Path(root).resolve()), ".").replace(str(root), ".")
    return _DURATION.sub("", text)


def _summarize(result, root):
    result = subprocess.CompletedProcess(result.args, result.returncode,
                                         _normalize(result.stdout, root), _normalize(result.stderr, root))
    lines = result.stdout.splitlines()
    summary = next((l for l in reversed(lines) if l.strip()), result.stderr.strip()[-300:])
    failed = [l.split()[1] for l in lines if l.startswith("FAILED ")][:20]
    head = result.stdout if len(result.stdout.encode()) <= OUTPUT_BYTES else result.stdout.encode()[:OUTPUT_BYTES].decode(errors="ignore") + "\n[truncated]"
    return dict(exit_code=result.returncode, summary=summary, failed=failed, output=head)


class RepoTool:
    def __init__(self, workspace, python, sandbox):
        self.workspace, self.python, self.sandbox = Path(workspace), python, sandbox

    def execute(self, action, workers=1, **args):
        ws = self.workspace
        if action == "list":
            path = _inside(ws, args["path"])
            if not path.is_dir():
                raise ValueError("list takes a directory")
            entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir() if p.name != "__pycache__")
            return dict(path=args["path"], entries=entries[:400], truncated=len(entries) > 400)
        if action == "read":
            path = _inside(ws, args["path"])
            start = args["start"]
            if not path.is_file() or type(start) is not int or start < 1:
                raise ValueError("read takes a file path and a 1-based start line")
            lines = path.read_text().splitlines()
            chunk = lines[start - 1:start - 1 + READ_LINES]
            return dict(path=args["path"], start=start, end=start - 1 + len(chunk), total_lines=len(lines),
                        text="\n".join(f"{start + i}: {line}" for i, line in enumerate(chunk)))
        if action == "search":
            pattern = args["pattern"]
            if not isinstance(pattern, str) or not pattern or len(pattern) > 200:
                raise ValueError("search takes a nonempty regular expression up to 200 characters")
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid regular expression: {exc}")
            matches, total = [], 0
            for path in sorted((ws / PACKAGE).rglob("*.py")):
                for number, line in enumerate(path.read_text().splitlines(), 1):
                    if compiled.search(line[:1000]):
                        total += 1
                        if len(matches) < SEARCH_MATCHES:
                            matches.append(f"{path.relative_to(ws)}:{number}: {line.strip()[:160]}")
            return dict(pattern=pattern, matches=matches, total=total)
        if action == "replace":
            path = _inside(ws, args["path"])
            old, new = args["old"], args["new"]
            if path.suffix != ".py" or _is_test_file(path.relative_to(ws)):
                raise ValueError("only non-test library .py files can be edited")
            if not isinstance(old, str) or not old or not isinstance(new, str) or len(new.encode()) > 32768:
                raise ValueError("replace takes nonempty old text and new text up to 32768 bytes")
            text = path.read_text()
            count = text.count(old)
            if count != 1:
                raise ValueError(f"old text must occur exactly once in the file (found {count})")
            path.write_text(text.replace(old, new))
            return dict(replaced=args["path"])
        if action == "test":
            target = args["target"]
            file_part = target.split("::", 1)[0] if isinstance(target, str) else None
            _inside(ws, file_part)
            try:
                result = run_pytest(self.python, ws, [target], self.sandbox)
            except subprocess.TimeoutExpired:
                return dict(exit_code=None, summary=f"test run exceeded {TEST_SECONDS} seconds", failed=[], output="")
            return _summarize(result, ws)
        raise ValueError("declared actions are list, read, search, replace, test")


def contract():
    variants = []
    for action, fields in ACTIONS.items():
        props = {"action": {"const": action}}
        for f in fields:
            props[f] = {"type": "integer", "minimum": 1} if f == "start" else {"type": "string", "minLength": 1}
        if action == "replace":
            props["new"] = {"type": "string"}
        variants.append(dict(type="object", properties=props, required=["action", *fields], additionalProperties=False))
    return {"oneOf": variants}


def validate(args):
    if not isinstance(args, dict) or args.get("action") not in ACTIONS:
        raise ValueError("a declared action is required")
    if set(args) != {"action", *ACTIONS[args["action"]]}:
        raise ValueError("arguments do not match the selected action")
    for field in ACTIONS[args["action"]]:
        value = args[field]
        if field == "start":
            if type(value) is not int or value < 1:
                raise ValueError("start must be a positive integer")
        elif not isinstance(value, str) or (field != "new" and not value.strip()) or len(value.encode()) > 32768:
            raise ValueError(f"{field} must be text up to 32768 bytes")


class RepoRuntime:
    def __init__(self, root):
        self.root = Path(root)

    def begin(self, task, lease):
        if _hash(task.asset_path) != task.asset_sha256:
            raise ValueError("repository task assets changed")
        meta = json.loads((task.asset_path / "task.json").read_text())
        if _python_identity(meta["tool_python"]["python"]) != meta["tool_python"]:
            raise ValueError("tool Python environment changed since task preparation")
        self.meta = meta
        self.workspace = self.root / "workspaces" / lease.execution_id
        shutil.copytree(task.asset_path / "visible", self.workspace)

    def context(self, task):
        return dict(family=task.family, tools={"repo": {
            "description": "Repository tool for networkx 3.4.2. The action argument is mandatory. "
            'action="list" {path}: directory entries. action="read" {path,start}: up to 150 numbered lines from start. '
            'action="search" {pattern}: Python regular-expression search, line by line, over networkx/*.py (40 matches shown). '
            'action="replace" {path,old,new}: replace text that occurs exactly once in a non-test library file. '
            'action="test" {target}: run pytest on a file, directory or node id, e.g. networkx/algorithms/tests/test_dag.py '
            "or networkx/algorithms (the complete algorithms suite takes about a minute). Paths are relative to the repository root.",
            "args": {"action": "list, read, search, replace or test", "path": "list/read/replace",
                     "start": "read: first line number", "pattern": "search", "old": "replace", "new": "replace", "target": "test"},
            "parameters": contract(),
            "example_call": {"id": "test_1", "tool": "repo", "args": {"action": "test", "target": "networkx/algorithms/tests/test_dag.py"}}}},
            instruction="Reproduce the failure with a focused test, read the relevant source, make a minimal fix with replace, "
            "rerun the focused test, then run the complete networkx/algorithms suite. When it passes, call the submit_answer "
            "tool with answer {\"done\": true}; do not write the answer as text.")

    def tool(self, task, call):
        if call.get("tool") != "repo":
            raise ValueError("invalid repository tool")
        validate(call.get("args"))
        return RepoTool(self.workspace, self.meta["tool_python"]["python"], str(task.asset_path / "sandbox"))

    def verify(self, task, answer):
        if not isinstance(answer, dict) or set(answer) != {"done"} or answer["done"] is not True:
            return dict(passed=False, reason="invalid completion answer")
        if _hash(task.asset_path) != task.asset_sha256:
            raise ValueError("repository task assets changed")
        return verify_workspace(task.asset_path, self.workspace, self.meta["tool_python"]["python"])


def verify_workspace(assets, workspace, python):
    meta = json.loads((Path(assets) / "task.json").read_text())
    spec = CASES[meta["case"]]
    visible, pristine = Path(assets) / "visible", Path(assets) / "pristine"
    changed = []
    for path in sorted((Path(workspace) / PACKAGE).rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(workspace)
        original = visible / relative
        if not original.exists() or original.read_bytes() != path.read_bytes():
            if _is_test_file(relative) or path.suffix != ".py":
                return dict(passed=False, reason=f"non-library file changed: {relative}")
            changed.append(relative)
    for path in sorted((visible / PACKAGE).rglob("*.py")):
        if not (Path(workspace) / path.relative_to(visible)).exists():
            return dict(passed=False, reason=f"library file removed: {path.relative_to(visible)}")
    with tempfile.TemporaryDirectory() as directory:
        # Library code comes entirely from the workspace (the injected defect stays unless
        # repaired); every test file comes from the pristine tree (withheld tests restored).
        tree = Path(directory) / "tree"
        shutil.copytree(pristine, tree)
        for path in sorted((Path(workspace) / PACKAGE).rglob("*.py")):
            relative = path.relative_to(workspace)
            if "__pycache__" not in relative.parts and not _is_test_file(relative):
                shutil.copyfile(path, tree / relative)
        heldout = next((Path(assets) / "heldout").glob("test_*.py"))
        shutil.copyfile(heldout, tree / heldout.name)
        try:
            result = run_pytest(python, tree, [spec["module"], heldout.name], str(Path(assets) / "sandbox"))
        except subprocess.TimeoutExpired:
            return dict(passed=False, reason="verification tests exceeded their time limit", changed_files=[str(c) for c in changed])
        summary = _summarize(result, tree)
    return dict(passed=result.returncode == 0,
                reason="original module (incl. withheld tests) and independent held-out checks passed" if result.returncode == 0
                else "verification tests failed", changed_files=[str(c) for c in changed],
                verification_summary=summary["summary"], verification_failed=summary["failed"])
