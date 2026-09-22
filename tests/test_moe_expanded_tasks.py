"""Independent contracts for the database, ETL, and numerical task families."""
import json
import sqlite3

import pytest

from studies.energy_diagnosis.moe.workloads import (
    BUGGY,
    ETL_BUGGY,
    TOOL_CONTRACTS,
    DatabaseTool,
    HiddenETLCheck,
    HiddenRepositoryCheck,
    NumericalTool,
    WorkloadRuntime,
    create_tasks,
)

ETL_REPAIR = (
    "def transform_rows(rows):\n"
    "    return [{'region': row['region'], 'net_cents': row['gross_cents'] - row['tax_cents']} for row in rows]\n"
)
FAMILIES = ("data-pipeline", "repository-repair", "database-analysis", "etl-repair", "numerical-analysis")


def task_set(tmp_path):
    return {task.family: task for task in create_tasks(tmp_path / "assets")}


def test_create_tasks_is_restart_safe_and_never_replaces_changed_inputs(tmp_path):
    first = create_tasks(tmp_path / "assets")
    second = create_tasks(tmp_path / "assets")  # Same directory: resume path.
    assert [t.task_id for t in first] == [t.task_id for t in second]
    assert [t.asset_sha256 for t in first] == [t.asset_sha256 for t in second]
    assert {t.family for t in first} == set(FAMILIES)
    assert not [p for p in (tmp_path / "assets").iterdir() if p.name.startswith(".")]
    for path, other in (("repository/pricing.py", "database/orders.sqlite"),):
        target = tmp_path / "assets" / path
        changed = "def net_cents(price, count, discount):\n    return 0\n"
        target.write_text(changed, encoding="utf-8", newline="\n")
        with pytest.raises(RuntimeError, match="differs from the moe-tools-v4 definition"):
            create_tasks(tmp_path / "assets")
        # The modified input is neither restored nor rewritten behind the operator's back.
        assert target.read_text(encoding="utf-8") == changed
        assert (tmp_path / "assets" / other).exists()
    db = sqlite3.connect(tmp_path / "assets" / "database" / "orders.sqlite")
    db.execute("UPDATE orders SET amount_cents = amount_cents + 1 WHERE order_id = 101")
    db.commit()
    db.close()
    # Restore the exact original bytes (no newline translation) so only the database differs.
    (tmp_path / "assets" / "repository" / "pricing.py").write_text(BUGGY, encoding="utf-8", newline="\n")
    with pytest.raises(RuntimeError, match="database"):
        create_tasks(tmp_path / "assets")


@pytest.mark.parametrize("family", FAMILIES)
def test_context_declares_exact_tool_contracts_and_hides_references(tmp_path, family):
    task = task_set(tmp_path)[family]
    runtime = WorkloadRuntime(tmp_path)
    context = runtime.context(task)
    assert context["family"] == family and context["tools"] == TOOL_CONTRACTS[family]
    assert "Follow the exact declared argument schema" in context["instruction"]
    (name, contract), = context["tools"].items()
    assert name in task.prompt or family == "repository-repair" and "pricing.py" in task.prompt
    assert contract["parameters"]["additionalProperties"] is False
    assert set(contract["parameters"]["properties"]) == set(contract["args"])
    assert contract["example_call"]["tool"] == name
    runtime.workspace = task.asset_path  # tool() selects by declared name and argument set only.
    assert type(runtime.tool(task, contract["example_call"])).__name__.endswith("Tool")
    if family in {"repository-repair", "etl-repair", "database-analysis"}:
        assert "depends_on" in contract["description"]  # Ordered read/write/test or schema/query steps.
    with pytest.raises(ValueError):
        runtime.tool(task, {"tool": name, "args": {"unexpected": 1, **contract["example_call"]["args"]}})
    with pytest.raises(ValueError):
        runtime.tool(task, {"tool": "other", "args": {}})
    assert task.expected == {}
    assert len(task.asset_sha256) == 64
    assert "expected" not in json.dumps(context) and "5650" not in json.dumps(context)


def test_tasks_have_distinct_identities(tmp_path):
    tasks = create_tasks(tmp_path / "assets")
    for field in ("task_id", "lineage", "asset_sha256", "asset_path", "prompt"):
        assert len({getattr(t, field) for t in tasks}) == len(tasks)


def test_database_tool_is_read_only_and_bounded(tmp_path):
    task = task_set(tmp_path)["database-analysis"]
    tool = DatabaseTool(str(task.asset_path / "orders.sqlite"))
    before = task.asset_sha256
    schema = tool.execute("schema")
    assert {"customers", "orders"} == set(schema["tables"])
    rows = tool.execute("query", "SELECT COUNT(*) FROM orders")["rows"]
    assert rows == [[9]]
    for action, sql in (
        ("query", "DELETE FROM orders"),
        ("query", "SELECT 1; DELETE FROM orders"),
        ("query", "PRAGMA writable_schema=ON"),
        ("query", None),
        ("schema", "SELECT 1"),
        ("drop", None),
    ):
        with pytest.raises(ValueError):
            tool.execute(action, sql)
    with pytest.raises(sqlite3.OperationalError):
        tool.execute("query", "SELECT * FROM missing")
    with pytest.raises(ValueError):
        tool.execute("query", "SELECT 1", workers=2)
    with pytest.raises(ValueError):
        NumericalTool(str(task.asset_path)).execute("read", workers=2)
    from studies.energy_diagnosis.workloads.pilot_tasks import _hash

    assert _hash(task.asset_path) == before


def test_database_answer_is_recomputed_and_wrong_partial_or_malformed_totals_fail(tmp_path):
    task = task_set(tmp_path)["database-analysis"]
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
    wrong = json.loads(json.dumps(answer))
    wrong["total_cents"] += 1
    assert not runtime.verify(task, wrong)["passed"]
    partial = json.loads(json.dumps(answer))
    del partial["by_segment"]["startup"]
    assert not runtime.verify(task, partial)["passed"]
    refunded_included = json.loads(json.dumps(answer))
    refunded_included["by_segment"]["enterprise"] = {"order_count": 5, "revenue_cents": 4900}
    refunded_included["total_cents"] = 6550
    assert not runtime.verify(task, refunded_included)["passed"]
    for malformed in (
        None, [], {"by_segment": {}, "total_cents": 5650.0},
        {"by_segment": {"enterprise": {"order_count": 3.0, "revenue_cents": 4000}}, "total_cents": 5650},
        {"by_segment": {"enterprise": {"order_count": 3, "revenue_cents": 4000, "extra": 1}}, "total_cents": 5650},
        {"by_segment": [], "total_cents": 5650}, {**answer, "extra": 1},
        {"by_segment": {"enterprise": {"order_count": True, "revenue_cents": 4000}}, "total_cents": 5650},
    ):
        result = runtime.verify(task, malformed)
        assert result["passed"] is False and result["reason"].startswith("invalid database")


def test_etl_checker_accepts_repair_and_rejects_buggy_source(tmp_path):
    task = task_set(tmp_path)["etl-repair"]
    source_path = task.asset_path / "etl.py"
    assert not HiddenETLCheck(str(source_path)).execute()["passed"]
    source_path.write_text(ETL_REPAIR, encoding="utf-8")
    assert HiddenETLCheck(str(source_path)).execute() == {"passed": True, "checks": 3}
    assert ETL_BUGGY != source_path.read_text(encoding="utf-8")
    runtime = WorkloadRuntime(tmp_path)
    runtime.workspace = task.asset_path
    assert runtime.verify(task, {"done": True})["passed"]
    assert not runtime.verify(task, {"done": False})["passed"]
    assert not runtime.verify(task, {"answer": "done"})["passed"]


@pytest.mark.parametrize("source", [
    "def transform_rows(rows: list):\n    return [{'region': row['region'], 'net_cents': row['gross_cents'] - row['tax_cents']} for row in rows]\n",
    "def transform_rows(rows) -> list:\n    return [{'region': row['region'], 'net_cents': row['gross_cents'] - row['tax_cents']} for row in rows]\n",
    "def transform_rows(rows):  # type: (list) -> list\n    return [{'region': row['region'], 'net_cents': row['gross_cents'] - row['tax_cents']} for row in rows]\n",
    "def transform_rows(rows):\n    return [{'region': row['region'], 'net_cents': row['gross_cents'] - row['tax_cents'] + 0.0} for row in rows]\n",
    "def transform_rows(rows):\n    return [{'region': row['region'], 'net_cents': row['gross_cents'] - row['tax_cents']} for row in rows if row]\n",
    "def transform_rows(rows):\n    return [{'region': row['region'], 'net_cents': row['gross_cents'] - row['tax_cents']} for rows2 in [rows] for row in rows2]\n",
    "def transform_rows(rows):\n    'doc'\n    return [{'region': row['region'], 'net_cents': row['gross_cents'] - row['tax_cents']} for row in rows]\n",
    "def transform_rows(rows):\n    out = []\n    return out\n",
    "def transform_rows(rows):\n    return [dict(region=row['region'], net_cents=row['gross_cents'] - row['tax_cents']) for row in rows]\n",
    "def transform_rows(rows, extra=None):\n    return [{'region': row['region'], 'net_cents': row['gross_cents'] - row['tax_cents']} for row in rows]\n",
    "import os\ndef transform_rows(rows):\n    return []\n",
    "def transform_rows(rows):\n    return [{'region': row['region'], 'net_cents': (lambda: 0)()} for row in rows]\n",
    "def transform_rows(rows):\n    return [{'region': (r:=row)['region'], 'net_cents': 0} for row in rows]\n",
    "",
])
def test_etl_language_violations_have_an_explicit_contract_failure(tmp_path, source):
    path = tmp_path / "etl.py"
    path.write_text(source, encoding="utf-8")
    assert HiddenETLCheck(str(path)).execute() == {"passed": False, "reason": "source violates the bounded ETL language"}


@pytest.mark.parametrize("source", [
    "def transform_rows(rows):\n    return [{'region': row['region'], 'net_cents': row['gross_cents'] + row['tax_cents']} for row in rows]\n",
    "def transform_rows(rows):\n    return [{'region': row['region'], 'net_cents': row['gross_cents'] - row['tax_cents'], 'x': 1} for row in rows]\n",
    "def transform_rows(rows):\n    return [{'region': row['region']} for row in rows]\n",
    "def transform_rows(rows):\n    return rows\n",
    "def transform_rows(rows):\n    return [{'region': row['region'], 'net_cents': row['missing']} for row in rows]\n",
])
def test_etl_behavior_violations_fail_hidden_cases(tmp_path, source):
    path = tmp_path / "etl.py"
    path.write_text(source, encoding="utf-8")
    assert HiddenETLCheck(str(path)).execute()["passed"] is False


def test_etl_syntax_error_is_reported(tmp_path):
    path = tmp_path / "etl.py"
    path.write_text("def transform_rows(rows)\n    return 1\n", encoding="utf-8")
    assert HiddenETLCheck(str(path)).execute() == {"passed": False, "reason": "invalid Python source"}


def test_repository_checker_rejects_type_comments_and_syntax_errors(tmp_path):
    path = tmp_path / "pricing.py"
    path.write_text("def net_cents(price, count, discount):  # type: (int, int, int) -> int\n    return (price * count * (100 - discount) + 50) // 100\n")
    assert HiddenRepositoryCheck(str(path)).execute() == {"passed": False, "reason": "source violates the declared constrained arithmetic repair language"}
    path.write_text("def net_cents(price, count, discount)\n    return 1\n")
    assert HiddenRepositoryCheck(str(path)).execute() == {"passed": False, "reason": "invalid Python source"}


def test_numerical_answer_uses_exact_reference_and_finite_types(tmp_path):
    task = task_set(tmp_path)["numerical-analysis"]
    runtime = WorkloadRuntime(tmp_path)
    rows = NumericalTool(str(task.asset_path)).execute("read")["rows"]
    assert rows == [[x, 3 * x + 2 + (-1 if x % 3 == 0 else 1 if x % 3 == 1 else 0)] for x in range(1, 10)]
    assert runtime.verify(task, {"slope": 2.9, "intercept": 2.5, "rmse": 0.774597})["passed"]
    for wrong in (
        {"slope": 2.9, "intercept": 2.5, "rmse": float("nan")},
        {"slope": 2.9, "intercept": 2.5, "rmse": float("inf")},
        {"slope": 2.9, "intercept": 2.5, "rmse": 0.0},
        {"slope": 2.9, "intercept": 2.5, "rmse": 0.7746},
        {"slope": 2.9, "intercept": 2.5},
        {"slope": 2.9, "intercept": 2.5, "rmse": "0.774597"},
        {"slope": True, "intercept": 2.5, "rmse": 0.774597},
        {"slope": 2.9, "intercept": 2.5, "rmse": 0.774597, "r2": 1},
        None, [2.9, 2.5, 0.774597],
    ):
        assert not runtime.verify(task, wrong)["passed"]
