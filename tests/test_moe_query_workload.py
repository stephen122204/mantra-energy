"""Queryable task correctness, read-only boundary and full fixture integration."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from studies.energy_diagnosis.moe.query_workload import (
    VERSION, TASK_ID, LINEAGE, QueryRuntime, QueryTool, DuckQueryTool, file_hash, load_task,
)

ROWS = [
    ("2025-01-01 01:00:00", 1, 1, 1.0, 10.0),
    ("2025-01-01 01:00:00", 1, 1, 1.0, 10.0),  # duplicate counts twice
    ("2025-01-31 23:59:59.999999", 1, 1, 2.0, 20.0),
    ("2024-12-31 23:59:59", 1, 1, 1.0, 10.0),
    ("2025-02-01 00:00:00", 1, 1, 1.0, 10.0),
    ("2025-01-01 01:00:00", 2, 1, 1.0, 10.0),
    ("2025-01-01 01:00:00", 1, 2, 1.0, 10.0),
    ("2025-01-01 01:00:00", 1, 1, 0.0, 10.0),
    ("2025-01-01 01:00:00", 1, 1, 1.0, -10.0),
    (None, 1, 1, 1.0, 10.0),
    ("2025-01-01 01:00:00", None, 1, 1.0, 10.0),
    ("2025-01-01 01:00:00", 1, None, 1.0, 10.0),
    ("2025-01-01 01:00:00", 1, 1, None, 10.0),
    ("2025-01-01 01:00:00", 1, 1, 1.0, None),
]


def assets(root, duck=False):
    root.mkdir()
    db = sqlite3.connect(root / "trips.sqlite")
    db.executescript("CREATE TABLE trips(tpep_pickup_datetime TEXT, PULocationID INTEGER, payment_type INTEGER, trip_distance REAL, fare_amount REAL);"
                    "CREATE TABLE zones(LocationID INTEGER PRIMARY KEY, Borough TEXT, Zone TEXT, service_zone TEXT);")
    db.executemany("INSERT INTO trips VALUES(?,?,?,?,?)", ROWS)
    db.executemany("INSERT INTO zones VALUES(?,?,?,?)", [(1,"Manhattan","a","Yellow"), (2,"Queens","b","Yellow")])
    db.commit(); db.close()
    counts = [0] * 24
    counts[1], counts[23] = 2, 1
    manifest = dict(version=VERSION, task_id=TASK_ID, lineage=LINEAGE,
                    simulated_source=True, database_sha256=file_hash(root / "trips.sqlite"),
                    expected=dict(hour_counts=counts, total_trips=3))
    if duck:
        duckdb = pytest.importorskip("duckdb")
        db = duckdb.connect(str(root / "trips.duckdb"))
        db.execute("CREATE TABLE trips(tpep_pickup_datetime TIMESTAMP, PULocationID INTEGER, payment_type INTEGER, trip_distance DOUBLE, fare_amount DOUBLE)")
        db.execute("CREATE TABLE zones(LocationID INTEGER PRIMARY KEY, Borough VARCHAR, Zone VARCHAR, service_zone VARCHAR)")
        db.executemany("INSERT INTO trips VALUES(?,?,?,?,?)", ROWS)
        db.executemany("INSERT INTO zones VALUES(?,?,?,?)", [(1,"Manhattan","a","Yellow"), (2,"Queens","b","Yellow")])
        db.close()
        manifest["duckdb_sha256"] = file_hash(root / "trips.duckdb")
    (root / "task-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return load_task(root, allow_fixture=True)


def test_independent_answer_types_and_reference_is_not_in_tool_context(tmp_path):
    task = assets(tmp_path / "assets")
    runtime = QueryRuntime()
    runtime.begin(task, None)
    assert runtime.verify(task, task.expected)["passed"]
    bad = json.loads(json.dumps(task.expected)); bad["hour_counts"][1] -= 1; bad["total_trips"] -= 1
    assert not runtime.verify(task, bad)["passed"]
    for value in (3.0, True, "3", None):
        assert not runtime.verify(task, task.expected | {"total_trips": value})["passed"]
    assert not runtime.verify(task, {"hour_counts": [0]*24, "total_trips": 0})["passed"]
    assert "expected" not in json.dumps(runtime.context(task))
    result = runtime.tool(task, dict(tool="sql", args={})).execute("schema")
    assert set(result["tables"]) == {"trips", "zones"}
    assert "reference" not in json.dumps(result)


@pytest.mark.parametrize("sql", [
    "DELETE FROM trips", "DROP TABLE trips", "PRAGMA user_version=1",
    "ATTACH DATABASE ':memory:' AS other", "SELECT load_extension('anything')",
    "SELECT * FROM sqlite_master", "SELECT 1; SELECT 2",
])
def test_queries_cannot_mutate_or_read_outside_declared_tables(tmp_path, sql):
    task = assets(tmp_path / "assets")
    db = task.asset_path / "trips.sqlite"
    before = file_hash(db)
    with pytest.raises(sqlite3.Error):
        QueryTool(str(db)).execute("query", sql)
    assert file_hash(db) == before


def test_budget_and_truncation_are_real(tmp_path):
    task = assets(tmp_path / "assets")
    tool = QueryTool(str(task.asset_path / "trips.sqlite"))
    result = tool.execute("query", "SELECT a.PULocationID FROM trips a CROSS JOIN trips b")
    assert len(result["rows"]) == 128 and result["truncated"]
    assert result["tool_accounting"]["elapsed_ns"] > 0
    with pytest.raises(sqlite3.OperationalError, match="interrupted"):
        QueryTool(tool.database, max_seconds=0.001).execute("query", "SELECT count(*) FROM trips a,trips b,trips c,trips d,trips e,trips f,trips g")
    with pytest.raises(ValueError, match="one worker"):
        tool.execute("schema", workers=4)
    with pytest.raises(ValueError):
        tool.execute("query", "x"*32769)


def test_source_identity_cannot_silently_change(tmp_path):
    task = assets(tmp_path / "assets")
    with pytest.raises(ValueError, match="synthetic source"):
        load_task(task.asset_path)
    db = sqlite3.connect(task.asset_path / "trips.sqlite")
    db.execute("DELETE FROM trips"); db.commit(); db.close()
    with pytest.raises(ValueError, match="database changed"):
        load_task(task.asset_path, allow_fixture=True)


@pytest.mark.parametrize("case,passes", [("success", True), ("wrong_answer", False)])
@pytest.mark.parametrize("engine", ["sqlite", "duckdb"])
def test_full_query_goal_executes_tools_and_retains_verifier_result(tmp_path, case, passes, engine):
    task = assets(tmp_path / "assets", duck=engine == "duckdb")
    output = tmp_path / "run"
    result = subprocess.run([sys.executable, "-m", "studies.energy_diagnosis.moe.run",
        "--mode", "fixture", "--query-assets", str(task.asset_path), "--output", str(output),
        "--query-engine", engine,
        "--policies", "demand,fixed", "--max-runs", "2", "--deadline", "30", "--fixture-case", case],
        capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["executed"] == 2 and report["window_audit"]["audit_passed"]
    catalog = json.loads((output / "moe-manifest.json").read_text())["task_catalog"]
    assert len(catalog) == 1 and catalog[0]["lineage"] == LINEAGE
    assert catalog[0]["asset_sha256"] == task.asset_sha256
    for path in (output / "goals").glob("*/tool-results.json"):
        rows = json.loads(path.read_text())
        assert len(rows) == 2 and all(row["status"] == "completed" for row in rows)
        assert rows[1]["result"]["rows"] == [[1, 2], [23, 1]]
        calls = json.loads(path.with_name("model-calls.json").read_text())
        assert len(calls) == 3 and "expected" not in json.loads(calls[0]["prompt"])
    attempts = [json.loads(s)["attempt"] for s in (output / "exports" / "attempts.jsonl").read_text().splitlines()]
    assert len(attempts) == 2
    assert all(a["verifier_outcome"] == ("pass" if passes else "fail") for a in attempts)


@pytest.mark.parametrize("sql", [
    "DELETE FROM trips", "CREATE TEMP TABLE extra(x INTEGER)", "SET threads=4",
    "SELECT 1; SELECT 2", "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM read_parquet('https://example.com/remote.parquet')",
])
def test_analytical_engine_rejects_mutation_configuration_and_external_io(tmp_path, sql):
    duckdb = pytest.importorskip("duckdb")
    task = assets(tmp_path / "assets", duck=True)
    db = task.asset_path / "trips.duckdb"
    before = file_hash(db)
    with pytest.raises((ValueError, duckdb.Error)):
        DuckQueryTool(str(db)).execute("query", sql)
    assert file_hash(db) == before


def test_analytical_timeout_interrupts_owned_query(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    task = assets(tmp_path / "assets", duck=True)
    with pytest.raises(duckdb.InterruptException):
        DuckQueryTool(str(task.asset_path / "trips.duckdb"), max_seconds=0.03).execute(
            "query", "SELECT sum(a.i*b.i) FROM range(1000000000) a(i), range(1000000000) b(i)")


def test_optional_raw_parquet_reference_agrees_with_hand_checked_cases(tmp_path):
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq
    from datetime import datetime
    from studies.energy_diagnosis.moe.query_workload import COLUMNS, reference_counts

    raw = [{name: (datetime.fromisoformat(row[0]) if row[0] else None) if i == 0 else row[i]
            for i,name in enumerate(COLUMNS)} for row in ROWS]
    parquet = tmp_path / "source.parquet"
    pq.write_table(pa.Table.from_pylist(raw), parquet)
    zones = tmp_path / "zones.csv"
    zones.write_text("LocationID,Borough\n1,Manhattan\n2,Queens\n", encoding="utf-8")
    task = assets(tmp_path / "assets")
    assert reference_counts(parquet, zones) == task.expected
