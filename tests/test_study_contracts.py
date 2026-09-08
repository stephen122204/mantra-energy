"""ED-01: shared record contracts round-trip, enforce their invariants, and bridge the existing components."""

import json
from pathlib import Path

import pytest

from studies.energy_diagnosis import contracts as c
from studies.energy_diagnosis.workloads.data_analysis import load_default_task, verify_answer

EXAMPLES = c.EXAMPLES_DIR


def test_examples_load_and_round_trip():
    for path in sorted(EXAMPLES.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):  # execution_settings.json
            records = [c.ExecutionSetting.from_dict(r) for r in raw]
            assert [r.to_dict() for r in records] == raw
            continue
        kind = raw.pop("_type")
        record = c.RECORD_TYPES[kind].from_dict(raw)
        again = c.RECORD_TYPES[kind].from_json(record.to_json())
        assert again == record
        assert again.to_dict() == record.to_dict()


def test_verified_example_semantics():
    rec = c.load_example("execution_record_verified")
    assert rec.verified is True
    assert rec.simulated is True
    assert rec.energy_by_domain == {"cpu-package-0": 412.5, "cpu-package-1": 97.25, "gpu-board-0": 1840.0}


def test_completion_is_not_correctness():
    rec = c.load_example("execution_record_wrong_answer")
    assert rec.execution_status == "completed"
    assert rec.verifier.outcome == "fail"
    assert rec.verified is False


def test_missing_energy_is_null_never_zero():
    rec = c.load_example("execution_record_timeout_missing_energy")
    assert rec.execution_status == "timed_out"
    assert rec.energy_by_domain == {"cpu-package-0": None, "gpu-board-0": None}
    base = rec.measurements[0].to_dict()
    with pytest.raises(c.ContractError, match="never 0"):
        c.MeasurementRecord.from_dict({**base, "energy_j": 0.0})
    with pytest.raises(c.ContractError, match="reason"):
        c.MeasurementRecord.from_dict({**base, "reason": ""})
    valid = rec.measurements[1].to_dict()
    with pytest.raises(c.ContractError, match="coverage"):
        c.MeasurementRecord.from_dict({**valid, "status": "valid", "reason": ""})


def test_failed_run_cannot_pass_verification():
    raw = json.loads((EXAMPLES / "execution_record_verified.json").read_text(encoding="utf-8"))
    raw.pop("_type")
    raw["execution_status"] = "crashed"
    raw["error"] = "runtime died"
    with pytest.raises(c.ContractError, match="cannot have a passing verifier"):
        c.ExecutionRecord.from_dict(raw)


def test_span_dependency_integrity():
    raw = json.loads((EXAMPLES / "execution_record_verified.json").read_text(encoding="utf-8"))
    raw.pop("_type")
    early = json.loads(json.dumps(raw))
    early["spans"][3]["ready_ns"] = 4000000000  # reconcile marked ready and started before product-tool ends
    early["spans"][3]["start_ns"] = 4000000000
    with pytest.raises(c.ContractError, match="started before its dependency"):
        c.ExecutionRecord.from_dict(early)
    unknown = json.loads(json.dumps(raw))
    unknown["spans"][1]["depends_on"] = ["s-nope"]
    with pytest.raises(c.ContractError, match="unknown span"):
        c.ExecutionRecord.from_dict(unknown)
    cyclic = json.loads(json.dumps(raw))
    cyclic["spans"][0]["depends_on"] = ["s-cleanup"]
    with pytest.raises(c.ContractError):
        c.ExecutionRecord.from_dict(cyclic)


def test_unknown_and_missing_fields_are_rejected():
    with pytest.raises(c.ContractError, match="unknown fields"):
        c.ExecutionSetting.from_dict({"setting_id": "C00", "tool_concurrency": False, "tool_workers": 1, "extra": 1})
    with pytest.raises(c.ContractError, match="missing fields"):
        c.ExecutionSetting.from_dict({"setting_id": "C00"})
    with pytest.raises(c.ContractError, match="tool_workers"):
        c.ExecutionSetting(setting_id="C00", tool_concurrency=False, tool_workers=0)


def test_model_response_failure_states():
    ok = dict(request_id="r", status="completed", model_hash="m", started_ns=1, ended_ns=2, clock_domain="d", text="x")
    assert c.ModelResponse(**ok).status == "completed"
    with pytest.raises(c.ContractError, match="error"):
        c.ModelResponse(**{**ok, "status": "timed_out", "text": None})
    with pytest.raises(c.ContractError, match="text"):
        c.ModelResponse(**{**ok, "text": None})
    with pytest.raises(c.ContractError, match="precede"):
        c.ModelResponse(**{**ok, "ended_ns": 0})


def test_sensor_sample_invalid_reads_are_null_with_reason():
    good = c.SensorSample(sample_id="s1", session_id="sess", domain_id="cpu-package-0", acquired_start_ns=1, acquired_end_ns=2, unit="uJ", value=12.0)
    assert good.status == "ok"
    with pytest.raises(c.ContractError, match="value=null"):
        c.SensorSample(sample_id="s2", session_id="sess", domain_id="cpu-package-0", acquired_start_ns=1, acquired_end_ns=2, unit="uJ", status="invalid", value=0.0, reason="x")
    with pytest.raises(c.ContractError, match="reason"):
        c.SensorSample(sample_id="s3", session_id="sess", domain_id="cpu-package-0", acquired_start_ns=1, acquired_end_ns=2, unit="uJ", status="missing")


def test_bridge_from_existing_ed03_verifier():
    """Producer/consumer check: Aldric's merged verifier output maps into the shared VerifierResult."""
    task = load_default_task()
    spec = c.load_example("task_spec")
    assert spec.asset_sha256 == task.asset_sha256 and spec.expected_result_sha256 == task.expected_result_sha256
    good = {
        "region_totals": {"North": 49.0, "South": 33.5, "West": 41.0},
        "product_totals": {"Widget": 62.5, "Gadget": 40.0, "Gizmo": 21.0},
        "reconciliation": {"region_total": 123.5, "product_total": 123.5, "difference": 0.0},
        "evidence": [task.asset_sha256],
    }
    passed = c.VerifierResult.from_data_analysis(verify_answer(task, good))
    assert passed.outcome == "pass" and passed.verifier_version == spec.verifier_version
    bad = json.loads(json.dumps(good)); bad["product_totals"]["Widget"] = 62.52
    failed = c.VerifierResult.from_data_analysis(verify_answer(task, bad))
    assert failed.outcome == "fail" and "mismatch" in failed.reason
    # a consumer (ledger) can embed it unchanged
    rec = c.load_example("execution_record_verified")
    rebuilt = c.ExecutionRecord.from_dict({**rec.to_dict(), "verifier": failed.to_dict()})
    assert rebuilt.verified is False
