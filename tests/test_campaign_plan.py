"""Frozen plan -> node spec, and the per-batch wrapper's start-state and stop semantics."""
import collections
import json
from pathlib import Path
import subprocess
import sys

import pytest

from studies.energy_diagnosis.diagnostics import campaign_plan as cp

ROOT = Path(__file__).resolve().parents[1]


def plan(tmp_path, **changes):
    p = dict(
        campaign_id="rehearsal", cutoff_utc="2099-01-01T00:00:00Z",
        node=dict(host="cc@node", remote_repository="/w/repo", remote_python="/w/env/bin/python",
                  remote_directory="/w/a/b/results", node_output="/w/control", lock="/w/gpu.lock",
                  identity_file="/k/id", known_hosts="/k/kh"),
        maintenance=dict(anchor_utc="2026-09-25T00:00:00Z", period_seconds=10800, window_seconds=900),
        host_condition=dict(cpu_affinity="64-71", keep_awake_cpus="199", tool_cpus="16-23", supervisor_cpus="8-15",
                            idle_cpus="64-71,199"),
        warm=["/w/model", "/w/offload"], required_domains=["PACKAGE_SOCKET_0", "GPU_BOARD_0"],
        base_args=["--mode", "native", "--config", "/w/c.json", "--campaign-exit", "--max-runs", "1"],
        families=dict(S=dict(args=["--deadline", "1500"], tasks=[dict(short="etl", task_pack="/w/p.json", task="etl-x")]),
                      L=dict(args=["--deadline", "1800"], tasks=[dict(short="bfs", task_pack="/w/q.json", task="repo-x"),
                                                                    dict(short="deg", task_pack="/w/r.json", task="repo-y")])),
        arms=dict(A=["--policies", "demand"], B=["--policies", "fixed", "--byte-budget", "1"],
                  C=["--policies", "fixed", "--byte-budget", "1", "--preparation-timing", "after"]),
        repetitions=2, seed=7, batch_seconds=2000, estimated_batch_seconds=420,
        expected=dict(repository_revision="0" * 40, build_manifest="/w/b.json", build_manifest_sha256="1" * 64,
                      backend_python="/w/be/bin/python", weights_manifest="/w/model/alems-weights.json",
                      weights_manifest_sha256="2" * 64, tool_python="/w/tool/bin/python", tool_python_freeze_sha256="3" * 64,
                      networkx_source="/w/nx", networkx_commit="4" * 40, cpu_power=[], min_free_gib=50,
                      lease_end_utc="2099-01-01T00:00:00Z"))
    p.update(changes)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(p))
    return path


def test_spec_is_deterministic_balanced_and_valid(tmp_path):
    spec = cp.node_spec(cp.load(plan(tmp_path)))
    again = cp.node_spec(cp.load(plan(tmp_path)))
    assert spec == again
    ids = [b["id"] for b in spec["batches"]]
    assert len(ids) == len(set(ids)) == 2 * 3 * 3
    per = collections.Counter((s["block"], s["task"]) for s in spec["schedule"])
    assert set(per.values()) == {3}
    for s in spec["schedule"]:
        argv = next(b["argv"] for b in spec["batches"] if b["id"] == s["id"])
        run = argv[argv.index("--") + 1:]
        assert "--campaign-exit" in run and run[run.index("--cpu-affinity") + 1] == "64-71"
        assert run[run.index("--task") + 1] == s["task"]
    from studies.energy_diagnosis.diagnostics.batch_coordinator import validate
    validate(spec)
    orders = {tuple(s["arm"] for s in spec["schedule"] if s["block"] == b and s["task"] == "etl-x") for b in (0, 1)}
    assert all(sorted(o) == ["A", "B", "C"] for o in orders)


def test_plan_schema_and_campaign_flags_are_enforced(tmp_path):
    for changes in (dict(base_args=["--mode", "native"]), dict(base_args=["--campaign-exit", "--output", "x"]),
                    dict(repetitions=0)):
        with pytest.raises(ValueError):
            cp.load(plan(tmp_path, **changes))
    bad = json.loads(plan(tmp_path).read_text()); bad["extra"] = 1
    (tmp_path / "bad.json").write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        cp.load(tmp_path / "bad.json")


def test_windows_listing(tmp_path, capsys):
    assert cp.main(["--plan", str(plan(tmp_path)), "--windows", "2"]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 2


def test_campaign_batch_runs_guarded_goal_and_stops_on_protocol_invalid(tmp_path):
    import datetime as dt
    import os
    if sys.platform != "linux":
        pytest.skip("Linux supervisor placement and guard")
    cpu = min(os.sched_getaffinity(0))
    argv = [sys.executable, "-m", "studies.energy_diagnosis.diagnostics.campaign_batch", "--root", str(tmp_path / "results"),
            "--id", "b0", "--seconds", "120", "--cutoff-utc", (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat(),
            "--lock", str(tmp_path / "lock"), "--supervisor-cpus", str(cpu), "--idle-cpus", str(cpu), "--warm", str(tmp_path / "results"),
            "--", sys.executable, "-m", "studies.energy_diagnosis.moe.run", "--mode", "fixture", "--task", "joined-orders-v1",
            "--policies", "demand", "--max-runs", "1", "--campaign-exit"]
    first = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=300)
    batch = tmp_path / "results/b0"
    status = json.loads((batch / "job/status.json").read_text())
    assert status["status"] == "completed" and status["supervisor_cpus"] == [cpu]
    assert (batch / "job/process-baseline.json").exists() and (batch / "idle-before.json").exists() and (batch / "idle-after.json").exists()
    acceptance = json.loads((batch / "acceptance.json").read_text())
    assert acceptance["protocol_valid"] is False  # simulated fixture goals are never campaign evidence
    assert first.returncode == 6
    again = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert again.returncode != 0 and "FileExistsError" in again.stderr  # no silent rerun


def test_preflight_reports_missing_checkout_instead_of_crashing(tmp_path):
    from studies.energy_diagnosis.diagnostics.campaign_check import preflight
    p = cp.load(plan(tmp_path))
    p["node"]["remote_repository"] = str(tmp_path / "missing-checkout")
    result = preflight(p)
    assert result["passed"] is False and result["checks"] == {"repository_present": False}


def _interrupted_batch(tmp_path, p, status="running", pid=None):
    batch = Path(p["node"]["remote_directory"]) / "r00-S-etl-A"
    (batch / "job").mkdir(parents=True)
    (batch / "job/status.json").write_text(json.dumps(dict(status=status, supervisor_pid=pid, child_pid=None)))
    (batch / "batch.json").write_text("{}")
    (batch / "campaign").mkdir()
    (batch / "campaign/partial.json").write_text('{"partial": true}')
    return batch


def test_recover_refuses_while_running_and_records_partial_artifacts(tmp_path):
    import subprocess as sp
    from studies.energy_diagnosis.diagnostics.campaign_check import recover
    if sys.platform != "linux":
        pytest.skip("reads /proc")
    p = cp.load(plan(tmp_path))
    p["node"]["remote_directory"] = str(tmp_path / "results")
    p["node"]["lock"] = str(tmp_path / "gpu.lock")
    batch = _interrupted_batch(tmp_path, p)
    child = sp.Popen([sys.executable, "-c", "import time; time.sleep(60)", str(batch)])
    try:
        ok, reasons = recover(p, "r00-S-etl-A", gpu_apps=[])
        assert not ok and any("references the batch" in r for r in reasons)
    finally:
        child.kill(); child.wait()
    ok, reasons = recover(p, "r00-S-etl-A", gpu_apps=["123"])
    assert not ok and "GPU compute" in reasons[0]
    ok, record = recover(p, "r00-S-etl-A", gpu_apps=[])
    assert ok and record["status"] == "interrupted"
    assert {f["path"] for f in record["partial_artifacts"]} >= {"campaign/partial.json", "job/status.json"}
    assert json.loads((batch / "job/status.json").read_text())["status"] == "running"  # untouched
    ok, reasons = recover(p, "r00-S-etl-A", gpu_apps=[])
    assert not ok and "never overwritten" in reasons[0]


def test_recover_refuses_terminal_batch(tmp_path):
    from studies.energy_diagnosis.diagnostics.campaign_check import recover
    p = cp.load(plan(tmp_path))
    p["node"]["remote_directory"] = str(tmp_path / "results")
    p["node"]["lock"] = str(tmp_path / "gpu.lock")
    _interrupted_batch(tmp_path, p, status="completed")
    ok, reasons = recover(p, "r00-S-etl-A", gpu_apps=[])
    assert not ok and "terminal" in reasons[0]
