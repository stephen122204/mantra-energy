"""Deadline attribution, inclusive wall-time budgets, and non-measuring preflight."""
import io
import json
import signal

import pytest

from studies.paper2.cohort import budget, cohort, pilot


@pytest.mark.parametrize("failure", ["before_poll", "during_signal", "missing_process"])
def test_real_crash_at_deadline_is_not_scheduler_cancellation(tmp_path, monkeypatch, failure):
    now, processes, signals = [0.0], [], []
    class Proc:
        pid = 999999
        returncode = None
        def poll(self): return self.returncode
        def wait(self, timeout=None): return self.returncode
    def start(s, *args):
        s.proc = Proc(); processes.append(s.proc); s.log = io.StringIO()
    def sleep(_):
        now[0] = 2.0
        if failure == "before_poll":
            processes[0].returncode = 1
    def killpg(pid, sig):
        processes[0].returncode = 1
        if failure == "missing_process":
            raise ProcessLookupError()
        signals.append(sig)
    monkeypatch.setattr(cohort._Session, "start", start)
    monkeypatch.setattr(cohort.time, "sleep", sleep)
    monkeypatch.setattr(cohort.os, "killpg", killpg)
    monkeypatch.setattr("studies.paper2.cohort.guards.wait_drained", lambda *a, **k: {"drained": True})
    spec = cohort.CohortSpec(cohort_id="crash", config_id="fixture", served_model="fixture", base_url="fixture",
                            max_model_len=100, tekken="unused", cohort_deadline_s=1,
                            tasks=[dict(task_id="task", task_pickle="unused", task_kind="fixture", pair_key="task")])
    result = cohort.run_cohort(spec, tmp_path, clock=lambda: now[0])
    assert result["outcomes"] == {"infra_failed": 1} and result["infra_invalid"]
    if failure == "before_poll":
        assert signals == []


def test_budget_counts_grading_once_and_reports_actual_interval(tmp_path):
    events = [dict(kind="server_started", config={"name": "a"}, started={"load_s": 30}),
              dict(kind="step_done", step="a-live", seconds=120)]
    (tmp_path / "driver-events.jsonl").write_text("".join(json.dumps(e)+"\n" for e in events))
    c = tmp_path / "cohorts/a-live/a-live"; (c / "sessions/s").mkdir(parents=True)
    (c / "cohort-summary.json").write_text(json.dumps({"energy": {"interval_s": 90}}))
    (c / "sessions/s/verification.json").write_text(json.dumps({"t_start": 1000, "t_end": 1020}))
    m = budget.measured(tmp_path)
    result = budget.budget(m, dict(cells=[dict(config="a", step="live", repeats=30)],
                                  contingency=0, export_h=0, server_loads_per_config=2))
    assert m["steps"]["a-live"] == 120 and m["interval_s"]["a-live"] == 90
    assert result["step_wall_h"] == 1.0
    assert result["gpu_interval_h"] == 0.75
    assert result["verify_cpu_h"] == round(600/3600, 2)
    assert result["total_reserved_h"] == round((3600+60)/3600, 2)


def test_missing_interval_does_not_turn_wall_time_into_gpu_time():
    result = budget.budget(dict(steps={"a-live": 3600}, verify_s={"a-live": 1200}, loads={}),
                           dict(cells=[dict(config="a", step="live", repeats=1)], contingency=0, export_h=0))
    assert result["total_reserved_h"] == 1.0
    assert result["gpu_interval_h"] is None
    assert result["missing_interval_cells"] == ["a-live"]


def test_explicit_dry_run_never_touches_gpu_even_with_large_budget(tmp_path, monkeypatch):
    from studies.paper2.cohort.make_plan import build_sweep
    plan = build_sweep(tmp_path, "GPU-unused", "fixture", 8103)
    plan["expected_tasks"] = {"task": "hash"}
    monkeypatch.setattr(pilot, "prepare_tasks", lambda *a, **k: [dict(task_id="task", asset_sha256="hash")])
    def forbidden(*a, **k): raise AssertionError("dry run attempted GPU work")
    monkeypatch.setattr(pilot, "gpu_index_for", forbidden)
    monkeypatch.setattr(pilot, "VllmServer", forbidden)
    monkeypatch.setattr(pilot, "make_measurement", forbidden)
    # Isolate revision checks from the worktree in this fixture; the real node dry run checks both.
    monkeypatch.setattr(pilot.subprocess, "check_output", lambda argv, **k: "fixture" if "rev-parse" in argv else "")
    f = tmp_path / "plan.json"; f.write_text(json.dumps(plan))
    pilot.main(["--plan", str(f), "--out", str(tmp_path/"out"), "--budget-s", "999999",
                "--cutoff-utc", "2099-01-01T00:00:00Z", "--dry-run"])
    events = [json.loads(l) for l in (tmp_path/"out/driver-events.jsonl").read_text().splitlines()]
    assert sum(e["kind"] == "pass_skipped" for e in events) == 3
    assert not any(e["kind"] == "server_started" for e in events)
    assert events[-1]["kind"] == "driver_end" and events[-1]["steps"] == 0
