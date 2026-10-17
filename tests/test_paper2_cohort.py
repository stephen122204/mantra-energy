"""Shared-server cohort runner: fixture tests (no GPU, no model).

End-to-end cases need mistral_common and a tekken.json (PAPER2_TEKKEN=/path/to/tekken.json);
they are skipped otherwise. The fixture server only stands in for vLLM's HTTP protocol.
"""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from studies.paper2.cohort import energy, records, telemetry
from studies.paper2.cohort.forcing import encode_forced, parse_forced

TEKKEN = os.environ.get("PAPER2_TEKKEN")
needs_renderer = pytest.mark.skipif(not (TEKKEN and Path(TEKKEN).exists()), reason="PAPER2_TEKKEN not set")


def S(domain, t_s, value, status="ok"):
    ns = int(t_s * 1e9)
    return SimpleNamespace(domain_id=domain, acquired_start_ns=ns, acquired_end_ns=ns, status=status, value=value)


def test_forced_token_encoding_round_trip():
    assert parse_forced(encode_forced([5, 0, 131071])) == [5, 0, 131071]
    assert parse_forced("") is None and parse_forced(None) is None
    with pytest.raises(ValueError):
        parse_forced("1,-2")


def test_prometheus_parse_sums_label_sets_and_ignores_others():
    text = ('# HELP x\nvllm:num_requests_running{model_name="a"} 3\nvllm:num_requests_running{model_name="b"} 1\n'
            'vllm:prompt_tokens_total{m="a"} 1.5e3\nother_metric 9\n')
    out = telemetry.parse_prometheus(text)
    assert out == {"vllm:num_requests_running": 4.0, "vllm:prompt_tokens_total": 1500.0}


def test_energy_bridges_short_gap_and_handles_wrap():
    rows = [S("PACKAGE_SOCKET_0", 0.0, 900), S("PACKAGE_SOCKET_0", 0.1, None, "missing"),
            S("PACKAGE_SOCKET_0", 0.2, 990), S("PACKAGE_SOCKET_0", 0.3, 40)]
    out = energy.integrate_samples(rows, 0, int(0.3e9), counter_max=1000, unit_scale=1.0)["PACKAGE_SOCKET_0"]
    assert out.status == "valid" and out.energy_j == 140 and out.wraps == 1 and out.samples_missing == 1


def test_energy_long_gap_and_reset_invalidate():
    gap = [S("GPU_BOARD_0", 0, 0), S("GPU_BOARD_0", 45, 10)]
    assert energy.integrate_samples(gap, 0, int(45e9), max_gap_s=30)["GPU_BOARD_0"].status == "invalid"
    reset = [S("GPU_BOARD_0", 0, 500), S("GPU_BOARD_0", 1, 400)]
    assert energy.integrate_samples(reset, 0, int(1e9), counter_max=1000)["GPU_BOARD_0"].status == "invalid"


def test_records_reconcile_and_manifest_detects_tampering(tmp_path):
    log = records.EventLog(tmp_path / "events.jsonl")
    log.append("offered", attempt_id="a1", task_id="t")
    log.append("offered", attempt_id="a2", task_id="t2")
    log.append("terminal", attempt_id="a1", outcome="completed")
    rec = records.reconcile(log.read())
    assert rec["open"] == ["a2"] and not rec["reconciled"]
    log.append("terminal", attempt_id="a2", outcome="infra_failed")
    assert records.reconcile(log.read())["reconciled"]
    log.close()
    records.write_manifest(tmp_path)
    assert records.verify_manifest(tmp_path) == []
    (tmp_path / "events.jsonl").write_text("tampered\n")
    assert records.verify_manifest(tmp_path) == ["mismatch events.jsonl"]


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    pytest.importorskip("mistral_common")
    if not (TEKKEN and Path(TEKKEN).exists()):
        pytest.skip("PAPER2_TEKKEN not set")
    from studies.paper2.cohort.taskprep import prepare_tasks
    out = tmp_path_factory.mktemp("prep")
    specs = [dict(kind="business", rows=64, seed=7), dict(kind="etl", rows=64, seed=7), dict(kind="numerical", rows=64, seed=7)]
    return prepare_tasks(specs, out)


def _spec(catalog, task_ids, server, **kw):
    from studies.paper2.cohort.cohort import CohortSpec
    from studies.paper2.cohort.taskprep import cohort_items
    limits = dict(max_turns=3, max_tool_calls=10, max_total_output_tokens=2048, max_tokens=256, deadline_s=60,
                  verify_timeout_s=120)
    limits.update(kw.pop("limits", {}))
    return CohortSpec(cohort_id=kw.pop("cohort_id"), config_id="fixture-cfg", served_model=server.served_model,
                      base_url=server.base_url, max_model_len=32768, tekken=TEKKEN,
                      tasks=cohort_items(catalog, task_ids), limits=limits, grace_s=kw.pop("grace_s", 10), **kw)


def _events(root):
    return [json.loads(l) for l in (root / "events.jsonl").read_text().splitlines()]


@needs_renderer
def test_cohort_shares_one_server_and_reconciles(prepared, tmp_path):
    from studies.paper2.cohort.client import MistralRenderer
    from studies.paper2.cohort.cohort import run_cohort
    from studies.paper2.cohort.fake_server import FakeVllm
    ids = [c["task_id"] for c in prepared][:4]
    with FakeVllm(MistralRenderer(TEKKEN), delay_s=0.8) as srv:
        summary = run_cohort(_spec(prepared, ids, srv, cohort_id="c-fixed", admission_limit=3), tmp_path)
        assert srv.peak >= 2, "sessions must overlap in the shared server"
    root = tmp_path / "c-fixed"
    assert summary["reconciliation"]["reconciled"] and summary["offered"] == 4
    assert summary["outcomes"] == {"completed": 4}
    # submit_answer {} is a wrong answer: graded fail by the trusted verifier, never pass.
    assert {s["verdict"] for s in summary["sessions"]} == {"fail"}
    ev = _events(root)
    end = next(e["seq"] for e in ev if e["kind"] == "interval_end")
    assert all(e["seq"] > end for e in ev if e["kind"] == "verified"), "verification must follow the energy interval"
    assert max(e["active_after"] for e in ev if e["kind"] == "admitted") == 3
    assert summary["joules_per_verified_success"] is None
    assert records.verify_manifest(root) == []
    # workspaces are per session and distinct
    ws = [p for p in (root / "sessions").glob("*/workspaces/*")]
    assert len(ws) == 4 and len({p.parent.parent for p in ws}) == 4


@needs_renderer
def test_failure_outcomes_are_explicit(prepared, tmp_path):
    from studies.paper2.cohort.client import MistralRenderer
    from studies.paper2.cohort.cohort import run_cohort
    from studies.paper2.cohort.fake_server import FakeVllm
    ids = [c["task_id"] for c in prepared][:2]
    r = MistralRenderer(TEKKEN)
    with FakeVllm(r, mode="text") as srv:
        s1 = run_cohort(_spec(prepared, ids, srv, cohort_id="c-text", admission_limit=2), tmp_path)
    assert s1["outcomes"] == {"agent_failed": 2}
    with FakeVllm(r, mode="error") as srv:
        s2 = run_cohort(_spec(prepared, ids, srv, cohort_id="c-err", admission_limit=2), tmp_path)
    assert s2["outcomes"] == {"infra_failed": 2} and s2["infra_invalid"]
    assert {s["verdict"] for s in s1["sessions"] + s2["sessions"]} == {"not_run"}


@needs_renderer
def test_arrivals_queue_and_cohort_deadline_cancel(prepared, tmp_path):
    from studies.paper2.cohort.client import MistralRenderer
    from studies.paper2.cohort.cohort import run_cohort
    from studies.paper2.cohort.fake_server import FakeVllm
    ids = [c["task_id"] for c in prepared][:3]
    r = MistralRenderer(TEKKEN)
    with FakeVllm(r, delay_s=1.0) as srv:
        s = run_cohort(_spec(prepared, ids, srv, cohort_id="c-arr", admission_limit=1, mode="arrivals",
                             arrival_offsets_s=[0.0, 0.2, 0.2]), tmp_path)
    ev = _events(tmp_path / "c-arr")
    waits = [e["queue_wait_s"] for e in ev if e["kind"] == "admitted"]
    assert waits[0] < 0.5 and max(waits[1:]) > 0.5, "later arrivals wait for the single admission slot"
    assert s["outcomes"] == {"completed": 3}
    with FakeVllm(r, delay_s=30) as srv:
        s = run_cohort(_spec(prepared, ids, srv, cohort_id="c-cut", admission_limit=1, cohort_deadline_s=2.0), tmp_path)
    assert s["reconciliation"]["reconciled"]
    assert s["outcomes"].get("cancelled", 0) == 3


@needs_renderer
def test_replay_reproduces_prompts_and_forces_outputs(prepared, tmp_path):
    from studies.paper2.cohort.client import MistralRenderer
    from studies.paper2.cohort.cohort import run_cohort
    from studies.paper2.cohort.fake_server import FakeVllm
    from studies.paper2.cohort.replay import load_live_session, run_replay
    ids = [c["task_id"] for c in prepared if c["task_kind"] in ("business", "numerical")][:3]
    r = MistralRenderer(TEKKEN)
    with FakeVllm(r, mode="tool") as srv:
        live = run_cohort(_spec(prepared, ids, srv, cohort_id="c-live", admission_limit=3), tmp_path)
    assert live["outcomes"] == {"completed": 3}
    for d in (tmp_path / "c-live" / "sessions").iterdir():
        assert json.loads((d / "tool-results.json").read_text()), "a real task tool ran in the session"
    sessions = [load_live_session(p) for p in sorted((tmp_path / "c-live" / "sessions").iterdir())]
    assert all(len(s.turns) == 2 and s.turns[0].gap_after_s > 0 for s in sessions)
    assert all(s.turns[1].prompt_ids[: len(s.turns[0].prompt_ids)] == s.turns[0].prompt_ids for s in sessions)
    # the replay server would otherwise answer with *text*; forcing must reproduce recorded outputs
    with FakeVllm(r, mode="text") as srv:
        out = run_replay("rp-1", sessions, srv.base_url, srv.served_model, tmp_path, admission_limit=2)
    assert out["failed"] == 0 and out["mismatched_turns"] == 0
    live_prompts = sum(len(t.prompt_ids) for s in sessions for t in s.turns)
    assert out["prompt_tokens"] == live_prompts
    assert records.verify_manifest(tmp_path / "rp-1") == []


@needs_renderer
def test_pilot_driver_fixture_end_to_end(tmp_path):
    pytest.importorskip("mistral_common")
    from studies.paper2.cohort import pilot
    cfg = lambda n: dict(name=n, model=f"/nonexistent/{n}", revision="fixture", weight_precision="int4",
                         activation_precision="bf16", max_model_len=32768)
    steps = [{"live": dict(name="n2", admission_limit=2, task_ids=["business-segments-v2-n64-s7", "grouped-fit-v1-n64-s7"],
                           seed=3, est_s=60)},
             {"replay": dict(name="replay-n2", source="n2", admission_limit=2, est_s=60)},
             {"live": dict(name="too-long", admission_limit=1, task_ids=["business-orphans-v2-n64-s7"], est_s=10**6)}]
    plan = dict(gpu_uuid="fixture", allocation="fixture", isolation="fixture", block_seed=1,
                configs=[cfg("arm-a"), cfg("arm-b")], blocks={"arm-a": dict(steps=steps), "arm-b": dict(steps=steps)},
                tekken={"arm-a": TEKKEN, "arm-b": TEKKEN},
                task_specs=[dict(kind="business", rows=64, seed=7), dict(kind="numerical", rows=64, seed=7)],
                limits=dict(max_turns=3, max_tool_calls=10, max_total_output_tokens=2048, max_tokens=256, deadline_s=60,
                            verify_timeout_s=120),
                sampling=dict(mode="sampled", temperature=0.15, top_p=1.0, top_k=-1, min_p=0.0, seed=0),
                load_est_s=1, export_reserve_s=0)
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(plan))
    out = tmp_path / "out"
    pilot.main(["--plan", str(p), "--out", str(out), "--budget-s", "3600", "--cutoff-utc", "2099-01-01T00:00:00Z",
                "--fixture-server"])
    ev = [json.loads(l) for l in (out / "driver-events.jsonl").read_text().splitlines()]
    assert [e["order"] for e in ev if e["kind"] == "block_order"][0] in (["arm-a", "arm-b"], ["arm-b", "arm-a"])
    done = [e["step"] for e in ev if e["kind"] == "step_done"]
    assert sorted(done) == sorted(["arm-a-n2", "arm-a-replay-n2", "arm-b-n2", "arm-b-replay-n2"])
    assert sum(e["kind"] == "step_skipped" for e in ev) == 2
    res = json.loads((out / "pilot-results.json").read_text())
    assert all(r.get("mismatched_turns", 0) == 0 for r in res if r["kind"] == "replay")
    assert records.verify_manifest(out) == []
