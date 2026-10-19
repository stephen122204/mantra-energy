"""Workspaces copied from a read-only frozen preparation must stay editable by the agent."""
import json
import os
import shutil
import stat
import sys
import time
from types import SimpleNamespace

import pytest

from studies.energy_diagnosis.moe import program_workload as pw
from studies.energy_diagnosis.moe.etl_workload import ETLRuntime, ETLTool, create_task as create_etl
from studies.energy_diagnosis.moe.task_pack_fixture import PROGRAMS
from studies.energy_diagnosis.workloads.pilot_tasks import WorkspaceFault, _hash, copy_workspace, workspace_write

CORRECT_ETL = ("SELECT r.region, COUNT(*) AS event_count, SUM(r.gross_cents-r.tax_cents) AS net_cents FROM raw r "
               "JOIN (SELECT event_id,MAX(seq) AS latest FROM raw GROUP BY event_id) v ON r.event_id=v.event_id "
               "AND r.seq=v.latest WHERE r.status='paid' GROUP BY r.region ORDER BY r.region")


def freeze(root):
    """Same effect as chmod -R a-w on a frozen preparation."""
    for item in sorted(root.rglob("*"), reverse=True) + [root]:
        item.chmod(item.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def thaw(root):
    for item in [root, *root.rglob("*")]:
        item.chmod(item.stat().st_mode | stat.S_IWUSR)


@pytest.fixture
def frozen(tmp_path):
    made = []
    yield made
    for root in made:
        thaw(root)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores write permission")
def test_copy_is_writable_and_source_stays_read_only(tmp_path, frozen):
    source = tmp_path / "frozen"
    (source / "pkg").mkdir(parents=True)
    (source / "pkg" / "mod.py").write_text("x = 1\n")
    (source / "private").mkdir()
    (source / "private" / "answer.json").write_text("{}")
    freeze(source); frozen.append(source)
    before = _hash(source)
    workspace = tmp_path / "ws"
    copy_workspace(source, workspace, ignore=shutil.ignore_patterns("private"))
    (workspace / "pkg" / "mod.py").write_text("x = 2\n")
    (workspace / "pkg" / "new.py").write_text("")
    assert not (workspace / "private").exists()
    assert _hash(source) == before
    assert not os.access(source / "pkg" / "mod.py", os.W_OK)
    assert not os.access(source / "pkg", os.W_OK)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores write permission")
@pytest.mark.parametrize("case", pw.CASES)
def test_program_task_from_frozen_assets_can_be_solved(tmp_path, frozen, case):
    task = pw.create_task(tmp_path / "assets", case=case, rows=32, seed=7)
    freeze(task.asset_path); frozen.append(task.asset_path)
    runtime = pw.ProgramRuntime(tmp_path / "run")
    runtime.begin(task, SimpleNamespace(execution_id="one"))
    tool = pw.ProgramTool(runtime.workspace)
    assert tool.execute("write", content=PROGRAMS[case]) == {"written": True}
    assert tool.execute("test")["passed"]
    assert runtime.verify(task, {"done": True})["passed"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores write permission")
def test_etl_task_from_frozen_assets_can_be_solved(tmp_path, frozen):
    task = create_etl(tmp_path / "assets", rows=128, seed=7)
    freeze(task.asset_path); frozen.append(task.asset_path)
    runtime = ETLRuntime(tmp_path / "runs")
    runtime.begin(task, SimpleNamespace(execution_id="one"))
    ETLTool(runtime.workspace).execute("write", CORRECT_ETL)
    assert runtime.verify(task, {"done": True})["passed"]


# A permitted write that the OS refuses is infrastructure: the attempt ends as infra_failed instead of the model
# retrying into a budget (calibration d921767 burned whole sessions this way).

class ScriptedModel:
    """Always asks to write solution.py through the program tool."""
    model_config = {"max_tokens": 256}

    def __init__(self):
        self.calls = 0

    def chat(self, request, sampling, meta):
        self.calls += 1
        call = dict(name="program", arguments=dict(action="write", content="def solve(data):\n    return []\n"))
        return dict(status="ok", content="<tool_call>" + json.dumps(call) + "</tool_call>", finish_reason="stop",
                    tokens=dict(prompt=100, completion=40), token_provenance="estimated")


def _program_runtime(tmp_path):
    from studies.energy_diagnosis.moe.task_pack import PackRuntime
    task = pw.create_task(tmp_path / "assets", case="conditional-dedup", rows=32, seed=7)
    runtime = PackRuntime({task.task_id: pw}, tmp_path / "runtime")
    lease = SimpleNamespace(execution_id="fault", attempt_id="fault", started_ns=time.monotonic_ns(),
                            clock_domain="host-monotonic")
    runtime.begin(task, lease)
    return task, runtime, lease


def runtime(tmp_path, case):
    task = pw.create_task(tmp_path / "assets", case=case, rows=32, seed=7)
    rt = pw.ProgramRuntime(tmp_path / "run"); rt.begin(task, SimpleNamespace(execution_id="one"))
    return task, rt


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores write permission")
def test_permitted_write_refused_by_the_os_is_a_workspace_fault(tmp_path):
    target = tmp_path / "solution.py"; target.write_text("x\n"); target.chmod(0o444)
    with pytest.raises(WorkspaceFault, match="PermissionError"):
        workspace_write(target, "y\n")
    task, rt = runtime(tmp_path / "p", "conditional-dedup")
    (rt.workspace / "solution.py").chmod(0o444)
    with pytest.raises(WorkspaceFault):
        pw.ProgramTool(rt.workspace).execute("write", content=PROGRAMS["conditional-dedup"])


def test_disallowed_agent_access_stays_an_agent_error(tmp_path):
    from studies.energy_diagnosis.moe import repo_workload as rw
    ws = tmp_path / "ws"; (ws / "networkx" / "tests").mkdir(parents=True)
    (ws / "networkx" / "tests" / "test_a.py").write_text("def test():\n    pass\n")
    tool = rw.RepoTool(ws, sys.executable, str(tmp_path))
    for path in ("../outside.py", "networkx/tests/test_a.py"):
        with pytest.raises(ValueError):
            tool.execute("replace", path=path, old="pass", new="assert 0")


def test_copy_that_cannot_be_made_writable_fails_before_the_agent_starts(tmp_path, monkeypatch):
    source = tmp_path / "src"; source.mkdir(); (source / "a.txt").write_text("a")
    real = os.access
    monkeypatch.setattr(os, "access", lambda p, mode: False if str(p).endswith("a.txt") else real(p, mode))
    with pytest.raises(WorkspaceFault, match="not writable"):
        copy_workspace(source, tmp_path / "ws")


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores write permission")
def test_production_loop_ends_the_attempt_as_infrastructure(tmp_path):
    from studies.energy_diagnosis.local_run import GoalExecutor
    from studies.paper2.cohort.session import OUTCOMES
    task, rt, lease = _program_runtime(tmp_path)
    (rt.active.workspace / "solution.py").chmod(0o444)  # injected after a valid copy
    model = ScriptedModel()
    plan = SimpleNamespace(setting_id="cohort", planned_run_id="fault-cohort", model_sha256="fixture",
                           tool_concurrency=False, tool_workers=1)
    ex = GoalExecutor({task.task_id: task}, model, None, tmp_path, max_steps=3, timeout_seconds=60, simulated=True,
                      workload_runtime=rt, protocol="chat-tools-v2")
    results, trace = [], dict(terminal=None, turns=[])
    status, error, *_ = ex._chat(task, lease, plan, rt.context(task), [], results, [], [], trace, [], None)
    assert (status, OUTCOMES[status], trace["terminal"]) == ("crashed", "infra_failed", "infrastructure_failure")
    assert model.calls == 1, "no further model turns after the fault"
    assert error.startswith("infrastructure_failure: WorkspaceFault:") and results[0]["status"] == "failed"
    assert list((tmp_path / "goals" / "fault" / "turns").glob("000-tools.json")), "the failing turn is kept"


FAKE_SESSION = '''#!{python}
import json, sys, time
from pathlib import Path
spec_path = Path(sys.argv[sys.argv.index("--spec") + 1]); spec = json.loads(spec_path.read_text())
broken = spec["task_id"] == "broken"
if not broken:
    time.sleep(60)
error = "infrastructure_failure: WorkspaceFault: permitted workspace write failed: PermissionError: denied"
(spec_path.parent / "outcome.json").write_text(json.dumps(dict(
    session_id=spec["session_id"], attempt_id=spec["attempt_id"], task_id=spec["task_id"], execution_status="crashed",
    outcome="infra_failed" if broken else "completed", terminal="infrastructure_failure" if broken else None,
    error=error if broken else "", answer=None, turns=1, started_wall=time.time(), ended_wall=time.time())))
'''


class _Idle(__import__("http.server").server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"vllm:num_requests_running 0\nvllm:num_requests_waiting 0\n"
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_cohort_stops_and_is_invalid_after_a_workspace_fault(tmp_path):
    import threading
    from http.server import ThreadingHTTPServer
    from studies.paper2.cohort import records
    from studies.paper2.cohort.cohort import CohortSpec, run_cohort
    fake = tmp_path / "fake-python"; fake.write_text(FAKE_SESSION.format(python=sys.executable)); fake.chmod(0o755)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Idle)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        tasks = [dict(task_id=t, task_pickle="unused", task_kind="program", pair_key=f"{t}-r0")
                 for t in ("slow-a", "broken", "slow-b", "queued-1", "queued-2")]
        spec = CohortSpec(cohort_id="c-fault", config_id="cfg", served_model="m",
                          base_url=f"http://127.0.0.1:{server.server_address[1]}", max_model_len=4096, tekken="unused",
                          tasks=tasks, admission_limit=3, grace_s=5, drain_timeout_s=5)
        started = time.monotonic()
        summary = run_cohort(spec, tmp_path / "out", python=str(fake), poll_s=0.05)
        assert time.monotonic() - started < 40, "running sessions are stopped, not waited out"
    finally:
        server.shutdown()
    by_task = {s["task_id"]: s["outcome"] for s in summary["sessions"]}
    assert by_task == {"broken": "infra_failed", "slow-a": "cancelled", "slow-b": "cancelled",
                       "queued-1": "cancelled", "queued-2": "cancelled"}
    assert summary["infra_invalid"] and summary["reconciliation"]["reconciled"]
    assert summary["infrastructure_fault"]["session_id"].endswith("broken-r0")
    root = tmp_path / "out" / "c-fault"
    events = [json.loads(l) for l in (root / "events.jsonl").read_text().splitlines()]
    assert any(e["kind"] == "infrastructure_stop" for e in events)
    assert {e.get("reason") for e in events if e["kind"] == "terminal" and e.get("task_id", "").startswith("queued")} \
        == {"infrastructure fault in c-fault-broken-r0"}
    assert records.verify_manifest(root) == []


REPO_SOURCE = os.environ.get("ALEMS_NETWORKX_SOURCE")
REPO_PYTHON = os.environ.get("ALEMS_REPO_TOOL_PYTHON")


@pytest.mark.skipif(not (REPO_SOURCE and REPO_PYTHON) or os.geteuid() == 0,
                    reason="needs a networkx 3.4.2 checkout and tool Python (ALEMS_NETWORKX_SOURCE, ALEMS_REPO_TOOL_PYTHON)")
def test_repository_task_from_frozen_assets_repairs_and_grades(tmp_path, frozen):
    """Both copy paths: the agent workspace and the verifier's scratch tree that overlays library files."""
    from studies.energy_diagnosis.moe import repo_workload as rw
    case = "bfs-layers-visited"
    spec = rw.CASES[case]
    task = rw.create_task(tmp_path / "task", case=case, source=REPO_SOURCE, python=REPO_PYTHON)
    freeze(task.asset_path); frozen.append(task.asset_path)
    before = _hash(task.asset_path)
    runs = {}
    for name in ("repaired", "untouched"):
        rt = rw.RepoRuntime(tmp_path / "runs")
        rt.begin(task, SimpleNamespace(execution_id=name))
        runs[name] = rt
    tool = rw.RepoTool(runs["repaired"].workspace, REPO_PYTHON, str(task.asset_path / "sandbox"))
    assert tool.execute("replace", path=spec["file"], old=spec["new"], new=spec["old"]) == {"replaced": spec["file"]}
    repaired = runs["repaired"].verify(task, {"done": True})
    assert repaired["passed"] is True, repaired
    untouched = runs["untouched"].verify(task, {"done": True})
    assert untouched["passed"] is False
    assert _hash(task.asset_path) == before and not os.access(task.asset_path / "visible" / spec["file"], os.W_OK)
