"""Real tool execution and the same owned RPC/lifecycle interface as the GPU path."""
from collections import Counter
import json
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
        output, "--policies", "demand,history,fixed,bounded", "--max-runs", "8"
    )
    assert first["executed"] == 8
    assert first["validation"]["valid"]
    assert all(
        x["startup_seconds"] > 0 and x["resume_barrier_seconds"] >= 0
        for x in first["summary"]["settings"].values()
    )
    assert all(x["successful"] == 2 for x in first["summary"]["settings"].values())
    barrier_totals = Counter()
    barrier_counts = Counter()
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
        assert events[-1]["event"] == "goal_end"
        calls = json.loads(path.with_name("model-calls.json").read_text())
        assert "expected" not in json.loads(calls[0]["prompt"])
        # Fixture sensor counter deltas are independent of transfer success.
        measurement = json.loads(path.with_name("measurement.json").read_text())
        record = json.loads(path.with_name("record.json").read_text())
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
        assert barrier_counts[setting] == 4  # One data tool and three repair tools.
        assert row["resume_barrier_seconds"] == pytest.approx(
            barrier_totals[setting] / 1e9
        )
    again = command(
        output, "--policies", "demand,history,fixed,bounded", "--max-runs", "8"
    )
    assert again["executed"] == 0
    assert again["validation"]["counts"]["attempts"] == 8


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
        assert any(m["energy_j"] is None for m in record["measurements"])
        assert (
            next(iter(result["summary"]["settings"].values()))[
                "invalid_energy_attempts"
            ]
            == 1
        )
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
    token = control.start_pause()
    # Ensure transfer has started before queued-only cancellation.
    time.sleep(0.03)
    begin = time.monotonic()
    control.end_pause(token)
    assert time.monotonic() - begin >= 0.08
    assert any(e["event"] == "expert_transfer" for e in control.events)
    control.end_goal()
    assert b.process is None
    control.begin_goal("g2")
    assert not control.history
    with pytest.raises(RuntimeError, match="stale"):
        control.end_pause(token)
    control.end_goal()


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
        "1",
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
