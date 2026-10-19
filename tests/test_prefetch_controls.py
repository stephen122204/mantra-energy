"""Prefetch comparison arms and prepared-expert usefulness accounting."""
from collections import Counter
import json

import pytest

from studies.energy_diagnosis.moe.audit_usefulness import goal as usefulness
from studies.energy_diagnosis.moe.control import Expert, Lifecycle, Policy
from studies.energy_diagnosis.moe.expert_profile import build_future_trace, build_profile, dump, load
from studies.energy_diagnosis.moe import run as campaign

MB = 9 * 2**20


class Scripted:
    """In-process backend replaying declared transfer outcomes and demand residency."""

    def __init__(self, experts):
        self.experts = {e.key: e for e in experts}
        self.outcomes = {}       # key -> outcome for its next preparation
        self.demands = []        # demand rows returned by the next drain_demands
        self.queued = []
        self.seq = 0
        self.reset_evidence = dict(method="scripted")

    def capabilities(self):
        return dict(controls=["acknowledged_preparation", "completed_transfers", "cancel_queued", "drain", "expert_snapshot"])

    def reset_goal_state(self):
        pass

    def snapshot_experts(self):
        return list(self.experts.values())

    def prepare_experts(self, selected, generation, budget):
        for e in selected:
            self.seq += 1
            outcome = self.outcomes.pop(e.key, "completed")
            self.queued.append(dict(layer=e.layer, expert=e.expert, node=e.node, generation=generation,
                                    bytes=e.nbytes, transferred_bytes=e.nbytes if outcome == "completed" else 0,
                                    enqueue_ns=self.seq, start_ns=self.seq, end_ns=self.seq, outcome=outcome))
        return dict(accepted_nodes=[e.node for e in selected], accepted_bytes=sum(e.nbytes for e in selected),
                    inflight_bytes=0)

    def cancel_pending_preparation(self, generation):
        return 0

    def drain_owned_work(self, timeout):
        pass

    def drain_transfers(self):
        rows, self.queued = self.queued, []
        return rows, 0

    def drain_demands(self):
        rows, self.demands = self.demands, []
        return rows

    def end_goal(self):
        pass


def expert(i, device="cpu"):
    return Expert(0, i, 100 + i, 200 + i, MB, device)


def demand(i, resident, phase="decode"):
    return dict(layer=0, expert=i, tokens=3, dispatches=1, resident_dispatches=int(resident),
                first_dispatch_resident=resident, phase=phase)


def pause(control):
    control.plan_pause()
    token = control.start_pause()
    control.end_pause(token)


def model(control, backend, step, rows=()):
    control.before_model(f"r{step}")
    backend.demands = list(rows)
    control.after_model()
    control.request_id = ""


def test_known_sequences_are_classified_once_each():
    experts = [expert(i) for i in range(5)]
    backend = Scripted(experts)
    control = Lifecycle(backend, Policy("fixed", 5 * MB))
    control.begin_goal("g")
    # Call 0 uses all five, so all are ranked for the first pause.
    model(control, backend, 0, [demand(i, False, "prefill") for i in range(5)])
    backend.outcomes[(0, 4)] = "cancelled"
    pause(control)
    # Expert 0 used while resident; expert 1 evicted before its first use.
    model(control, backend, 1, [demand(0, True), demand(1, False)])
    # Expert 2 prepared again before any use; 3 never used.
    control.policy = Policy("fixed", MB)
    control.history = Counter({(0, 2): 99})
    pause(control)
    control.policy = Policy("fixed", 5 * MB)
    control.end_goal()
    result = usefulness(control.events)
    assert result["counts"] == dict(used_resident=1, evicted_before_use=1, replaced_unused=1, unused_at_goal_end=2)
    assert result["bytes"]["used_resident"] == MB
    assert result["used_resident_first_phase"] == {"decode": 1}
    assert result["not_completed"] == {"cancelled": 1}
    assert result["prepared_completed"] == 5
    assert result["demand"]["decode_nonresident_dispatches"] == 1


def test_unclassified_or_double_classified_transfers_are_rejected():
    backend = Scripted([expert(0)])
    control = Lifecycle(backend, Policy("fixed", MB))
    control.begin_goal("g")
    model(control, backend, 0, [demand(0, False)])
    pause(control)
    control.end_goal()
    events = [e for e in control.events if e["event"] != "prepared_not_used_by_goal_end"]
    with pytest.raises(ValueError, match="no terminal"):
        usefulness(events)
    doubled = control.events + [e for e in control.events if e["event"] == "prepared_not_used_by_goal_end"]
    with pytest.raises(ValueError, match="twice"):
        usefulness(doubled)


def test_random_matches_fixed_pool_and_budget_but_not_order():
    snapshot = [expert(i) for i in range(20)] + [expert(20, "cuda:0")]
    history = Counter({(0, i): 100 - i for i in range(21)})
    fixed, _ = Policy("fixed", 4 * MB).select(snapshot, history)
    picks = {tuple(e.key for e in Policy("random", 4 * MB, seed=s).select(snapshot, history, pause_index=1)[0]) for s in range(6)}
    assert [e.key for e in fixed] == [(0, i) for i in range(4)]
    assert all(len(p) == 4 and (0, 20) not in p for p in picks)  # resident experts never chosen
    assert len(picks) > 1
    again, reason = Policy("random", 4 * MB, seed=3).select(snapshot, history, pause_index=1)
    assert reason == "random_matched_budget"
    assert again == Policy("random", 4 * MB, seed=3).select(snapshot, history, pause_index=1)[0]


def test_static_prepares_profile_once_before_first_call_and_never_at_pauses():
    experts = [expert(i) for i in range(6)]
    backend = Scripted(experts)
    profile = dict(experts=[[0, 5, 50], [0, 3, 40], [0, 1, 30]])
    control = Lifecycle(backend, Policy("static", 2 * MB, data_sha256="x"), data=profile)
    control.begin_goal("g")
    control.prepare_ahead()
    admitted = next(e for e in control.events if e["event"] == "ahead_preparation_admitted")
    assert [s["expert"] for s in admitted["selected"]] == [5, 3]
    with pytest.raises(RuntimeError, match="ahead preparation"):
        control.prepare_ahead()
    model(control, backend, 0, [demand(5, True, "prefill")])
    pause(control)
    assert not any(e["event"] == "preparation_admitted" for e in control.events)
    control.end_goal()
    result = usefulness(control.events)
    assert result["counts"]["used_resident"] == 1 and result["counts"]["unused_at_goal_end"] == 1
    assert result["bytes_by_preparation_source"] == {"ahead": {"used_resident": MB, "unused_at_goal_end": MB}}
    with pytest.raises(RuntimeError, match="ahead preparation"):
        control.prepare_ahead()


def test_future_diagnostic_uses_next_call_trace_only():
    snapshot = [expert(i) for i in range(4)]
    trace = dict(tasks={"t": {"1": [[0, 2, 9], [0, 3, 1]]}})
    policy = Policy("future", 1 * MB, data_sha256="x")
    chosen, reason = policy.select(snapshot, Counter(), pause_index=1, task_id="t", data=trace)
    assert [e.key for e in chosen] == [(0, 2)] and reason == "future_trace_diagnostic"
    with pytest.raises(ValueError, match="future trace missing"):
        policy.select(snapshot, Counter(), pause_index=2, task_id="t", data=trace)
    with pytest.raises(ValueError):
        Policy("future", MB)  # no data
    with pytest.raises(ValueError):
        Policy("fixed", MB, data_sha256="x")


def test_builtin_and_demand_prepare_nothing_at_pauses():
    for name in ("demand", "builtin"):
        class NoPreparation(Scripted):
            def snapshot_experts(self):
                pytest.fail(f"{name} must not enumerate experts at a pause")
        backend = NoPreparation([expert(0)])
        control = Lifecycle(backend, Policy(name))
        control.begin_goal("g")
        control.prepare_ahead()
        model(control, backend, 0, [demand(0, False)])
        pause(control)
        control.end_goal()
        assert usefulness(control.events)["prepared_completed"] == 0


def test_all_arms_run_through_campaign_and_profiles_build(tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps([dict(kind="numerical", rows=256, seed=7)]))
    dev = tmp_path / "dev"
    campaign.main(["--mode", "fixture", "--output", str(dev), "--task-pack", str(spec), "--policies", "demand",
                   "--max-runs", "1", "--deadline", "60"])
    profile_sha = dump(build_profile(dev), tmp_path / "profile.json")
    trace_sha = dump(build_future_trace(dev), tmp_path / "trace.json")
    assert load(tmp_path / "profile.json")[1] == profile_sha and load(tmp_path / "trace.json")[1] == trace_sha
    out = tmp_path / "arms"
    campaign.main(["--mode", "fixture", "--output", str(out), "--task-pack", str(spec),
                   "--policies", "demand,fixed,random,static,future,builtin", "--byte-budget", "128",
                   "--policy-data", f"static={tmp_path / 'profile.json'}", "--policy-data", f"future={tmp_path / 'trace.json'}",
                   "--max-runs", "6", "--deadline", "60"])
    from studies.energy_diagnosis.moe.audit_usefulness import audit_campaign
    report = audit_campaign(out)
    assert {g["policy"] for g in report["goals"]} == {"demand", "fixed", "random", "static", "future", "builtin"}
    manifest = json.loads((out / "moe-manifest.json").read_text())
    shas = {p["name"]: p["data_sha256"] for p in manifest["policies"].values()}
    assert shas["static"] == profile_sha and shas["future"] == trace_sha and shas["fixed"] is None


def test_future_trace_maps_real_pauses_after_recovery_turns(tmp_path):
    root = tmp_path / "goals" / "g"
    root.mkdir(parents=True)
    # Model call 1 retries a malformed call 0 without executing a tool. Pause 1
    # precedes model call 2, which needs expert 2, not expert 1.
    events = [dict(event="goal_start", policy=dict(name="demand"))]
    for i in range(3):
        if i == 2:
            events.append(dict(event="tool_pause_start"))
        events += [dict(event="model_start"), dict(event="expert_demand", observation=demand(i, False)), dict(event="model_end")]
    events.append(dict(event="goal_end"))
    (root / "expert-events.json").write_text(json.dumps(events))
    (root / "record.json").write_text(json.dumps(dict(task_id="t", goal_execution_id="g", execution_status="completed", verifier=dict(outcome="pass"))))
    trace = build_future_trace(tmp_path)
    assert trace["kind"] == "future-trace-v2"
    assert trace["tasks"] == {"t": {"1": [[0, 2, 3]]}}


def test_native_builtin_rejected_and_other_arms_force_it_off():
    with pytest.raises(ValueError, match="not qualified"):
        campaign.policy_backend_config({}, Policy("builtin"))
    for name in ("demand", "fixed", "random"):
        assert campaign.policy_backend_config(dict(builtin_prefetch=True), Policy(name))["builtin_prefetch"] is False
    assert campaign.policy_backend_config({}, Policy("builtin"), simulated=True)["builtin_prefetch"] is True


@pytest.mark.parametrize("mutation, message", [
    ("duplicate", "duplicate completed"), ("bytes", "byte count"),
    ("residency", "first-dispatch residency"), ("dispatches", "dispatch/residency"),
    ("incomplete", "complete goal"),
])
def test_usefulness_rejects_corrupt_or_incomplete_evidence(mutation, message):
    from copy import deepcopy
    backend = Scripted([expert(0)])
    control = Lifecycle(backend, Policy("fixed", MB))
    control.begin_goal("g")
    model(control, backend, 0, [demand(0, False)])
    pause(control)
    model(control, backend, 1, [demand(0, True)])
    control.end_goal()
    events = deepcopy(control.events)
    transfer = next(e for e in events if e["event"] == "expert_transfer")
    if mutation == "duplicate":
        events.append(deepcopy(transfer))
    elif mutation == "bytes":
        transfer["transfer"]["transferred_bytes"] -= 1
    elif mutation == "residency":
        next(e for e in events if e["event"] == "prepared_expert_requested")["resident_on_first_dispatch"] = None
    elif mutation == "dispatches":
        next(e for e in events if e["event"] == "expert_demand")["observation"]["resident_dispatches"] = 100
    elif mutation == "incomplete":
        events = [e for e in events if e["event"] != "goal_end"]
    with pytest.raises(ValueError, match=message):
        usefulness(events)


def test_profile_serialization_hashes_exact_canonical_bytes(tmp_path):
    """Runs on Linux/Windows: binary output prevents platform newline translation."""
    import hashlib
    first = {"source": "café", "experts": [[0, 1, 2]], "kind": "static-profile-v1"}
    reordered = {"kind": first["kind"], "experts": first["experts"], "source": first["source"]}
    paths = [tmp_path / "first.json", tmp_path / "reordered.json"]
    digests = [dump(value, path) for value, path in zip((first, reordered), paths)]
    expected = (json.dumps(first, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    assert paths[0].read_bytes() == paths[1].read_bytes() == expected
    assert b"\r" not in expected and expected.endswith(b"\n")
    assert digests == [hashlib.sha256(expected).hexdigest()] * 2
    assert load(paths[0]) == (first, digests[0])


def test_after_timing_admits_same_batch_only_when_tool_returns():
    experts = [expert(i) for i in range(3)]
    events_by_timing = {}
    for timing in ("during", "after"):
        backend = Scripted(experts)
        control = Lifecycle(backend, Policy("fixed", 2 * MB, timing=timing))
        control.begin_goal("g")
        model(control, backend, 0, [demand(i, False) for i in range(3)])
        control.plan_pause()
        token = control.start_pause()
        admitted_at_start = [e["event"] for e in control.events if e["event"].endswith("admitted")]
        control.end_pause(token)
        control.end_goal()
        events_by_timing[timing] = control.events
        names = [e["event"] for e in control.events]
        if timing == "during":
            assert admitted_at_start == ["preparation_admitted"]
        else:
            assert admitted_at_start == [] and "preparation_deferred" in names
            # Admitted after tools_finished and completed before the model resumes.
            assert names.index("tools_finished") < names.index("deferred_preparation_admitted") < names.index("model_resume")
    selected = {t: [s["expert"] for e in ev if e["event"].endswith("preparation_admitted") for s in e["selected"]]
                for t, ev in events_by_timing.items()}
    assert selected["during"] == selected["after"] == [0, 1]
    assert usefulness(events_by_timing["after"])["prepared_completed"] == 2
    with pytest.raises(ValueError):
        Policy("demand", timing="after")
