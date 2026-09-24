import json
from copy import deepcopy

from studies.energy_diagnosis.moe.audit_pilot import audit, call_checks, compare_calls


def calls():
    return [dict(request={"turn": i}, adapter=dict(content="answer", backend=dict(
        tokens=dict(prompt=10 + i, completion=4),
        prefix_cache=dict(mode="exact_prefix", new_prefill_tokens=10 - i,
                          reused_prefix_tokens=2 * i, decode_forward_tokens=3)))) for i in range(2)]


def test_observed_prefill_and_decode_reconcile_with_tokens():
    x = calls()
    assert all(call_checks(x, "exact_prefix").values())
    x[1]["adapter"]["backend"]["prefix_cache"]["decode_forward_tokens"] = 0
    assert not call_checks(x, "exact_prefix")["token_accounting"]
    x[0]["adapter"]["backend"]["tokens"]["prompt"] = True
    assert not call_checks(x, "exact_prefix")["token_accounting"]


def test_claimed_prefix_setting_without_reuse_does_not_pass():
    x = calls()[:1]
    assert not call_checks(x, "exact_prefix")["prefix_reuse_exercised"]
    assert not call_checks(x, "disabled")["prefix_mode"]
    assert not all(call_checks([], "exact_prefix").values())


def test_pair_comparison_detects_prompt_or_output_changes():
    a, b = calls(), calls()
    assert all(compare_calls(a, b).values())
    b[1]["request"]["elapsed_ns"] = 123
    assert not compare_calls(a, b)["same_requests"]
    b = deepcopy(a)
    b[1]["adapter"]["content"] = "different"
    assert not compare_calls(a, b)["same_outputs"]


def test_missing_or_interrupted_stage_cannot_pass(tmp_path):
    assert not audit(tmp_path, prefix_mode="exact_prefix")["smoke_passed"]
    (tmp_path / "job").mkdir()
    (tmp_path / "job/status.json").write_text(json.dumps(dict(status="interference_detected", returncode=76, cleanup_complete=True)))
    result = audit(tmp_path, prefix_mode="exact_prefix")
    assert not result["smoke_passed"]
    assert not result["checks"]["guarded_stage_completed"]
