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
    assert policy.select(snapshot, Counter(), pause_index=2, task_id="t", data=trace)[0] == []
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
