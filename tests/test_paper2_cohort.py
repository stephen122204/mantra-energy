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
    # vLLM 0.10.2 reports some failures as an error event inside an HTTP 200 stream: never an empty turn
    with FakeVllm(r, mode="stream_error") as srv:
        s3 = run_cohort(_spec(prepared, ids, srv, cohort_id="c-stream-err", admission_limit=2), tmp_path)
        assert srv.requests == 2  # one request per session, not a turn budget of empty completions
    assert s3["outcomes"] == {"infra_failed": 2}
    req = json.loads((tmp_path / "c-stream-err" / "sessions").glob("*/requests.jsonl").__next__().read_text().splitlines()[0])
    assert "server error in stream" in req["error"]


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
    # several sessions running at the deadline: those that exit from SIGTERM before they are polled are
    # still cancellations, never infrastructure failures that invalidate the cohort
    with FakeVllm(r, delay_s=30) as srv:
        s = run_cohort(_spec(prepared, ids, srv, cohort_id="c-cut-many", admission_limit=3, cohort_deadline_s=2.0),
                       tmp_path)
    assert s["outcomes"] == {"cancelled": 3} and not s["infra_invalid"]


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
    from studies.paper2.cohort import budget
    m = budget.measured(out)
    assert set(m["steps"]) == set(done) and {x["step"] for x in m["skipped"]} == {"arm-a-too-long", "arm-b-too-long"}
    b = budget.budget(m, dict(cells=[dict(config="arm-a", step="n2", repeats=4), dict(config="arm-a", step="n9", repeats=1)]),
                      available_h=10)
    assert b["unmeasured"] == ["arm-a-n9"] and b["fits"] is False and b["cells"][0]["repeats"] == 4
    from studies.paper2.cohort import report
    report.main([str(out), "--json", str(tmp_path / "rep.json"), "--md", str(tmp_path / "rep.md")])
    rep = json.loads((tmp_path / "rep.json").read_text())
    live = [r for r in rep["cohorts"] if r.get("kind") != "replay"]
    assert sorted(r["cohort"] for r in live) == ["arm-a-n2", "arm-b-n2"]
    assert len([r for r in rep["cohorts"] if r.get("kind") == "replay"]) == 2
    assert set(rep["paired"]["n2"]) == {"business-segments-v2-n64-s7", "grouped-fit-v1-n64-s7"}


FAKE_DOCKER = r'''#!/bin/sh
# fixture docker: logs argv; "exec ... git diff" prints a patch; "exec ... bash -c CMD" echoes CMD
echo "$@" >> "$FAKE_DOCKER_LOG"
case "$*" in
  "image inspect --format"*) echo sha256:fixture ;;
  "image inspect"*) exit 1 ;;
  *"git diff --cached"*) printf 'diff --git a/x.py b/x.py\n+fixed\n' ;;
  *"exec"*) echo "ran: $*" ;;
  run*) echo cid123 ;;
esac
'''


def test_swebench_runtime_container_lifecycle_and_schema(tmp_path, monkeypatch):
    pytest.importorskip("cloudpickle")
    from studies.paper2.cohort import swebench_workload as sw
    docker = tmp_path / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    log = tmp_path / "docker.log"
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    row = dict(instance_id="astropy__astropy-12907", repo="astropy/astropy", base_commit="d16bfe05a744909de4b27f5875fe0d4ed41ce607",
               problem_statement="Separability matrix wrong for nested models", difficulty="15 min - 1 hour")
    cat = sw.prepare_instances([row], tmp_path / "prep", docker=str(docker))
    calls = log.read_text()
    assert "--network none" in calls and "git update-ref -d" in calls and "commit" in calls
    assert sw.official_image(row["instance_id"]) == "swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest"
    import cloudpickle
    from types import SimpleNamespace
    task = cloudpickle.loads(Path(cat[0]["task_pickle"]).read_bytes())
    assert "Separability" in task.prompt and "/testbed" in task.prompt
    assert not any(k in json.loads((task.asset_path / "instance.json").read_text()) for k in ("patch", "test_patch", "FAIL_TO_PASS"))
    rt = sw.SweBenchRuntime(tmp_path / "sess", docker=str(docker))
    rt.begin(task, SimpleNamespace(execution_id="s1"))
    assert set(rt.context(task)["tools"]) == {"bash"}
    with pytest.raises(ValueError):
        rt.tool(task, dict(tool="bash", args=dict(command="ls", extra=1)))
    out = rt.tool(task, dict(tool="bash", args=dict(command="ls -la"))).execute()
    assert out["exit_code"] == 0 and "ls -la" in out["output"]
    patch = rt.finalize(task)
    assert patch.read_text().startswith("diff --git") and "rm -f p2-s1" in log.read_text()
    assert rt.container is None


def test_swebench_evaluate_parses_harness_report_and_rejects_empty(tmp_path):
    from studies.paper2.cohort import swebench_workload as sw
    assert sw.evaluate_patch("a__b-1", "  ", tmp_path / "e0")["passed"] is False

    def fake_run(argv, timeout, cwd=None):
        rid = argv[argv.index("--run_id") + 1]
        d = Path(cwd) / "logs" / "run_evaluation" / rid / "paper2" / "a__b-1"
        d.mkdir(parents=True)
        (d / "report.json").write_text(json.dumps({"a__b-1": {"resolved": True, "tests_status": {}}}))
        return 0, "", ""
    res = sw.evaluate_patch("a__b-1", "diff --git a/x b/x\n", tmp_path / "e1", run=fake_run)
    assert res["passed"] is True
    res = sw.evaluate_patch("a__b-1", "diff --git a/x b/x\n", tmp_path / "e2", run=lambda a, t, cwd=None: (1, "", "boom"))
    assert res["passed"] is False and res["infrastructure"] is True


def _campaign_inputs(tmp_path):
    cfg = lambda n: dict(name=n, model=f"/nonexistent/{n}", revision="fixture", weight_precision="int4",
                         activation_precision="bf16", max_model_len=32768)
    calib = ["business-segments-v2-n64-s7", "grouped-fit-v1-n64-s7"]
    pilot_steps = [{"live": dict(name="n2", admission_limit=2, task_ids=calib, seed=3, est_s=60)},
                   {"replay": dict(name="replay-n2", source="n2", admission_limit=2, est_s=60)}]
    base = dict(gpu_uuid="GPU-pilot", allocation="pilot", isolation="fixture", block_seed=1,
                configs=[cfg("arm-a"), cfg("arm-b")], blocks={"arm-a": dict(steps=pilot_steps), "arm-b": dict(steps=pilot_steps)},
                tekken={"arm-a": TEKKEN or "tekken.json", "arm-b": TEKKEN or "tekken.json"},
                task_specs=[dict(kind="business", rows=64, seed=7), dict(kind="numerical", rows=64, seed=7)],
                limits=dict(max_turns=3, max_tool_calls=10, max_total_output_tokens=2048, max_tokens=256, deadline_s=60,
                            verify_timeout_s=120),
                sampling=dict(mode="sampled", temperature=0.15, top_p=1.0, top_k=-1, min_p=0.0, seed=0),
                load_est_s=1, export_reserve_s=0)
    pilot_out = tmp_path / "pilot"
    pilot_out.mkdir()
    ev = [dict(kind="server_started", config=dict(name="arm-a"), started=dict(load_s=30, kv_cache_tokens=16000)),
          dict(kind="server_started", config=dict(name="arm-b"), started=dict(load_s=40, gpu_blocks=900)),
          dict(kind="step_done", step="arm-a-n2", seconds=100), dict(kind="step_done", step="arm-b-n2", seconds=120),
          dict(kind="step_done", step="arm-a-replay-n2", seconds=50)]
    (pilot_out / "driver-events.jsonl").write_text("\n".join(json.dumps(e) for e in ev) + "\n")
    evals = ["business-segments-v2-n64-s9", "grouped-fit-v1-n64-s9"]
    matrix = dict(campaign_id="fixture-campaign", seed=5, contingency=0.0, export_h=0.0,
                  allow_borrowed_estimates=True, allow_unbalanced_order=True,
                  task_specs=[dict(kind="business", rows=64, seed=9), dict(kind="numerical", rows=64, seed=9)],
                  cells=[dict(name="n2", kind="live", admission_limit=2, task_ids=evals, repeats=3, measure_as="n2", seed=7),
                         dict(name="xr", kind="replay", source_cell="n2", repeats=1, admission_limit=2, measure_as="replay-n2")])
    nodes = [dict(name="node-x", gpu_class="A100-SXM4-80GB", available_h=10),
             dict(name="node-y", gpu_class="A100-SXM4-80GB", available_h=10)]
    return base, matrix, nodes, pilot_out


def _node_report(uuid="GPU-x", cpu=True, sandbox=True, busy=0):
    return dict(host="fixture-host", cpu=dict(sockets=2, model="fixture CPU"), memory_gib=503,
                gpus=dict(driver="fixture", devices=[dict(name="NVIDIA A100-SXM4-80GB", uuid=uuid, compute_procs=busy, energy_counter=dict(advancing=True))]),
                verdict=dict(gpu_energy_counter=True, cpu_package_counters=cpu, task_sandbox_landlock_abi4=sandbox))


def test_campaign_shard_keeps_every_precision_on_each_node(tmp_path):
    from studies.paper2.cohort import campaign
    base, matrix, nodes, pilot_out = _campaign_inputs(tmp_path)
    m = campaign._measurements([pilot_out])
    assert m["kv_blocks"] == {"arm-a": 1000, "arm-b": 900}
    meas = {"A100-SXM4-80GB": m}
    res = campaign.shard(base, matrix, meas, nodes, commit="c0")
    units = [u for nd in res["nodes"].values() for r in nd["rounds"] for u in r["plan"]["campaign"]["units"]]
    assert sorted(units) == ["n2-r0", "n2-r1", "n2-r2"]
    assert all(len(nd["rounds"]) >= 1 for nd in res["nodes"].values())
    for nd in res["nodes"].values():
        for r in nd["rounds"]:
            p = r["plan"]
            live = p["passes"][0]["blocks"]
            assert set(live) == {"arm-a", "arm-b"}
            a_steps, b_steps = (next(iter(s.values())) for s in (live["arm-a"]["steps"][0], live["arm-b"]["steps"][0]))
            assert (a_steps["name"], a_steps["seed"], a_steps["task_ids"]) == (b_steps["name"], b_steps["seed"], b_steps["task_ids"])
            if "n2-r0" in p["campaign"]["units"]:  # crossed replay incl. diagonal, on every configuration
                rep = {t: sorted(next(iter(s.values()))["source"] for s in b["steps"]) for t, b in p["passes"][1]["blocks"].items()}
                assert rep == {"arm-a": ["arm-a/n2-r0", "arm-b/n2-r0"], "arm-b": ["arm-a/n2-r0", "arm-b/n2-r0"]}
            else:
                assert len(p["passes"]) == 1
    assert res["estimate_provenance"]["A100-SXM4-80GB"]["arm-b-xr"] == "slowest measured on another config"
    # a second GPU class needs its own pilot, then gets its own full set of repeats (never pooled)
    h100 = [dict(name="node-h", gpu_class="H100", available_h=10)]
    with pytest.raises(SystemExit, match="each class needs its own pilot"):
        campaign.shard(base, matrix, meas, nodes + h100, commit="c0")
    both = campaign.shard(base, matrix, dict(meas, H100=m), nodes + h100, commit="c0")
    assert sorted(u for r in both["nodes"]["node-h"]["rounds"] for u in r["plan"]["campaign"]["units"]) == \
        ["n2-r0", "n2-r1", "n2-r2"]
    # block order rotates: over a node's rounds each configuration is first equally often
    one = campaign.shard(base, matrix, meas, nodes[:1], commit="c0")["nodes"]["node-x"]["rounds"]
    firsts = [r["plan"]["passes"][0]["order"][0] for r in one]
    assert len(one) == 3 and firsts.count("arm-a") in (1, 2) and set(firsts) == {"arm-a", "arm-b"}
    eq = campaign.shard(base, dict(matrix, equal_kv=True), meas, nodes, commit="c0")
    assert {c["name"]: c.get("num_gpu_blocks_override") for c in eq["nodes"]["node-x"]["rounds"][0]["plan"]["configs"]} == \
        {"arm-a": None, "arm-b": None, "arm-a-eqkv": 900, "arm-b-eqkv": 900}
    with pytest.raises(SystemExit, match="pilot task ids"):
        campaign.shard(base, dict(matrix, cells=[dict(matrix["cells"][0], task_ids=["business-segments-v2-n64-s7"])]),
                       meas, nodes, commit="c0")
    with pytest.raises(SystemExit, match="no measured duration"):
        campaign.shard(base, dict(matrix, cells=[dict(matrix["cells"][0], measure_as="n16")]), meas, nodes, commit="c0")
    # audit I: a duration borrowed from another configuration is not that configuration's measurement
    with pytest.raises(SystemExit, match="not measured on this configuration"):
        campaign.shard(base, dict(matrix, allow_borrowed_estimates=False), meas, nodes, commit="c0")
    # audit I: rounds that cannot rotate block order through every configuration need an explicit opt-in
    with pytest.raises(SystemExit, match="cannot rotate fully"):
        campaign.shard(base, dict(matrix, allow_unbalanced_order=False), meas, nodes, commit="c0")
    # audit D: cells of one sweep must offer the same tasks, order and seeds (only admission varies)
    sweep = [dict(matrix["cells"][0], name="s1", admission_limit=1, sweep="main"),
             dict(matrix["cells"][0], name="s2", admission_limit=2, sweep="main",
                  task_ids=list(reversed(matrix["cells"][0]["task_ids"])))]
    with pytest.raises(SystemExit, match="differ in tasks"):
        campaign.shard(base, dict(matrix, cells=sweep), meas, nodes, commit="c0")
    ok_sweep = [sweep[0], dict(sweep[1], task_ids=sweep[0]["task_ids"])]
    assert campaign.shard(base, dict(matrix, cells=ok_sweep), meas, nodes, commit="c0")["nodes"]


def test_campaign_bind_checks_node_and_campaign_integrity(tmp_path):
    from studies.paper2.cohort import campaign
    base, matrix, nodes, pilot_out = _campaign_inputs(tmp_path)
    for name, obj in (("base.json", base), ("matrix.json", matrix), ("nodes.json", nodes)):
        (tmp_path / name).write_text(json.dumps(obj))
    camp = tmp_path / "campaign"
    assert campaign.main(["shard", "--base-plan", str(tmp_path / "base.json"), "--matrix", str(tmp_path / "matrix.json"),
                          "--pilot", f"A100-SXM4-80GB={pilot_out}", "--nodes", str(tmp_path / "nodes.json"), "--out", str(camp),
                          "--commit", "c0"]) == 0
    manifest = campaign._load_campaign(camp)
    bound, warnings = campaign.bind(manifest, camp, "node-x", _node_report(), "lease-x")
    assert not warnings and all(p["gpu_uuid"] == "GPU-x" and p["allocation"] == "lease-x" for _, p in bound)
    assert {p["binding"]["energy_metric"] for _, p in bound} == {"cpu_package+gpu_board"}
    assert bound[0][1]["binding"]["hardware"]["cpu_sockets"] == 2
    # audit A: the CPU-plus-GPU campaign refuses nodes without every CPU package, the task sandbox, or a free GPU
    for bad, why in ((_node_report(cpu=False), "CPU-package"), (_node_report(sandbox=False), "sandbox"),
                     (_node_report(busy=1), "compute processes")):
        with pytest.raises(SystemExit, match=why):
            campaign.bind(manifest, camp, "node-x", bad, "l")
    gpu_only = dict(manifest, energy_metric="gpu_board")  # explicit GPU-only campaign
    assert {p["binding"]["energy_metric"] for _, p in campaign.bind(gpu_only, camp, "node-x", _node_report(cpu=False), "l")[0]} \
        == {"gpu_board"}
    assert all(campaign.canonical_sha(campaign.unbound(p)) == p["binding"]["plan_sha256"] for _, p in bound)
    with pytest.raises(SystemExit, match="exactly one"):
        campaign.bind(manifest, camp, "node-x", dict(_node_report(), gpus=dict(devices=[dict(name="Tesla V100", uuid="u")])), "l")
    with pytest.raises(SystemExit, match="energy counter"):
        campaign.bind(manifest, camp, "node-x", dict(_node_report(), verdict=dict(gpu_energy_counter=False)), "l")
    f = camp / manifest["nodes"]["node-x"]["rounds"][0]["file"]
    tampered = json.loads(f.read_text())
    tampered["limits"]["max_turns"] += 1
    f.write_text(json.dumps(tampered, indent=1))
    with pytest.raises(SystemExit, match="altered"):
        campaign._load_campaign(camp)


@needs_renderer
def test_campaign_round_runs_and_collects(tmp_path):
    import subprocess
    from studies.paper2.cohort import campaign, pilot
    base, matrix, nodes, pilot_out = _campaign_inputs(tmp_path)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    res = campaign.shard(base, matrix, {"A100-SXM4-80GB": campaign._measurements([pilot_out])}, nodes, commit=head)
    camp = tmp_path / "campaign"
    camp.mkdir()
    rows = {}
    for node, nd in res["nodes"].items():
        (camp / node).mkdir()
        rows[node] = []
        for r in nd["rounds"]:
            f = f"{node}/round-{r['plan']['campaign']['round']:02d}.json"
            (camp / f).write_text(json.dumps(r["plan"]))
            rows[node].append(dict(file=f, plan_sha256=campaign.canonical_sha(r["plan"])))
    manifest = dict(campaign_id=res["campaign_id"], commit=head,
                    nodes={n: dict(gpu_class=nd["gpu_class"], rounds=rows[n]) for n, nd in res["nodes"].items()})
    node = next(n for n, nd in res["nodes"].items() if "n2-r0" in nd["rounds"][0]["plan"]["campaign"]["units"])
    bound, _ = campaign.bind(manifest, camp, node, _node_report(), "lease")
    plan_file = tmp_path / "bound-round.json"
    plan_file.write_text(json.dumps(bound[0][1]))
    out = tmp_path / "run"
    pilot.main(["--plan", str(plan_file), "--out", str(out), "--budget-s", "36000", "--cutoff-utc", "2099-01-01T00:00:00Z",
                "--fixture-server"])
    results = json.loads((out / "pilot-results.json").read_text())
    replays = [r for r in results if r["kind"] == "replay"]
    assert len(replays) == 4 and {r["pass_index"] for r in replays} == {1}
    assert all(r["mismatched_turns"] == 0 for r in replays)
    cov = campaign.collect(manifest, [out])
    counted = [r for r in cov["rounds"] if r["runs"]]
    run = counted[0]["runs"][0]
    assert len(counted) == 1 and run["complete"] and set(run["problems"]) <= {"dirty checkout"}
    assert run["expected"] == run["completed"] == 6 and not run["missing_cells"]
    # fixture runs have no energy counters: every cell is flagged, so the round is never "complete"
    assert any("no valid cpu_plus_gpu_j" in p for p in run["invalid_cells"])
    assert cov["summary"]["missing"] == len(cov["rounds"]) - 1 and not cov["analysable"]
    ev = [json.loads(l) for l in (out / "driver-events.jsonl").read_text().splitlines()]
    resets = [e for e in ev if e["kind"] == "cache_reset"]  # audit E: verified cold start before each cohort
    assert len(resets) == 6 and all(e["ok"] and e["cached_before_reset"] > 0 and e["cached_after_reset"] == 0 for e in resets)
    summ = json.loads(next((out / "cohorts").glob("*/*/cohort-summary.json")).read_text())
    assert summ["drain"]["drained"] is True  # audit F: interval closes after the server is idle
    assert counted[0]["runs"][0]["energy_metric"] == "cpu_package+gpu_board" and not cov["mixed_energy_metrics"]
    with pytest.raises(SystemExit, match="infra"):  # a rerun must name an infrastructure cause
        pilot.main(["--plan", str(plan_file), "--out", str(tmp_path / "rerun"), "--budget-s", "60",
                    "--cutoff-utc", "2099-01-01T00:00:00Z", "--fixture-server", "--retry-of", str(out)])
    victim = next(p for p in (out / "cohorts").rglob("requests.jsonl"))
    victim.write_text(victim.read_text() + "\n")
    run = next(x for r in campaign.collect(manifest, [out])["rounds"] for x in r["runs"])
    assert any(p.startswith("mismatch") for p in run["problems"])


@needs_renderer
def test_server_start_failure_and_death_are_configuration_outcomes(tmp_path, monkeypatch):
    from studies.paper2.cohort import engine_check, pilot, telemetry
    from studies.paper2.cohort.client import MistralRenderer
    from studies.paper2.cohort.fake_server import FakeVllm

    class StandIn:  # arm-a cannot start (e.g. does not fit); arm-b serves one step, then its process is gone
        def __init__(self, cfg, port, log_path, gpu_uuid):
            self.cfg, self.log_path = cfg, log_path
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("stand-in log\nCUDA out of memory\n")
            self.fake = None

        def start(self):
            if self.cfg.name == "arm-a":
                raise RuntimeError("vLLM exited with 1")
            self.fake = FakeVllm(MistralRenderer(TEKKEN), served_model=self.cfg.name, delay_s=0.05).__enter__()
            self.base_url = self.fake.base_url
            self.proc = SimpleNamespace(poll=lambda: -9, returncode=-9)
            return {"load_s": 1}

        def stop(self):
            if self.fake:
                self.fake.__exit__(None, None, None)
            return -9

    monkeypatch.setattr(pilot, "VllmServer", StandIn)
    monkeypatch.setattr(pilot, "gpu_index_for", lambda uuid: 0)
    monkeypatch.setattr(pilot, "gpu_busy", lambda i: 0)
    monkeypatch.setattr(pilot, "make_measurement", lambda *a: None)
    monkeypatch.setattr(telemetry, "MetricsPoller", lambda *a, **k: None)
    monkeypatch.setattr(engine_check, "run_checks", lambda *a, **k: {"ok": True, "forced_decoding": {"ok": True}})
    monkeypatch.setattr(pilot.subprocess, "check_output", lambda args, **k: "c0" if "rev-parse" in args else "")
    cfg = lambda n: dict(name=n, model=f"/nonexistent/{n}", revision="fixture", weight_precision="int4",
                         activation_precision="bf16", max_model_len=32768)
    steps = [{"idle": dict(name="idle1", seconds=0.1, est_s=1)},
             {"live": dict(name="n1", admission_limit=1, task_ids=["business-segments-v2-n64-s7"], est_s=60)}]
    plan = dict(gpu_uuid="GPU-x", allocation="fixture", isolation="fixture", block_seed=1,
                configs=[cfg("arm-a"), cfg("arm-b")], blocks={"arm-a": dict(steps=steps), "arm-b": dict(steps=steps)},
                tekken={"arm-a": TEKKEN, "arm-b": TEKKEN}, task_specs=[dict(kind="business", rows=64, seed=7)],
                limits=dict(max_turns=3, max_tool_calls=10, max_total_output_tokens=2048, max_tokens=256, deadline_s=60,
                            verify_timeout_s=120),
                sampling=dict(mode="sampled", temperature=0.15, top_p=1.0, top_k=-1, min_p=0.0, seed=0),
                load_est_s=1, export_reserve_s=0)
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    out = tmp_path / "out"
    pilot.main(["--plan", str(tmp_path / "plan.json"), "--out", str(out), "--budget-s", "3600",
                "--cutoff-utc", "2099-01-01T00:00:00Z"])
    ev = [json.loads(l) for l in (out / "driver-events.jsonl").read_text().splitlines()]
    failed = [e for e in ev if e["kind"] == "server_start_failed"]
    died = [e for e in ev if e["kind"] == "server_died"]
    assert [e["config"] for e in failed] == ["arm-a"] and failed[0]["outcome"] == "configuration"
    assert "CUDA out of memory" in failed[0]["log_tail"]
    assert [(e["config"], e["step"]) for e in died] == [("arm-b", "arm-b-idle1")]
    assert any(e["kind"] == "step_skipped" and e["step"] == "arm-b-n1" and "configuration outcome" in e["reason"] for e in ev)
    assert any(e["kind"] == "driver_end" for e in ev) and records.verify_manifest(out) == []


@needs_renderer
def test_atomic_pass_runs_on_all_precisions_or_none(tmp_path):
    from studies.paper2.cohort import make_plan, pilot
    built = make_plan.build(tmp_path, "GPU-x", "lease", None)
    assert [sorted(p["blocks"]) for p in built["passes"]][:2] == [sorted(make_plan.ARMS)] * 2 and all(p["atomic"] for p in built["passes"])
    ids = make_plan.task_ids()
    assert set(ids["isolated"]) <= set(ids["moderate"]) <= set(ids["all"]) and len(ids["moderate"]) == 12
    cfg = lambda n: dict(name=n, model=f"/nonexistent/{n}", revision="fixture", weight_precision="int4",
                         activation_precision="bf16", max_model_len=32768)
    small = [{"live": dict(name="n1", admission_limit=1, task_ids=["business-segments-v2-n64-s7"], est_s=60)}]
    huge = [{"live": dict(name="n9", admission_limit=1, task_ids=["business-segments-v2-n64-s7"], est_s=2000)}]
    plan = dict(gpu_uuid="fixture", allocation="fixture", isolation="fixture", block_seed=1, configs=[cfg("a"), cfg("b")],
                passes=[dict(atomic=True, blocks={"a": dict(steps=small), "b": dict(steps=small)}),
                        dict(atomic=True, blocks={"a": dict(steps=huge), "b": dict(steps=huge)})],  # 2 x 2000 s > budget
                tekken={"a": TEKKEN, "b": TEKKEN}, task_specs=[dict(kind="business", rows=64, seed=7)],
                limits=dict(max_turns=3, max_tool_calls=10, max_total_output_tokens=2048, max_tokens=256, deadline_s=60,
                            verify_timeout_s=120),
                sampling=dict(mode="sampled", temperature=0.15, top_p=1.0, top_k=-1, min_p=0.0, seed=0),
                load_est_s=1, export_reserve_s=0)
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    out = tmp_path / "out"
    pilot.main(["--plan", str(tmp_path / "plan.json"), "--out", str(out), "--budget-s", "3000",
                "--cutoff-utc", "2099-01-01T00:00:00Z", "--fixture-server"])
    ev = [json.loads(l) for l in (out / "driver-events.jsonl").read_text().splitlines()]
    assert sorted(e["step"] for e in ev if e["kind"] == "step_done") == ["a-n1", "b-n1"]
    assert [e["pass_index"] for e in ev if e["kind"] == "pass_skipped"] == [1]


def test_collect_never_calls_failed_or_missing_rounds_complete(tmp_path):
    """audit B: a finished, checksummed round whose configurations all failed to start is a configuration
    outcome; a round with cells that never ran is partial; neither is 'complete'."""
    from studies.paper2.cohort import campaign
    base, matrix, nodes, pilot_out = _campaign_inputs(tmp_path)
    res = campaign.shard(base, matrix, {"A100-SXM4-80GB": campaign._measurements([pilot_out])}, nodes[:1], commit="c0")
    plan = res["nodes"]["node-x"]["rounds"][0]["plan"]
    sha = campaign.canonical_sha(plan)
    manifest = dict(campaign_id="f", commit="c0", nodes={"node-x": dict(gpu_class="A100-SXM4-80GB",
                                                                         rounds=[dict(file="r.json", plan_sha256=sha)])})
    bound = dict(plan, gpu_uuid="GPU-x", allocation="l", binding=dict(plan_sha256=sha, energy_metric="cpu_package+gpu_board"))

    def run_dir(name, events):
        d = tmp_path / name
        d.mkdir()
        (d / "plan.json").write_text(json.dumps(bound))
        start = dict(kind="driver_start", revision="c0", dirty=False, energy_metric="cpu_package+gpu_board")
        (d / "driver-events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in [start] + events + [dict(kind="driver_end")]))
        records.write_manifest(d)
        return d
    failed = run_dir("all-failed", [dict(kind="server_start_failed", config=c, pass_index=i, error="OOM")
                                  for i, ps in enumerate(plan["passes"]) for c in ps["blocks"]])
    cov = campaign.collect(manifest, [failed])
    assert cov["rounds"][0]["status"] == "complete_with_configuration_outcomes"
    assert cov["rounds"][0]["runs"][0]["completed"] == 0
    nothing = run_dir("nothing-ran", [])
    assert campaign.collect(manifest, [nothing])["rounds"][0]["status"] == "partial"


def test_swebench_noop_harness_crash_does_not_qualify(tmp_path, monkeypatch):
    """audit C: a crashed no-op run is not a rejected solution; catalogues need a passing qualification."""
    from studies.paper2.cohort import pilot, swebench_workload as sw
    results = iter([dict(passed=True, reason="resolved"),
                    dict(passed=False, reason="harness produced no report (rc=1)", infrastructure=True)])
    monkeypatch.setattr(sw, "evaluate_patch", lambda *a, **k: next(results))
    q = sw.qualify_instance(dict(instance_id="x__y-1", patch="diff"), tmp_path)
    assert q["gold_resolves"] and not q["controls_valid"] and not q["qualified"]
    cat = tmp_path / "catalog.json"
    rows = [dict(task_id="x__y-1")]
    cat.write_text(json.dumps(rows))
    with pytest.raises(SystemExit, match="no qualification.json"):
        pilot.check_qualified(cat, rows)
    (tmp_path / "qualification.json").write_text(json.dumps([q]))
    with pytest.raises(SystemExit, match="not qualified"):
        pilot.check_qualified(cat, rows)


@needs_renderer
def test_frozen_task_assets_are_enforced(tmp_path):
    """audit G: a round whose prepared task assets differ from the frozen catalogue does not run."""
    from studies.paper2.cohort import pilot
    cfg = dict(name="a", model="/nonexistent/a", revision="fixture", weight_precision="int4", activation_precision="bf16",
               max_model_len=32768)
    plan = dict(gpu_uuid="fixture", allocation="fixture", isolation="fixture", block_seed=1, configs=[cfg],
                blocks={"a": dict(steps=[{"live": dict(name="n1", admission_limit=1, task_ids=["business-segments-v2-n64-s7"])}])},
                tekken={"a": TEKKEN}, task_specs=[dict(kind="business", rows=64, seed=7)],
                expected_tasks={"business-segments-v2-n64-s7": "0" * 64},
                limits=dict(max_turns=3, max_tool_calls=10, max_total_output_tokens=2048, max_tokens=256, deadline_s=60,
                            verify_timeout_s=120),
                sampling=dict(mode="sampled", temperature=0.15, top_p=1.0, top_k=-1, min_p=0.0, seed=0),
                load_est_s=1, export_reserve_s=0)
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    with pytest.raises(SystemExit, match="differ from the frozen catalogue"):
        pilot.main(["--plan", str(tmp_path / "plan.json"), "--out", str(tmp_path / "out"), "--budget-s", "600",
                    "--cutoff-utc", "2099-01-01T00:00:00Z", "--fixture-server"])


def test_sweep_plan_varies_only_admission_and_rotates_blocks(tmp_path):
    from collections import Counter
    from studies.paper2.cohort.make_plan import SWEEP_N, build_sweep, sweep_bound_s
    plan = build_sweep(tmp_path, "GPU-x", "lease", 7505, repeat_n=(4, 16), repeats=2)
    names = [c["name"] for c in plan["configs"]]
    lives = []
    for ps in plan["passes"]:
        assert ps["atomic"] and sorted(ps["order"]) == sorted(names)
        orders = {json.dumps(b["steps"]) for b in ps["blocks"].values()}
        assert len(orders) == 1, "every precision runs the same steps in the same order within a round"
        lives += [s["live"] for s in next(iter(ps["blocks"].values()))["steps"] if "live" in s]
    assert Counter(ps["order"][0] for ps in plan["passes"]) == Counter(names), "each precision first once"
    assert len({(l["name"]) for l in lives}) == len(lives), "cohort directories never collide across rounds"
    assert {l["admission_limit"] for l in lives if l["round"] == 0} == set(SWEEP_N)
    assert len({(tuple(l["task_ids"]), l["seed"], l["mode"], l["cohort_deadline_s"]) for l in lives}) == 1
    assert len(lives[0]["task_ids"]) == 23
    for l in lives:
        assert l["est_s"] >= sweep_bound_s(l["admission_limit"], 7505, plan["limits"]["deadline_s"])
        assert l["cohort_deadline_s"] >= l["est_s"] - plan["sweep"]["grading_s"]


def test_sweep_plan_pins_a_frozen_preparation(tmp_path):
    from studies.paper2.cohort.make_plan import build_sweep, task_ids
    prep = tmp_path / "prep"
    (prep / "assets").mkdir(parents=True)
    rows = [dict(task_id=t, asset_sha256=f"h-{t}") for t in task_ids()["all"]]
    (prep / "catalog.json").write_text(json.dumps(rows))
    plan = build_sweep(tmp_path, "GPU-x", "lease", 7505, frozen_prep=prep)
    assert plan["prepared_assets"] == str((prep / "assets").resolve())
    assert plan["expected_tasks"] == {r["task_id"]: r["asset_sha256"] for r in rows}
    (prep / "catalog.json").write_text(json.dumps(rows[1:]))
    with pytest.raises(SystemExit, match="lacks"):
        build_sweep(tmp_path, "GPU-x", "lease", 7505, frozen_prep=prep)
