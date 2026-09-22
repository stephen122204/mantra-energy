"""Independent contracts for the database, ETL, and numerical task families."""
import json

import pytest

from studies.energy_diagnosis.moe.workloads import (
    ETL_BUGGY,
    HiddenETLCheck,
    WorkloadRuntime,
    create_tasks,
)


def task_set(tmp_path):
    return {task.family: task for task in create_tasks(tmp_path / "assets")}


def test_database_answer_is_recomputed_and_wrong_totals_fail(tmp_path):
    tasks = task_set(tmp_path)
    task = tasks["database-analysis"]
    runtime = WorkloadRuntime(tmp_path)
    answer = {
        "by_segment": {
            "enterprise": {"order_count": 3, "revenue_cents": 4000},
            "small": {"order_count": 2, "revenue_cents": 1200},
            "startup": {"order_count": 1, "revenue_cents": 450},
        },
        "total_cents": 5650,
    }
    assert runtime.verify(task, answer)["passed"]
    answer["total_cents"] += 1
    assert not runtime.verify(task, answer)["passed"]


def test_etl_checker_accepts_repair_and_rejects_buggy_source(tmp_path):
    tasks = task_set(tmp_path)
    task = tasks["etl-repair"]
    source_path = task.asset_path / "etl.py"
    assert not HiddenETLCheck(str(source_path)).execute()["passed"]
    source_path.write_text(
        "def transform_rows(rows):\n"
        "    return [{'region': row['region'], 'net_cents': row['gross_cents'] - row['tax_cents']} for row in rows]\n",
        encoding="utf-8",
    )
    assert HiddenETLCheck(str(source_path)).execute() == {"passed": True, "checks": 3}
    assert ETL_BUGGY != source_path.read_text(encoding="utf-8")


def test_numerical_answer_uses_exact_reference_and_finite_types(tmp_path):
    tasks = task_set(tmp_path)
    task = tasks["numerical-analysis"]
    runtime = WorkloadRuntime(tmp_path)
    assert runtime.verify(task, {"slope": 2.9, "intercept": 2.5, "rmse": 0.774597})["passed"]
    assert not runtime.verify(task, {"slope": 2.9, "intercept": 2.5, "rmse": float("nan")})["passed"]
    assert not runtime.verify(task, {"slope": 2.9, "intercept": 2.5, "rmse": 0.0})["passed"]


@pytest.mark.parametrize("family", ["database-analysis", "etl-repair", "numerical-analysis"])
def test_new_tasks_have_distinct_versioned_assets_and_prompts(tmp_path, family):
    task = task_set(tmp_path)[family]
    assert len(task.asset_sha256) == 64
    assert family in task.prompt or (family == "etl-repair" and "ETL" in task.prompt)
    assert task.expected == {}