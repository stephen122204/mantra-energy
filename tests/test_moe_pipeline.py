"""Real tool execution and the same owned RPC/lifecycle interface as the GPU path."""
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from studies.energy_diagnosis.moe.backend import ProcessBackend
from studies.energy_diagnosis.moe.control import Expert, Lifecycle, Policy
from studies.energy_diagnosis.moe.summary import paired_interval

ROOT = Path(__file__).resolve().parents[1]


def command(output, *args, expected=0):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "studies.energy_diagnosis.moe.run",
            "--mode",
            "fixture",
            "--output",
            str(output),
            *args,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_complete_tasks_controls_and_durable_resume(tmp_path):
    output = tmp_path / "all"
    first = command(
        output, "--policies", "demand,history,fixed,bounded", "--max-runs", "20"
    )
    assert first["executed"] == 20
    assert first["validation"]["valid"]
    manifest = json.loads((output / "moe-manifest.json").read_text())
    assert manifest["execution_protocol"] == "planned-body-initialized-window-v1"
    assert all(
        x["startup_seconds"] > 0 and x["resume_barrier_seconds"] >= 0
        for x in first["summary"]["settings"].values()
    )
    assert all(x["successful"] == 5 for x in first["summary"]["settings"].values())
    barrier_totals = Counter()
    barrier_counts = Counter()
    inner_totals = Counter()
    for path in (output / "goals").glob("*/expert-events.json"):
        events = json.loads(path.read_text())
        policy = events[0]["policy"]["name"]
        assert events[0]["reset"]["method"] == "new_owned_process"
        transfers = [e for e in events if e["event"] == "expert_transfer"]
        if policy in {"history", "fixed"}:
            assert any(e["transfer"]["transferred_bytes"] == 64 for e in transfers)
        else:
            assert not transfers
        assert any(e["event"] == "tool_pause_start" for e in events)
        tools = json.loads(path.with_name("events.json").read_text())
        body_starts = [e for e in tools if e["event"] == "body_start"]
        pauses = [e for e in events if e["event"] == "tool_pause_start"]
        planning_starts = [e for e in events if e["event"] == "preparation_planning_start"]
        planning_ends = [e for e in events if e["event"] == "preparation_planning_end"]
        ready = [e for e in tools if e["event"] == "ready"]
        assert len(pauses) == len(body_starts)  # These tasks have one tool per decision.
        assert len(planning_starts) == len(planning_ends) == len(pauses)
        for begin, end, tool_ready, pause in zip(planning_starts, planning_ends, ready, pauses):
            assert begin["upcoming_pause_id"] == end["upcoming_pause_id"] == pause["pause_id"]
            assert begin["monotonic_ns"] <= end["monotonic_ns"] <= tool_ready["monotonic_ns"]
        for pause, body in zip(pauses, body_starts):
            assert pause["monotonic_ns"] >= body["observed_ns"] >= body["monotonic_ns"]
        if policy == "demand":
            assert not any(e["event"] == "preparation_admitted" for e in events)
            assert len([e for e in events if e["event"] == "preparation_skipped"]) == len(pauses)
        assert events[-1]["event"] == "goal_end"
        calls = json.loads(path.with_name("model-calls.json").read_text())
        assert "expected" not in json.dumps(calls[0]["request"])
        # Fixture sensor counter deltas are independent of transfer success.
        measurement = json.loads(path.with_name("measurement.json").read_text())
        record = json.loads(path.with_name("record.json").read_text())
        operating = json.loads(path.with_name("operating-state.json").read_text())
        assert operating["status"] == "unavailable"  # No invented fixture hardware.
        assert operating["simulated"] is True
        assert operating["samples"] == []
        assert record["started_ns"] <= planning_starts[0]["monotonic_ns"]
        inner = json.loads(path.with_name("initialized-model-window.json").read_text())
        assert inner["status"] == "valid"
        checkpoint = measurement["checkpoints"]
        for window in inner["measurements"]:
            domain = [s for s in measurement["samples"] if s["domain_id"] == window["domain_id"]]
            begin = next(s for s in domain if f":{checkpoint['initialized_model_start']}:" in s["sample_id"])
            end = next(s for s in domain if f":{checkpoint['initialized_model_end']}:" in s["sample_id"])
            assert window["energy_j"] == pytest.approx((end["value"] - begin["value"]) / 1e6)
            assert events[0]["startup_window"]["end_ns"] <= begin["acquired_start_ns"]
            assert begin["acquired_end_ns"] <= planning_starts[0]["monotonic_ns"]
            assert all(begin["acquired_end_ns"] <= s["start_ns"] <= s["end_ns"] <= end["acquired_start_ns"] for s in record["spans"])
            assert end["acquired_end_ns"] <= events[-1]["monotonic_ns"]
            before = next(m for m in inner["before_task_window"]["measurements"] if m["domain_id"] == window["domain_id"])
            after = next(m for m in inner["after_task_window"]["measurements"] if m["domain_id"] == window["domain_id"])
            outer = next(m for m in record["measurements"] if m["domain_id"] == window["domain_id"])
            assert before["energy_j"] + window["energy_j"] + after["energy_j"] == pytest.approx(outer["energy_j"])
            inner_totals[record["setting_id"], window["domain_id"]] += window["energy_j"]
        # Some Windows monotonic clocks resolve a short boundary to the same
        # tick. Check ordering and independent raw arithmetic, not duration > 0.
        finished = {
            e["pause_id"]: e["monotonic_ns"]
            for e in events
            if e["event"] == "tools_finished"
        }
        for event in events:
            if event["event"] == "model_resume":
                delta = event["monotonic_ns"] - finished[event["pause_id"]]
                assert delta >= 0
                barrier_totals[record["setting_id"]] += delta
                barrier_counts[record["setting_id"]] += 1
        for m in record["measurements"]:
            domain = [
                s for s in measurement["samples"] if s["domain_id"] == m["domain_id"]
            ]
            begin = next(s["value"] for s in domain if ":goal_start:" in s["sample_id"])
            end = next(s["value"] for s in domain if ":goal_end:" in s["sample_id"])
            assert m["energy_j"] == pytest.approx((end - begin) / 1e6)
    for setting, row in first["summary"]["settings"].items():
        assert barrier_counts[setting] == 10  # One data, two database, three repair, three ETL, one numerical call.
        assert row["resume_barrier_seconds"] == pytest.approx(
            barrier_totals[setting] / 1e9
        )
        assert row["initialized_model"]["attempts_with_valid_window"] == 5
        for domain, cost in row["initialized_model"]["energy"].items():
            assert cost["total_attempt_joules"] == pytest.approx(inner_totals[setting, domain])
            assert cost["joules_per_success"] == pytest.approx(inner_totals[setting, domain] / 5)
            assert cost["before_task_window_joules"] + cost["total_attempt_joules"] + cost["after_task_window_joules"] == pytest.approx(row["energy"][domain]["total_attempt_joules"])
    again = command(
        output, "--policies", "demand,history,fixed,bounded", "--max-runs", "20"
    )
    assert again["executed"] == 0
    assert again["validation"]["counts"]["attempts"] == 20
    # An adjacent JSON file is not evidence unless the ledger registered it.
    from studies.energy_diagnosis.moe.summary import summarize
    exports = output / "exports" / "attempts.jsonl"
    rows = [json.loads(line) for line in exports.read_text().splitlines()]
    for row in rows:
        row["attempt"]["artifacts"] = [a for a in row["attempt"]["artifacts"] if a["role"] != "initialized-model-window"]
    exports.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    unregistered = summarize(output)
    assert all(row["initialized_model"]["attempts_with_valid_window"] == 0 for row in unregistered["settings"].values())
    assert all(cost["total_attempt_joules"] is None for row in unregistered["settings"].values() for cost in row["initialized_model"]["energy"].values())


@pytest.mark.parametrize(
    "case",
    [
        "wrong_answer",
        "model_failure",
        "broken_ack",
        "cancel_failure",
        "drain_failure",
        "dropped",
        "missing_telemetry",
        "wrong_prediction",
        "locked",
        "tool_failure",
    ],
)
def test_failures_and_controls_are_not_silently_eligible(tmp_path, case):
    root = tmp_path / case
    result = command(
        root, "--fixture-case", case, "--policies", "fixed", "--max-runs", "1"
    )
    record = json.loads(next((root / "goals").glob("*/record.json")).read_text())
    inner = json.loads(next((root / "goals").glob("*/initialized-model-window.json")).read_text())
    assert record["simulated"] is True
    if case in {
        "wrong_answer",
        "model_failure",
        "broken_ack",
        "cancel_failure",
        "drain_failure",
        "dropped",
        "tool_failure",
    }:
        assert record["verifier"]["outcome"] != "pass"
        assert all(m["energy_j"] is not None for m in record["measurements"])
        summary = next(iter(result["summary"]["settings"].values()))
        assert summary["successful"] == 0
        assert all(d["joules_per_success"] is None for d in summary["energy"].values())
    if case == "missing_telemetry":
        assert inner["status"] == "unavailable"
        assert any(m["energy_j"] is None for m in record["measurements"])
        assert (
            next(iter(result["summary"]["settings"].values()))[
                "invalid_energy_attempts"
            ]
            == 1
        )
        summary = next(iter(result["summary"]["settings"].values()))["initialized_model"]
        assert summary["energy"]["GPU_FIXTURE"]["total_attempt_joules"] is None
        assert summary["energy"]["CPU_FIXTURE"]["total_attempt_joules"] is not None
    if case == "wrong_prediction":
        events = json.loads(
            next((root / "goals").glob("*/expert-events.json")).read_text()
        )
        assert any(e["event"] == "prepared_not_used_by_goal_end" for e in events)
    if case == "locked":
        events = json.loads(
            next((root / "goals").glob("*/expert-events.json")).read_text()
        )
        assert any(
            e["event"] == "preparation_admitted" and e["ack"]["rejected_bytes"]
            for e in events
        )
    if case in {"cancel_failure", "drain_failure", "dropped", "model_failure"}:
        assert inner["status"] != "valid"
    if case in {"wrong_answer", "wrong_prediction", "locked", "tool_failure", "broken_ack"}:
        assert inner["status"] == "valid"  # Failed outcomes still have measured cost.
    if case == "wrong_answer":
        assert result["window_audit"]["audit_passed"]
        assert result["window_audit"]["results"][0]["verifier_outcome"] == "fail"
        costs = next(iter(result["summary"]["settings"].values()))["initialized_model"]["energy"]
        assert all(c["total_attempt_joules"] > 0 and c["joules_per_success"] is None for c in costs.values())


def test_late_transfer_stale_callback_and_clean_reset(tmp_path):
    b = ProcessBackend(
        {"transfer_seconds": 0.15},
        python=sys.executable,
        mode="fixture",
        log_path=tmp_path / "backend.log",
    )
    control = Lifecycle(b, Policy("fixed", 64))
    control.begin_goal("g1")
    control.history[(0, 0)] = 1
    control.plan_pause()
    token = control.start_pause()
    # Ensure transfer has started before queued-only cancellation.
    time.sleep(0.03)
    begin = time.monotonic()
    control.end_pause(token)
    assert time.monotonic() - begin >= 0.08
    assert any(e["event"] == "expert_transfer" for e in control.events)
    control.request_id = "g1-request"
    control.end_goal()
    assert b.process is None
    control.begin_goal("g2")
    assert not control.history
    assert control.request_id == ""
    with pytest.raises(RuntimeError, match="stale"):
        control.end_pause(token)
    control.plan_pause()
    control.settle_work()
    assert b.process is not None  # The model remains resident after task work settles.
    with pytest.raises(RuntimeError, match="generation outside"):
        control.before_model("after-seal")
    control.settle_work()  # Idempotent; no second device work interval.
    control.end_goal()
    assert any(e["event"] == "preparation_plan_discarded" for e in control.events)
    assert control._pause_plan is None


def test_hung_rpc_is_killed_not_retried(tmp_path):
    b = ProcessBackend(
        {"fixture_case": "model_timeout"},
        python=sys.executable,
        mode="fixture",
        log_path=tmp_path / "backend.log",
    )
    b.reset_goal_state()
    with pytest.raises(Exception):
        b.generate("{}", 0.05, 10)
    assert b.process is None


def test_byte_budgets_history_and_no_future_inputs():
    es = [Expert(0, 0, 10, 1, 64, "cpu"), Expert(0, 1, 11, 2, 64, "cpu")]
    history = Counter({(0, 0): 3, (0, 1): 2})
    assert len(Policy("fixed", 64).select(es, history)[0]) == 1
    assert not Policy("fixed", 63).select(es, history)[0]
    assert not Policy("bounded", 128).select(es, history)[0]
    assert (
        len(
            Policy(
                "bounded", 128, bytes_per_second=64, expected_pause_seconds=1
            ).select(es, history)[0]
        )
        == 1
    )
    assert paired_interval([(1, 2)])["interval"] is None
    assert paired_interval([(1, 2), (3, 4)])["interval"] == [1, 1]
    with pytest.raises(ValueError):
        Policy("bounded", 128, bytes_per_second=float("nan"))


def test_demand_pause_does_not_call_preparation_backend():
    class NoPreparation:
        def snapshot_experts(self):
            pytest.fail("demand must not enumerate expert state")

        def prepare_experts(self, *args):
            pytest.fail("demand must not issue an empty preparation RPC")

    control = Lifecycle(NoPreparation(), Policy("demand"))
    control.goal = "owned-fixture"
    control.plan_pause()
    token = control.start_pause()
    assert token == (0, "owned-fixture:pause:1")
    assert [e["event"] for e in control.events] == [
        "preparation_planning_start", "preparation_planning_end",
        "tool_pause_start", "preparation_skipped",
    ]


def test_planning_does_not_admit_transfers_and_cannot_cross_model_requests():
    class Probe:
        def __init__(self):
            self.calls = []

        def snapshot_experts(self):
            self.calls.append("snapshot")
            return [Expert(0, 0, 10, 1, 64, "cpu")]

        def prepare_experts(self, selected, generation, budget):
            self.calls.append("prepare")
            assert len(selected) == 1 and selected[0].node == 1 and budget == 64
            return dict(accepted_nodes=[1], accepted_bytes=64, inflight_bytes=64)

    backend = Probe()
    control = Lifecycle(backend, Policy("fixed", 64))
    control.goal = "g"
    control.history[(0, 0)] = 1
    with pytest.raises(RuntimeError, match="invalid pause"):
        control.start_pause()
    control.plan_pause()
    assert backend.calls == ["snapshot"]
    with pytest.raises(RuntimeError, match="planning state"):
        control.plan_pause()
    with pytest.raises(RuntimeError, match="generation outside"):
        control.before_model("intervening-request")
    control.request_id = "changed-request"
    with pytest.raises(RuntimeError, match="stale preparation"):
        control.start_pause()
    control.request_id = ""
    control.start_pause()
    assert backend.calls == ["snapshot", "prepare"]  # No snapshot on admission.
    with pytest.raises(RuntimeError, match="invalid pause"):
        control.start_pause()


def test_native_bridge_calls_actual_native_methods():
    from studies.energy_diagnosis.moe.native_backend import NativeDevice
    from types import SimpleNamespace

    class Native:
        def __init__(self):
            self.calls = []

        def get_inflight_prefetch_bytes(self):
            return 0

        def alems_expert_info(self, tensor):
            return (7, 64, "cpu")

        def schedule_prefetch_tensors(self, *args):
            self.calls.append(args)
            return SimpleNamespace(
                accepted_tensor_ids=[7],
                accepted_bytes=64,
                rejected_bytes=0,
                inflight_bytes=64,
            )

        def cancel_prefetch_generation(self, *args):
            self.calls.append(args)
            return 0

    d = NativeDevice.__new__(NativeDevice)
    d.mapping = {(0, 3): 100}
    d.native = Native()
    snapshot = d.snapshot(None)
    result = d.prepare(dict(experts=snapshot, generation=12, budget=64))
    assert d.native.calls == [([100], 1, 12, -1, 64)]
    assert result["accepted_nodes"] == [7]  # Node IDs are not tensor IDs.
    d.cancel({"generation": 12})
    assert d.native.calls[-1] == (12, -1, [])


def test_tool_timeout_still_drains_preparation(tmp_path):
    command(
        tmp_path,
        "--fixture-case",
        "tool_timeout",
        "--policies",
        "fixed",
        "--max-runs",
        "1",
        "--deadline",
        "8",  # Allow spawned worker startup on Windows; injected tool sleeps 20s.
    )
    path = next((tmp_path / "goals").glob("*/record.json"))
    record = json.loads(path.read_text())
    assert record["execution_status"] == "timed_out"
    events = json.loads(path.with_name("expert-events.json").read_text())
    assert events[-1]["event"] == "goal_end"
    assert any(e["event"] == "model_resume" for e in events)


def test_missing_attempt_cost_is_unknown_not_dropped(tmp_path):
    from studies.energy_diagnosis.moe.summary import summarize

    (tmp_path / "exports").mkdir()
    row = dict(
        plan={"setting_id": "fixed"},
        attempt=dict(
            execution_id="lost", execution_record=None, started_ns=1, ended_ns=None
        ),
    )
    (tmp_path / "exports/attempts.jsonl").write_text(json.dumps(row) + "\n")
    result = summarize(tmp_path)["settings"]["fixed"]
    assert result["attempts"] == 1 and result["invalid_energy_attempts"] == 1
    assert result["successful"] == 0 and result["total_seconds"] is None


def test_native_worker_cannot_fall_back_to_simulation(tmp_path):
    backend = ProcessBackend(
        {}, python=sys.executable, mode="native", log_path=tmp_path / "native.log"
    )
    with pytest.raises(RuntimeError):
        backend.reset_goal_state()
    assert backend.process is None
    assert not backend.reset_evidence


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal delivery to the campaign command")
def test_sigterm_terminates_owned_work_and_leaves_attempt_for_recovery(tmp_path):
    """A supervisor stop must not orphan the model worker or a running tool."""
    import signal
    import psutil

    process = subprocess.Popen(
        [sys.executable, "-m", "studies.energy_diagnosis.moe.run", "--mode", "fixture",
         "--output", str(tmp_path), "--fixture-case", "tool_timeout", "--policies", "fixed",
         "--max-runs", "1", "--deadline", "30"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    parent = psutil.Process(process.pid)
    deadline = time.monotonic() + 30
    owned = []
    while time.monotonic() < deadline:
        owned = parent.children(recursive=True)
        names = " ".join(" ".join(p.cmdline()) for p in owned if p.is_running())
        if "moe.worker" in names and "multiprocessing" in names:
            break
        time.sleep(0.05)
    assert any("moe.worker" in " ".join(p.cmdline()) for p in owned), "worker never started"
    process.send_signal(signal.SIGTERM)
    _, stderr = process.communicate(timeout=60)
    assert process.returncode == 130, stderr
    assert "left for recovery" in stderr
    gone, alive = psutil.wait_procs(owned, timeout=10)
    assert not [p for p in alive if p.is_running() and p.status() != psutil.STATUS_ZOMBIE], stderr
    from studies.energy_diagnosis.campaign import RunLedger

    with RunLedger(tmp_path / "ledger.sqlite", artifact_root=tmp_path) as ledger:
        running = ledger.running_attempts()
        assert len(running) == 1 and ledger.validate()["counts"]["running"] == 1
    assert (tmp_path / "exports" / "attempts.jsonl").exists()


@pytest.mark.parametrize("partial_artifact", [False, True])
def test_recovered_interrupted_attempt_resumes_summarizes_and_audits(tmp_path, partial_artifact):
    from studies.energy_diagnosis.campaign import RunLedger
    from studies.energy_diagnosis.campaign.recover import reconcile
    from studies.energy_diagnosis.moe.audit_windows import audit
    from studies.energy_diagnosis.moe.summary import summarize

    output = tmp_path / "campaign"
    first = command(output, "--policies", "demand", "--max-runs", "1")
    assert first["executed"] == 1
    # Simulate an interrupted claim from a separate fixture session.
    with RunLedger(output / "ledger.sqlite", artifact_root=output) as ledger:
        schedule_id = json.loads((output / "state" / "schedule.json").read_text())["schedule_id"]
        lease = ledger.claim_next(session_id="fixture-interrupted", started_ns=10 ** 12,
                                  clock_domain="fixture:test-host:process-1-1:monotonic",
                                  metadata={"schedule_id": schedule_id, "requested_resources": {}})
    assert lease is not None
    if partial_artifact:
        import hashlib
        from studies.energy_diagnosis.campaign import ArtifactRef
        plan = next(json.loads(line)["plan"] for line in (output / "exports/plans.jsonl").read_text().splitlines()
                    if json.loads(line)["plan"]["planned_run_id"] == lease.planned_run_id)
        retained = json.loads(next((output / "goals").glob("*/record.json")).read_text())
        retained.update(goal_execution_id=lease.execution_id, planned_run_id=lease.planned_run_id,
                        session_id=lease.session_id, task_id=plan["task_id"], setting_id=plan["setting_id"],
                        attempt_number=lease.attempt_number, clock_domain=lease.clock_domain,
                        started_ns=lease.started_ns, ended_ns=lease.started_ns+1,
                        execution_status="crashed", measurements=[], spans=[])
        retained_path = output / "goals" / lease.execution_id / "record.json"
        retained_path.parent.mkdir()
        retained_path.write_text(json.dumps(retained))
        ref = ArtifactRef(path=retained_path.relative_to(output).as_posix(), sha256=hashlib.sha256(retained_path.read_bytes()).hexdigest(), role="execution-record")
        with RunLedger(output / "ledger.sqlite", artifact_root=output) as ledger:
            ledger.checkpoint(lease, [ref], metadata={"owned_work_terminated": False})
    blocked = command(output, "--policies", "demand", "--max-runs", "5")
    assert blocked["executed"] == 0 and blocked["validation"]["counts"]["running"] == 1
    status = tmp_path / "status.json"
    status.write_text(json.dumps(dict(status="interrupted", returncode=130, child_pid=4321,
                                      cleanup_complete=True, finished_utc="2026-09-22T00:00:00+00:00")))
    result = reconcile(campaign_dir=output, session_id="fixture-interrupted",
                       clock_domain="fixture:test-host:process-1-1:monotonic", ended_ns=10 ** 12 + 5,
                       reason="fixture supervisor interruption", supervisor_status=status,
                       apply=True, owned_work_terminated=True)
    assert result["recovered_attempt_ids"] == [lease.attempt_id]
    resumed = command(output, "--policies", "demand", "--max-runs", "5")
    # The campaign command keeps the ledger default retry limit (0): the interrupted
    # slot is retained as incomplete evidence and is not silently re-run.
    assert resumed["executed"] == 3 and resumed["validation"]["valid"]
    counts = resumed["validation"]["counts"]
    assert counts["attempts"] == 5 and counts["running"] == 0 and counts["pending"] == 0
    rows = [json.loads(line) for line in (output / "exports" / "attempts.jsonl").read_text().splitlines()]
    statuses = Counter(row["attempt"]["execution_status"] for row in rows)
    assert statuses == {"completed": 4, "incomplete": 1}
    assert max(Counter(row["plan"]["planned_run_id"] for row in rows).values()) == 1  # never duplicated
    summary = summarize(output)
    (setting,) = summary["settings"].values()
    assert setting["attempts"] == 5 and setting["successful"] == 4 and setting["invalid_energy_attempts"] == 1
    assert setting["initialized_model"]["attempts_with_valid_window"] == 4
    assert all(cost["total_attempt_joules"] is None for cost in setting["energy"].values())  # one unknown cost
    report = audit(output)
    assert report["audit_passed"] and report["attempts"] == 5
    recovered = [r for r in report["results"] if r.get("recovered")]
    assert len(recovered) == 1 and recovered[0]["all_domains_measured"] is False
    assert recovered[0]["execution_status"] == "incomplete" and recovered[0]["verifier_outcome"] == "unavailable"
    assert sum(r["all_domains_measured"] for r in report["results"]) == 4
    dispositions = {d["planned_run_id"]: d["disposition"] for d in resumed["validation"]["dispositions"]}
    assert dispositions[lease.planned_run_id] != "pending"
    again = command(output, "--policies", "demand", "--max-runs", "5")
    assert again["executed"] == 0
    if partial_artifact:
        retained_path.write_text(retained_path.read_text() + " ")
        assert not audit(output)["audit_passed"]
        with pytest.raises(ValueError, match="artifact hash mismatch"):
            summarize(output)


def test_killed_worker_counts_as_terminated_but_not_idle(tmp_path):
    """A reaped worker cannot own device work; the batch must finalize the
    attempt instead of aborting, while the forced stop stays visible."""
    backend = ProcessBackend(
        {"fixture_case": "model_timeout"}, python=sys.executable, mode="fixture",
        log_path=tmp_path / "backend.log",
    )
    backend.reset_goal_state()
    assert backend.owned_work_terminated is False and backend.termination_forced is False
    with pytest.raises(RuntimeError, match="no response within"):
        backend.generate("{}", 0.05, 10)
    assert backend.process is None
    assert backend.owned_work_terminated is True
    assert backend.termination_forced is True and backend.idle_confirmed is False
    backend.reset_goal_state()
    assert backend.termination_forced is False  # A fresh owned process starts clean.
    backend.end_goal()
    assert backend.termination_forced is False  # Idle at kill time is not forced.


def test_forced_native_termination_invalidates_energy_but_finalizes():
    from studies.energy_diagnosis.local_run import GoalExecutor
    from types import SimpleNamespace

    def executor(simulated, forced):
        e = GoalExecutor.__new__(GoalExecutor)
        e.simulated = simulated
        e.lifecycle = SimpleNamespace(backend=SimpleNamespace(termination_forced=forced))
        return e

    assert executor(False, True)._termination_invalidity(False) == "live model termination unverified"
    assert executor(False, True)._termination_invalidity(True) == "owned worker terminated before device work was confirmed idle"
    assert executor(False, False)._termination_invalidity(True) is None
    assert executor(True, True)._termination_invalidity(True) is None  # Fixture devices have no idle semantics.


def test_startup_timeout_reaps_worker_without_claiming_device_drain(tmp_path):
    backend = ProcessBackend({}, python=sys.executable, mode="fixture",
                             log_path=tmp_path / "startup.log", timeout=0.000001)
    control = Lifecycle(backend, Policy("demand", 0))
    with pytest.raises(RuntimeError, match="no response within"):
        control.begin_goal("failed-start")
    assert control.goal is None
    assert backend.process is None
    assert backend.owned_work_terminated
    assert not backend.idle_confirmed
    control.end_goal()
    backend.timeout = 10
    control.begin_goal("next-start")
    control.end_goal()
    assert backend.owned_work_terminated


def test_termination_status_does_not_depend_on_device_drain(tmp_path):
    backend = ProcessBackend({"fixture_case": "model_timeout"},
                             python=sys.executable, mode="fixture",
                             log_path=tmp_path / "timeout.log")
    backend.reset_goal_state()
    with pytest.raises(RuntimeError, match="no response within"):
        backend.generate("{}", 0.01, 10)
    assert backend.owned_work_terminated
    assert not backend.idle_confirmed
    backend.termination_confirmed = False
    assert not backend.owned_work_terminated


def test_startup_timeout_recorded_and_next_slot_runs(tmp_path, monkeypatch):
    from studies.energy_diagnosis.moe import run as campaign
    original = ProcessBackend.reset_goal_state
    starts = []

    def reset(self):
        starts.append(1)
        if len(starts) == 1:
            self.timeout = 0.000001
        return original(self)

    monkeypatch.setattr(ProcessBackend, "reset_goal_state", reset)
    campaign.main(["--mode", "fixture", "--output", str(tmp_path),
                   "--task", "joined-orders-v1", "--policies", "demand,fixed",
                   "--max-runs", "2", "--deadline", "30"])
    records = [json.loads(p.read_text()) for p in (tmp_path / "goals").glob("*/record.json")]
    assert len(records) == 2
    failed = next(r for r in records if r["execution_status"] == "crashed")
    assert "no response within" in failed["error"]
    assert "no owned goal" not in failed["error"]
    assert failed["verifier"]["outcome"] == "unavailable"
    assert any(r["verifier"]["outcome"] == "pass" for r in records)
    for p in (tmp_path / "goals").glob("*/record.json"):
        if json.loads(p.read_text())["execution_status"] == "crashed":
            assert json.loads(p.with_name("initialized-model-window.json").read_text())["status"] != "valid"


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group ownership")
def test_surviving_process_group_refuses_termination_claim(tmp_path, monkeypatch):
    import psutil
    from types import SimpleNamespace
    backend = ProcessBackend({}, python=sys.executable, mode="fixture",
                             log_path=tmp_path / "group.log")
    backend.reset_goal_state()
    group = backend.process.pid
    real_getpgid = os.getpgid
    fake_pid = 2147483646
    monkeypatch.setattr(psutil, "process_iter", lambda *args: [
        SimpleNamespace(pid=fake_pid, status=lambda: psutil.STATUS_RUNNING)])
    monkeypatch.setattr(os, "getpgid", lambda pid: group if pid == fake_pid else real_getpgid(pid))
    with pytest.raises(RuntimeError, match="process group termination unverified"):
        backend.end_goal()
    assert backend.process is None
    assert not backend.owned_work_terminated



def test_explicit_longer_goal_budget_is_finite_and_pinned(tmp_path):
    result = command(tmp_path / "allowed", "--task", "joined-orders-v1", "--policies", "demand",
                     "--max-runs", "1", "--deadline", "1200")
    assert result["executed"] == 1
    limits = json.loads((tmp_path / "allowed/moe-manifest.json").read_text())["limits"]
    assert limits == dict(goal_seconds=1200, max_steps=5, max_output_tokens=512)
    for invalid in ("1801", "nan", "inf", "0"):
        rejected = subprocess.run([sys.executable, "-m", "studies.energy_diagnosis.moe.run", "--mode", "fixture",
                                   "--output", str(tmp_path / ("bad-"+invalid)), "--deadline", invalid],
                                  cwd=ROOT, capture_output=True, text=True, timeout=30)
        assert rejected.returncode == 2
        assert "invalid bounded" in rejected.stderr
        assert not (tmp_path / ("bad-"+invalid)).exists()


def test_cpu_affinity_is_parsed_applied_and_recorded(tmp_path):
    from studies.energy_diagnosis.moe.run import parse_cpu_list
    assert parse_cpu_list("64-67,70,66") == [64, 65, 66, 67, 70]
    for invalid in ("", "5-3", "-1", "a"):
        with pytest.raises(ValueError):
            parse_cpu_list(invalid)
    if not hasattr(os, "sched_getaffinity"):
        rejected = subprocess.run([sys.executable, "-m", "studies.energy_diagnosis.moe.run", "--mode", "fixture",
                                   "--output", str(tmp_path / "unsupported"), "--cpu-affinity", "0"],
                                  cwd=ROOT, capture_output=True, text=True, timeout=30)
        assert rejected.returncode == 2 and "not supported" in rejected.stderr
        return
    cpu = min(os.sched_getaffinity(0))
    command(tmp_path / "pinned", "--task", "joined-orders-v1", "--policies", "demand", "--max-runs", "1",
            "--cpu-affinity", str(cpu))
    manifest = json.loads((tmp_path / "pinned/moe-manifest.json").read_text())
    assert manifest["cpu_affinity"] == dict(pinned=True, cpus=[cpu])
    command(tmp_path / "unpinned", "--task", "joined-orders-v1", "--policies", "demand", "--max-runs", "1")
    manifest = json.loads((tmp_path / "unpinned/moe-manifest.json").read_text())
    assert manifest["cpu_affinity"]["pinned"] is False


def test_cpu_power_state_groups_cpus_by_governor_and_idle_states(tmp_path):
    from studies.energy_diagnosis.moe.run import cpu_power_state
    for cpu, disabled in ((0, "0"), (1, "0"), (2, "1")):
        base = tmp_path / f"cpu{cpu}"
        (base / "cpufreq").mkdir(parents=True)
        (base / "cpufreq/scaling_governor").write_text("schedutil\n")
        for i, (name, latency) in enumerate((("POLL", "0"), ("C1", "1"), ("C2", "30"))):
            state = base / f"cpuidle/state{i}"
            state.mkdir(parents=True)
            (state / "name").write_text(name + "\n")
            (state / "latency").write_text(latency + "\n")
            (state / "disable").write_text((disabled if name == "C2" else "0") + "\n")
    groups = cpu_power_state([0, 1, 2], root=tmp_path)
    assert sorted(g["cpus"] for g in groups) == [[0, 1], [2]]
    deep = next(g for g in groups if g["cpus"] == [2])
    assert deep["governor"] == "schedutil" and deep["min_khz"] is None
    assert deep["idle"][2] == dict(name="C2", exit_latency_us="30", disabled="1")
    assert cpu_power_state(None, root=tmp_path) is None
    assert cpu_power_state([0], root=tmp_path / "missing") is None


def test_keep_awake_is_owned_recorded_and_stopped(tmp_path):
    if not hasattr(os, "sched_getaffinity"):
        rejected = subprocess.run([sys.executable, "-m", "studies.energy_diagnosis.moe.run", "--mode", "fixture",
                                   "--output", str(tmp_path / "unsupported"), "--keep-awake-cpus", "0"],
                                  cwd=ROOT, capture_output=True, text=True, timeout=30)
        assert rejected.returncode == 2 and "Linux" in rejected.stderr
        return
    import psutil
    cpus = sorted(os.sched_getaffinity(0))
    if len(cpus) < 2:
        pytest.skip("needs two CPUs")
    overlap = subprocess.run([sys.executable, "-m", "studies.energy_diagnosis.moe.run", "--mode", "fixture",
                              "--output", str(tmp_path / "overlap"), "--cpu-affinity", str(cpus[0]),
                              "--keep-awake-cpus", str(cpus[0])], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert overlap.returncode == 2 and "must not overlap" in overlap.stderr
    before = {p.pid for p in psutil.process_iter()}
    command(tmp_path / "kept", "--task", "joined-orders-v1", "--policies", "demand", "--max-runs", "1",
            "--cpu-affinity", str(cpus[0]), "--keep-awake-cpus", str(cpus[1]))
    manifest = json.loads((tmp_path / "kept/moe-manifest.json").read_text())
    assert manifest["keep_awake"] == dict(cpus=[cpus[1]], method="owned python busy loop per CPU")
    assert sorted(c for group in (manifest["cpu_power"] or []) for c in group["cpus"]) in ([cpus[0], cpus[1]], []) \
        or manifest["cpu_power"] is None
    leftover = [p for p in psutil.process_iter(["cmdline"]) if p.pid not in before
                and "sched_setaffinity" in " ".join(p.info["cmdline"] or [])]
    assert not leftover
    # Resuming the same campaign directory must see an identical manifest.
    command(tmp_path / "kept", "--task", "joined-orders-v1", "--policies", "demand", "--max-runs", "1",
            "--cpu-affinity", str(cpus[0]), "--keep-awake-cpus", str(cpus[1]))


def test_tool_cpus_are_recorded_and_must_not_overlap(tmp_path):
    command(tmp_path / "tools", "--task", "joined-orders-v1", "--policies", "demand", "--max-runs", "1",
            "--tool-cpus", "3,5")
    assert json.loads((tmp_path / "tools/moe-manifest.json").read_text())["tool_cpus"] == [3, 5]
    if hasattr(os, "sched_getaffinity"):
        cpu = min(os.sched_getaffinity(0))
        overlap = subprocess.run([sys.executable, "-m", "studies.energy_diagnosis.moe.run", "--mode", "fixture",
                                  "--output", str(tmp_path / "overlap"), "--cpu-affinity", str(cpu), "--tool-cpus", str(cpu)],
                                 cwd=ROOT, capture_output=True, text=True, timeout=30)
        assert overlap.returncode == 2 and "must not overlap" in overlap.stderr


def test_campaign_exit_keeps_model_failures_as_data_but_stops_on_crash(tmp_path, monkeypatch):
    # A wrong/unfinished answer is campaign data: exit 0 with the failure recorded.
    result = command(tmp_path / "failing", "--task", "joined-orders-v1", "--policies", "demand", "--max-runs", "1",
                     "--fixture-case", "no_action", "--campaign-exit")
    row = next(iter(result["summary"]["settings"].values()))
    assert row["attempts"] == 1 and row["successful"] == 0
    # An infrastructure crash stops the campaign for review (exit 3).
    from studies.energy_diagnosis.moe import run as campaign
    original = ProcessBackend.reset_goal_state

    def reset(self):
        self.timeout = 0.000001
        return original(self)

    monkeypatch.setattr(ProcessBackend, "reset_goal_state", reset)
    with pytest.raises(SystemExit) as stopped:
        campaign.main(["--mode", "fixture", "--output", str(tmp_path / "crash"), "--task", "joined-orders-v1",
                       "--policies", "demand", "--max-runs", "1", "--deadline", "30", "--campaign-exit"])
    assert stopped.value.code == 3
