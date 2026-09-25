"""Frozen campaign analysis on synthetic batches: retention, EpSG, zero successes, pairing."""
import json
import math

from studies.energy_diagnosis.diagnostics import campaign_analysis as ca


def batch(root, ident, energy, success=True, valid=True, requests=("r1", "r2"), seconds=300.0):
    goal = root / ident / "campaign/goals/exec-x"
    goal.mkdir(parents=True)
    (root / ident / "acceptance.json").write_text(json.dumps(dict(protocol_valid=valid)))
    per = energy / 3
    (goal / "record.json").write_text(json.dumps(dict(
        verifier=dict(outcome="pass" if success else "fail"), execution_status="completed",
        started_ns=0, ended_ns=int(seconds * 1e9),
        measurements=[dict(domain_id=d, status="valid", energy_j=per) for d in ca.DOMAINS])))
    (goal / "model-calls.json").write_text(json.dumps([dict(request=r) for r in requests]))


def spec(entries):
    return dict(schedule=[dict(id=i, block=b, family=f, task=t, arm=a) for i, b, f, t, a in entries])


def test_energy_per_successful_goal_charges_failures_and_handles_zero_successes(tmp_path):
    entries = []
    for block in range(3):
        for arm, e in (("A", 1000.0), ("B1", 1010.0)):
            ident = f"r{block}-L-x-{arm}"
            entries.append((ident, block, "L", "x", arm))
            batch(tmp_path, ident, e + block, success=not (arm == "A" and block == 2))
        ident = f"r{block}-L-z-A"
        entries.append((ident, block, "L", "z", "A"))
        batch(tmp_path, ident, 500.0, success=False)
    out = ca.analyze(spec(entries), tmp_path)
    cell = next(c for c in out["cells"] if (c["task"], c["arm"]) == ("x", "A"))
    assert cell["valid"] == 3 and cell["successes"] == 2
    assert math.isclose(cell["energy_per_successful_goal_j"], (1000 + 1001 + 1002) / 2)
    assert math.isclose(cell["energy_of_failed_attempts_j"], 1002)
    zero = next(c for c in out["cells"] if c["task"] == "z")
    assert zero["energy_per_successful_goal_j"] is None and "zero successes" in zero["energy_per_successful_goal_note"]
    assert zero["success_rate_wilson95"][0] == 0.0
    x = next(s for s in out["contrasts"]["B1-A:total_j"]["per_task_fixed_work"] if s["task"] == "x")
    assert x["n"] == 3 and math.isclose(x["mean"], 100 * sum(10 / (1000 + b) for b in range(3)) / 3)


def test_invalid_and_divergent_attempts_are_retained_but_not_in_primary_contrast(tmp_path):
    entries = [("r0-S-e-A", 0, "S", "e", "A"), ("r0-S-e-B1", 0, "S", "e", "B1"),
               ("r1-S-e-A", 1, "S", "e", "A"), ("r1-S-e-B1", 1, "S", "e", "B1"),
               ("r2-S-e-A", 2, "S", "e", "A"), ("r2-S-e-B1", 2, "S", "e", "B1")]
    batch(tmp_path, "r0-S-e-A", 100.0); batch(tmp_path, "r0-S-e-B1", 101.0)
    batch(tmp_path, "r1-S-e-A", 100.0); batch(tmp_path, "r1-S-e-B1", 102.0, requests=("r1", "other"))
    batch(tmp_path, "r2-S-e-A", 100.0); batch(tmp_path, "r2-S-e-B1", 150.0, valid=False)
    out = ca.analyze(spec(entries), tmp_path)
    assert out["invalid_attempts"] == ["r2-S-e-B1"]
    s = out["contrasts"]["B1-A:total_j"]["per_task_fixed_work"][0]
    assert s["n"] == 1 and s["pairs_all"] == 2 and s["live_divergent"] == 1
    cell = next(c for c in out["cells"] if c["arm"] == "B1")
    assert cell["attempts"] == 3 and cell["valid"] == 2 and cell["invalid"] == ["r2-S-e-B1"]


def test_t_interval_and_precision_gate():
    s = ca.summary([1.0, 2.0, 3.0, 4.0, 5.0])
    assert math.isclose(s["half_width"], 2.776 * math.sqrt(2.5) / math.sqrt(5), rel_tol=1e-9)
    fam = ca.family([dict(n=5, mean=0.1, sd=0.5), dict(n=5, mean=-0.1, sd=0.5)])
    assert math.isclose(fam["mean"], 0.0, abs_tol=1e-12) and fam["df"] > 4
    gate = ca.precision_gate(dict(contrasts={"B1-A:total_j": dict(
        per_task_fixed_work=[dict(task="x", half_width=1.2)], family_fixed_work={"L": dict(half_width=0.3)})}))
    assert gate["extend"] and "x" in gate["reasons"][0]
    ok = ca.precision_gate(dict(contrasts={"B1-A:total_j": dict(
        per_task_fixed_work=[dict(task="x", half_width=0.8)], family_fixed_work={"L": dict(half_width=0.3)})}))
    assert not ok["extend"]
