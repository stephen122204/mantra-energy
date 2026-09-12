"""Counter replay must detect plausible-but-wrong, rehashed runtime artifacts."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from studies.energy_diagnosis.moe.audit_windows import audit, replay


@pytest.fixture(scope="module")
def packet(tmp_path_factory):
    root = tmp_path_factory.mktemp("window-audit") / "packet"
    result = subprocess.run(
        [sys.executable, "-m", "studies.energy_diagnosis.moe.run", "--mode", "fixture",
         "--output", str(root), "--policies", "demand,fixed", "--max-runs", "2"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["window_audit"]["audit_passed"]
    return root


def test_complete_export_replays_each_portion(packet):
    report = audit(packet)
    assert report["audit_passed"] and report["attempts"] == 2
    for result in report["results"]:
        assert result["all_domains_measured"] and result["simulated"]
        for domain in result["domains"].values():
            assert domain["initialized_duration_bracket_ns"][0] >= 0
            pieces = domain["portions"]
            assert pieces["outer"]["replayed_joules"] == pytest.approx(sum(pieces[k]["replayed_joules"] for k in ("before", "initialized", "after")))


@pytest.mark.parametrize("defect,match", [
    ("energy", "energy total"), ("clock", "clock domain"),
    ("span", "task span"), ("drain", "drain outside"),
    ("registration", "registered artifact"), ("duplicate", "duplicate raw"),
    ("order", "overlap or reordered"), ("ownership", "ownership/raw"),
    ("unit", "unit"), ("hash", "hash mismatch"),
    ("checkpoint", "raw endpoint"),
])
def test_rehashed_bad_artifact_cannot_pass(packet, tmp_path, defect, match):
    root = tmp_path / "packet"
    shutil.copytree(packet, root)
    path = root / "exports" / "attempts.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    attempt = rows[0]["attempt"]
    refs = {a["role"]: a for a in attempt["artifacts"]}
    data = {role: json.loads((root / ref["path"]).read_text()) for role, ref in refs.items()}
    raw, window = data["raw-measurement"], data["initialized-model-window"]
    if defect == "energy":
        window["measurements"][0]["energy_j"] += 0.01
    elif defect == "clock":
        window["clock_domain"] = "different host"
    elif defect == "span":
        data["execution-record"]["spans"][0]["start_ns"] = raw["goal_start_ns"]
    elif defect == "drain":
        # Windows may timestamp inner end and goal end on the same clock tick.
        # Make the deliberately invalid drain strictly later than the whole goal.
        next(e for e in data["expert-events"] if e["event"] == "preparation_drained")["monotonic_ns"] = raw["goal_end_ns"] + 1
    elif defect == "registration":
        attempt["artifacts"] = [r for r in attempt["artifacts"] if r["role"] != "initialized-model-window"]
    elif defect == "duplicate":
        raw["samples"].append(raw["samples"][0])
    elif defect == "order":
        raw["samples"] = list(reversed(raw["samples"]))
    elif defect == "ownership":
        attempt["outcome_metadata"]["owned_work_terminated"] = False
    elif defect == "unit":
        raw["measurement_schema"]["unit"] = "millijoules"
    elif defect == "checkpoint":
        raw["checkpoints"]["initialized_model_end"] = "nonexistent"
    elif defect == "hash":
        window["reason"] = "changed after registration"
    for role, ref in refs.items():
        artifact = root / ref["path"]
        artifact.write_text(json.dumps(data[role]))
        if defect != "hash":
            ref["sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    attempt["execution_record"] = data["execution-record"]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    report = audit(root)
    assert not report["audit_passed"]
    assert match in report["results"][0]["error"]
    assert report["results"][1]["audit_passed"]  # Retain the other attempt.


def test_replay_keeps_wraps_gaps_and_resets():
    def sample(value, status="ok"):
        return dict(value=value, status=status)
    domain = dict(domain_type="ENERGY_COUNTER", max_energy_range_uj=1000)
    assert replay([sample(v) for v in (900, 50, 150)], domain, 64) == (250 / 1e6, 1, "")
    assert replay([sample(900), sample(None, "missing"), sample(150)], domain, 64)[0] is None
    assert replay([sample(500), sample(100)], domain, 64)[0] is None
    with pytest.raises(ValueError, match="range"):
        replay([sample(1001), sample(20)], domain, 64)


def test_empty_export_is_not_a_successful_audit(tmp_path):
    (tmp_path / "exports").mkdir()
    (tmp_path / "exports" / "attempts.jsonl").write_text("")
    (tmp_path / "moe-manifest.json").write_text("{}")
    assert not audit(tmp_path)["audit_passed"]


def test_native_smoke_rejects_missing_checkpoint_evidence(monkeypatch, tmp_path):
    from studies.energy_diagnosis.moe import run
    monkeypatch.setattr(run, "run", lambda args: dict(
        validation={"valid": True}, summary={"settings": {}},
        window_audit={"audit_passed": False, "results": []},
    ))
    with pytest.raises(SystemExit) as error:
        run.main(["--mode", "native", "--policies", "demand", "--output", str(tmp_path)])
    assert error.value.code == 5
