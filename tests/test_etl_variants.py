"""ETL environment variants: window functions, timeout feedback, index. Default = original task."""
import sqlite3
from types import SimpleNamespace

import pytest

from studies.energy_diagnosis.moe import etl_workload
from studies.energy_diagnosis.moe.etl_workload import ETLRuntime, ETLTool, create_task
from studies.energy_diagnosis.moe.task_pack import prepare

WINDOW = ("SELECT region, COUNT(*) AS event_count, SUM(gross_cents - tax_cents) AS net_cents FROM "
          "(SELECT *, ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY seq DESC) AS rn FROM raw) "
          "WHERE rn = 1 AND status = 'paid' GROUP BY region ORDER BY region")
GROUPED = ("SELECT region, COUNT(*) AS event_count, SUM(gross_cents - tax_cents) AS net_cents FROM raw "
           "WHERE (event_id, seq) IN (SELECT event_id, MAX(seq) FROM raw GROUP BY event_id) AND status = 'paid' "
           "GROUP BY region ORDER BY region")
V = dict(window_functions=True, feedback="explicit", index=True)


def run(tmp_path, variant, name="one"):
    task = create_task(tmp_path / ("assets-" + name), rows=2048, seed=5, variant=variant)
    runtime = ETLRuntime(tmp_path / ("runs-" + name))
    runtime.begin(task, SimpleNamespace(execution_id=name))
    return task, runtime, ETLTool(runtime.workspace)


def test_default_is_the_original_task(tmp_path):
    a = create_task(tmp_path / "a", rows=2048, seed=5)
    b = create_task(tmp_path / "b", rows=2048, seed=5, variant=None)
    assert a.task_id == b.task_id == "etl-latest-v3-n2048-s5"
    assert (a.asset_path/'raw.csv').read_bytes() == (b.asset_path/'raw.csv').read_bytes()
    assert a.asset_sha256 != b.asset_sha256  # independently prepared private challenge seeds
    assert create_task(a.asset_path, rows=2048, seed=5).asset_sha256 == a.asset_sha256
    desc = ETLRuntime(tmp_path).context(a)["tools"]["etl"]["description"]
    assert "ranking functions such as ROW_NUMBER are not exposed" in desc and "Read, write and test" in desc


def test_window_functions_only_when_enabled(tmp_path):
    task, runtime, tool = run(tmp_path, None, "off")
    tool.execute("write", WINDOW)
    with pytest.raises(sqlite3.DatabaseError):
        tool.execute("test")
    assert not runtime.verify(task, {"done": True})["passed"]
    task, runtime, tool = run(tmp_path, dict(V, index=False), "on")
    assert task.task_id.endswith("-w1fei0")
    assert "window functions such as ROW_NUMBER are supported" in runtime.context(task)["tools"]["etl"]["description"]
    tool.execute("write", WINDOW)
    assert not tool.execute("test")["truncated"]
    assert runtime.verify(task, {"done": True})["passed"]


@pytest.mark.parametrize("feedback", ["generic", "explicit"])
def test_timeout_feedback(tmp_path, monkeypatch, feedback):
    task, runtime, tool = run(tmp_path, dict(window_functions=False, feedback=feedback, index=False), feedback)
    tool.execute("write", GROUPED)
    monkeypatch.setattr(etl_workload, "QUERY_SECONDS", 0.0)
    if feedback == "explicit":
        with pytest.raises(etl_workload.QueryBudgetExceeded, match="10-second execution budget"):
            tool.execute("test")
    else:
        with pytest.raises(sqlite3.OperationalError, match="interrupted"):
            tool.execute("test")
    assert runtime.verify(task, {"done": True})["failure"] == "budget"


def test_index_variant_changes_assets_not_answers(tmp_path):
    plain, r1, t1 = run(tmp_path, dict(window_functions=False, feedback="generic", index=False), "plain")
    indexed, r2, t2 = run(tmp_path, dict(window_functions=False, feedback="generic", index=True), "idx")
    assert plain.asset_sha256 != indexed.asset_sha256 and indexed.task_id.endswith("-w0fgi1")
    db = sqlite3.connect(indexed.asset_path / "raw.sqlite")
    assert db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='raw_event_seq'").fetchone()
    db.close()
    for task, runtime, tool in ((plain, r1, t1), (indexed, r2, t2)):
        tool.execute("write", GROUPED)
        assert runtime.verify(task, {"done": True})["passed"]
    assert etl_workload.reference(plain) == etl_workload.reference(indexed)


def test_pack_accepts_and_validates_variants(tmp_path):
    pack = prepare(tmp_path / "p", [dict(kind="etl", rows=64, seed=1), dict(kind="etl", rows=64, seed=1, variant=V)])
    assert sorted(t.task_id for t in pack.tasks) == ["etl-latest-v3-n64-s1", "etl-latest-v3-n64-s1-w1fei1"]
    with pytest.raises(ValueError):
        prepare(tmp_path / "q", [dict(kind="etl", rows=64, seed=1, variant=dict(V, feedback="loud"))])
    with pytest.raises(ValueError):
        prepare(tmp_path / "r", [dict(kind="business", rows=64, seed=1, variant=V)])
