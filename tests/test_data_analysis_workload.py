"""Focused tests for the first portable ED-03 goal and verifier."""

from decimal import Decimal

import pytest

from studies.energy_diagnosis.workloads.data_analysis import (
    TaskInputError,
    VERIFIER_VERSION,
    load_default_task,
    verify_answer,
)


@pytest.fixture()
def task():
    return load_default_task()


def valid_answer(task):
    return {
        "region_totals": {"North": 49.0, "South": 33.5, "West": 41.0},
        "product_totals": {"Widget": 62.5, "Gadget": 40.0, "Gizmo": 21.0},
        "reconciliation": {
            "region_total": 123.5,
            "product_total": 123.5,
            "difference": 0.0,
        },
        "evidence": [task.asset_sha256],
    }


def test_correct_answer_passes_independent_verifier(task):
    result = verify_answer(task, valid_answer(task))

    assert result["passed"] is True
    assert result["verifier_version"] == VERIFIER_VERSION
    assert result["expected_result_sha256"] == task.expected_result_sha256


def test_wrong_numeric_result_fails(task):
    answer = valid_answer(task)
    answer["product_totals"]["Widget"] = 62.52

    result = verify_answer(task, answer)

    assert result["passed"] is False


@pytest.mark.parametrize(
    "answer",
    [None, [], {"region_totals": {}, "product_totals": {}}],
)
def test_malformed_output_fails(task, answer):
    result = verify_answer(task, answer)

    assert result["passed"] is False
    assert result["verifier_version"] == VERIFIER_VERSION


def test_missing_evidence_fails(task):
    answer = valid_answer(task)
    answer.pop("evidence")

    result = verify_answer(task, answer)

    assert result["passed"] is False
    assert result["reason"] == "missing source evidence"


def test_invalid_task_input_is_rejected(task):
    invalid = {
        "task_id": task.task_id,
        "asset": "../outside.csv",
        "expected_result": "expected_result.json",
        "asset_sha256": task.asset_sha256,
        "expected_result_sha256": task.expected_result_sha256,
        "verifier_version": VERIFIER_VERSION,
        "absolute_tolerance": "0.01",
    }

    with pytest.raises(TaskInputError, match="inside the asset directory"):
        type(task).from_mapping(invalid)


def test_tolerance_is_contract_defined(task):
    answer = valid_answer(task)
    answer["region_totals"]["North"] = float(Decimal("49.009"))

    assert verify_answer(task, answer)["passed"] is True

@pytest.mark.parametrize("tolerance", ["Infinity", "-Infinity", "NaN"])
def test_non_finite_tolerance_is_rejected(task, tolerance):
    """Regression: an infinite tolerance let an all-zero answer pass; NaN escaped as InvalidOperation."""
    raw = {
        "task_id": task.task_id,
        "asset": "sales.csv",
        "expected_result": "expected_result.json",
        "asset_sha256": task.asset_sha256,
        "expected_result_sha256": task.expected_result_sha256,
        "verifier_version": VERIFIER_VERSION,
        "absolute_tolerance": tolerance,
    }

    with pytest.raises(TaskInputError, match="finite"):
        type(task).from_mapping(raw)


def test_pinned_hashes_match_lf_asset_bytes(task):
    """Regression: hashes were pinned on CRLF bytes, so the task failed to load on LF checkouts."""
    import hashlib

    asset_bytes = task.asset_path.read_bytes()
    expected_bytes = task.expected_result_path.read_bytes()

    assert b"\r\n" not in asset_bytes and b"\r\n" not in expected_bytes
    assert hashlib.sha256(asset_bytes).hexdigest() == task.asset_sha256
    assert hashlib.sha256(expected_bytes).hexdigest() == task.expected_result_sha256
