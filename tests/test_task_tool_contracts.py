"""Execute documented first calls and reject ambiguous/missing tool actions."""
from types import SimpleNamespace
import pytest
from studies.energy_diagnosis.moe.business_workload import BusinessRuntime, create_tasks
from studies.energy_diagnosis.moe.etl_workload import ETLRuntime, create_task
from studies.energy_diagnosis.moe.numerical_workload import (
    RegressionRuntime,
    create_task as numerical_task,
)
from studies.energy_diagnosis.moe.tool_contracts import (
    validate_action,
    SQL_ACTIONS,
    ETL_ACTIONS,
)


@pytest.mark.parametrize("family", ["business", "etl", "numerical"])
def test_documented_first_call_executes_and_schema_is_explicit(tmp_path, family):
    if family == "business":
        task = create_tasks(tmp_path / "assets", rows=64)[0]
        runtime = BusinessRuntime(tmp_path / "run")
    elif family == "etl":
        task = create_task(tmp_path / "assets", rows=64)
        runtime = ETLRuntime(tmp_path / "run")
    else:
        task = numerical_task(tmp_path / "assets", rows=64)
        runtime = RegressionRuntime(tmp_path / "run")
    runtime.begin(task, SimpleNamespace(execution_id="example"))
    contract = next(iter(runtime.context(task)["tools"].values()))
    call = contract["example_call"]
    args = call["args"]
    matching = [
        v
        for v in contract["parameters"]["oneOf"]
        if v["properties"]["action"]["const"] == args["action"]
    ]
    assert len(matching) == 1 and set(args) == set(matching[0]["required"])
    result = runtime.tool(task, call).execute(**args)
    assert isinstance(result, dict) and result
    if family == "business":
        assert set(result["tables"]) == {"customers", "transactions"}
        columns = {c["name"] for c in result["tables"]["transactions"]}
        assert {"year", "cents", "customer_id"} <= columns
        with pytest.raises(ValueError, match="action"):
            runtime.tool(
                task,
                {"tool": "sql", "args": {"sql": "SELECT COUNT(*) FROM transactions"}},
            )
    if family == "etl":
        assert "source" in result and "schema" in result


@pytest.mark.parametrize(
    "actions,args",
    [
        (SQL_ACTIONS, {}),
        (SQL_ACTIONS, {"sql": "SELECT 1"}),
        (SQL_ACTIONS, {"action": "schema", "sql": "SELECT 1"}),
        (SQL_ACTIONS, {"action": "query"}),
        (SQL_ACTIONS, {"action": "query", "sql": " "}),
        (ETL_ACTIONS, {"action": "write"}),
        (ETL_ACTIONS, {"action": "read", "content": "SELECT 1"}),
        (ETL_ACTIONS, {"action": "test", "content": "SELECT 1"}),
        (ETL_ACTIONS, {"action": ["read"]}),
    ],
)
def test_argument_combinations_match_declared_required_fields(actions, args):
    with pytest.raises(ValueError):
        validate_action(args, actions)
