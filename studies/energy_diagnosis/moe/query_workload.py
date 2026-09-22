"""Optional bounded SQL workload over prepared, immutable TLC source data.

Only offline preparation needs PyArrow; the default query runtime uses DuckDB.
The model receives schema/query tools,
never the reference manifest. This is one data lineage, not an agent benchmark.
"""
from dataclasses import dataclass
import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time

from studies.energy_diagnosis.workloads.pilot_tasks import PilotTask, _hash

VERSION = "tlc-query-v1"
TASK_ID = "tlc-manhattan-hours-2025-01-v1"
LINEAGE = "nyc-tlc-yellow-trips"
SOURCE_PAGE = "https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page"
SOURCES = {
    "trips": ("https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2025-01.parquet",
              "9af277e4c0d3f9deb30644da822981e1e7df6af58313170fd3aa8a474485488a"),
    "zones": ("https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv",
              "1a99e105092230f8620f301edcca7f80d3080642ff404d28ed957d3fa222c8ed"),
}
COLUMNS = ["tpep_pickup_datetime", "PULocationID", "payment_type", "trip_distance", "fare_amount"]
PROMPT = (
    "Using the supplied January 2025 NYC yellow taxi records and zone lookup, count "
    "trips by pickup hour for pickup zones whose Borough is exactly Manhattan. "
    "Include only payment_type=1 (card), trip_distance>0, fare_amount>0, and pickup "
    "timestamps >=2025-01-01 00:00:00 and <2025-02-01 00:00:00. Exclude nulls in "
    "these required fields. Timestamps are recorded local wall times; do not convert "
    "time zones. Count records as supplied, including duplicates. Return "
    '{"hour_counts":[24 integer counts in hour order 0..23],"total_trips":integer}. '
    "Inspect the schema and query the database as needed. Do not assume all records "
    "in the monthly file fall within the stated month."
)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reference_counts(trips_path, zones_path):
    """Read original Parquet directly, independently of SQLite conversion/query."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    with Path(zones_path).open(newline="", encoding="utf-8") as handle:
        manhattan = [int(r["LocationID"]) for r in csv.DictReader(handle) if r["Borough"] == "Manhattan"]
    counts = [0] * 24
    for batch in pq.ParquetFile(trips_path).iter_batches(columns=COLUMNS, batch_size=65536):
        pickup = batch.column("tpep_pickup_datetime")
        valid = pc.and_kleene(pc.greater_equal(pickup, pa.scalar(datetime(2025, 1, 1), type=pickup.type)),
                              pc.less(pickup, pa.scalar(datetime(2025, 2, 1), type=pickup.type)))
        for condition in (
            pc.is_in(batch.column("PULocationID"), value_set=pa.array(manhattan, type=batch.column("PULocationID").type)),
            pc.equal(batch.column("payment_type"), 1),
            pc.greater(batch.column("trip_distance"), 0),
            pc.greater(batch.column("fare_amount"), 0),
        ):
            valid = pc.and_kleene(valid, condition)
        hours = pc.hour(pc.filter(pickup, pc.fill_null(valid, False)))
        for item in pc.value_counts(hours).to_pylist():
            counts[item["values"]] += item["counts"]
    return {"hour_counts": counts, "total_trips": sum(counts)}


def prepare(trips_path, zones_path, output):
    """Prepare the pinned public inputs once, outside measured model execution."""
    import pyarrow
    import pyarrow.parquet as pq
    import duckdb

    paths = {"trips": Path(trips_path), "zones": Path(zones_path)}
    for role, path in paths.items():
        if file_hash(path) != SOURCES[role][1]:
            raise ValueError(f"{role} bytes differ from the pinned source; do not silently revise the task")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    database = root / "trips.sqlite"
    db = sqlite3.connect(database)
    rows = 0
    try:
        db.executescript("CREATE TABLE trips(tpep_pickup_datetime TEXT, PULocationID INTEGER, payment_type INTEGER, trip_distance REAL, fare_amount REAL);"
                         "CREATE TABLE zones(LocationID INTEGER PRIMARY KEY, Borough TEXT, Zone TEXT, service_zone TEXT);")
        with paths["zones"].open(newline="", encoding="utf-8") as handle:
            db.executemany("INSERT INTO zones VALUES (?,?,?,?)", [(int(r["LocationID"]), r["Borough"], r["Zone"], r["service_zone"]) for r in csv.DictReader(handle)])
        for batch in pq.ParquetFile(paths["trips"]).iter_batches(columns=COLUMNS, batch_size=65536):
            records = []
            for row in batch.to_pylist():
                ts = row[COLUMNS[0]]
                records.append((ts.isoformat(sep=" ") if ts is not None else None, *(row[c] for c in COLUMNS[1:])))
            db.executemany("INSERT INTO trips VALUES (?,?,?,?,?)", records)
            rows += len(records)
        db.commit()
    finally:
        db.close()
    expected = reference_counts(paths["trips"], paths["zones"])
    columnar = root / "trips.duckdb"
    analytical = duckdb.connect(str(columnar), config={"threads": 1, "memory_limit": "512MB"})
    try:
        analytical.execute("CREATE TABLE trips AS SELECT " + ",".join(COLUMNS) + " FROM read_parquet(?)", [str(paths["trips"])])
        analytical.execute("CREATE TABLE zones AS SELECT * FROM read_csv_auto(?)", [str(paths["zones"])])
        if analytical.execute("SELECT count(*) FROM trips").fetchone()[0] != rows:
            raise ValueError("prepared engines disagree on source row count")
    finally:
        analytical.close()
    manifest = dict(version=VERSION, task_id=TASK_ID, lineage=LINEAGE, rows=rows,
                    source_page=SOURCE_PAGE, sources={role: dict(url=SOURCES[role][0], sha256=SOURCES[role][1], bytes=path.stat().st_size) for role,path in paths.items()},
                    database_sha256=file_hash(database), duckdb_sha256=file_hash(columnar), expected=expected,
                    preparation=dict(pyarrow=pyarrow.__version__, sqlite=sqlite3.sqlite_version, duckdb=duckdb.__version__,
                                     source_sha256=file_hash(__file__)),
                    scope="Published source records; correctness is relative to the stated query, not real-world data accuracy.")
    (root / "task-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"output": str(root), "rows": rows, "database_bytes": database.stat().st_size, "database_sha256": manifest["database_sha256"]}


def load_task(root, *, allow_fixture=False, engine="sqlite"):
    if engine not in {"sqlite", "duckdb"}:
        raise ValueError("unsupported query engine")
    if engine == "duckdb":
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError("install duckdb==1.5.0 in the ALEMS driver/tool interpreter before launching a model") from exc
        if duckdb.__version__ != "1.5.0":
            raise ValueError("query runtime requires qualified duckdb==1.5.0")
    root = Path(root).resolve()
    manifest = json.loads((root / "task-manifest.json").read_text(encoding="utf-8"))
    if (manifest["version"], manifest["task_id"], manifest["lineage"]) != (VERSION, TASK_ID, LINEAGE):
        raise ValueError("unsupported query task identity")
    fixture = manifest.get("simulated_source", False)
    if fixture:
        if not allow_fixture:
            raise ValueError("synthetic source cannot be used in native mode")
    elif any(manifest.get("sources", {}).get(role, {}).get("sha256") != sha for role, (_, sha) in SOURCES.items()):
        raise ValueError("query manifest must identify the pinned public sources")
    if file_hash(root / "trips.sqlite") != manifest["database_sha256"]:
        raise ValueError("prepared query database changed")
    if engine == "duckdb" and file_hash(root / "trips.duckdb") != manifest.get("duckdb_sha256"):
        raise ValueError("prepared analytical database changed")
    expected = manifest["expected"]
    if not valid_answer(expected):
        raise ValueError("invalid query reference")
    return PilotTask(TASK_ID, "sql-query", LINEAGE, root, expected, _hash(root), (), PROMPT)


def valid_answer(answer):
    return (isinstance(answer, dict) and set(answer) == {"hour_counts", "total_trips"}
            and isinstance(answer["hour_counts"], list) and len(answer["hour_counts"]) == 24
            and all(type(v) is int and v >= 0 for v in answer["hour_counts"])
            and type(answer["total_trips"]) is int and answer["total_trips"] == sum(answer["hour_counts"]))


@dataclass
class QueryTool:
    database: str
    max_seconds: float = 10.0
    tables: tuple[str, ...] = ("trips", "zones")

    def execute(self, action, sql=None, workers=1):
        if not self.tables or any(not isinstance(name, str) or not name or not name.isascii() or not (name[0].isalpha() or name[0] == "_") or not name.replace("_", "").isalnum() for name in self.tables):
            raise ValueError("table names must be nonempty ASCII identifiers")
        if workers != 1:
            raise ValueError("this SQLite tool supports one worker")
        if action not in {"schema", "query"} or (action == "schema" and sql is not None):
            raise ValueError("use schema or query(sql)")
        if action == "query" and (not isinstance(sql, str) or not sql.strip() or len(sql.encode()) > 32768):
            raise ValueError("query must be nonempty SQL up to 32768 bytes")
        started, cpu = time.monotonic_ns(), time.process_time_ns()
        db = sqlite3.connect(Path(self.database).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA cache_size=-8192")
            db.execute("PRAGMA temp_store=MEMORY")
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 65536)
            db.set_progress_handler(lambda: int((time.monotonic_ns()-started)/1e9 > self.max_seconds), 1000)
            if action == "schema":
                payload = {"tables": {name: [dict(name=r[1], type=r[2]) for r in db.execute(f"PRAGMA table_info({name})")] for name in self.tables}}
            else:
                functions = {"count", "sum", "min", "max", "avg", "total", "strftime", "date", "datetime", "substr", "substring", "coalesce", "ifnull", "nullif", "lower", "upper", "trim", "length", "abs", "round", "like", "typeof"}

                def authorize(op, a, b, database, trigger):
                    if op == sqlite3.SQLITE_SELECT:
                        return sqlite3.SQLITE_OK
                    # SQLite reports a whole-table/count-only read with an
                    # empty column and no database name on some builds.
                    if op == sqlite3.SQLITE_READ and a in self.tables and (database == "main" or (database is None and b == "")):
                        return sqlite3.SQLITE_OK
                    if op == sqlite3.SQLITE_FUNCTION and (b or "").lower() in functions:
                        return sqlite3.SQLITE_OK
                    return sqlite3.SQLITE_DENY

                db.set_authorizer(authorize)
                result = db.execute(sql)
                rows = result.fetchmany(129)
                payload = {"columns": [c[0] for c in result.description], "rows": [list(r) for r in rows[:128]], "truncated": len(rows) > 128}
                if len(json.dumps(payload, allow_nan=False).encode()) > 65536:
                    raise ValueError("query result exceeds 65536 bytes; aggregate or select fewer columns")
            payload["tool_accounting"] = dict(elapsed_ns=time.monotonic_ns()-started, cpu_ns=time.process_time_ns()-cpu,
                                              sqlite=sqlite3.sqlite_version, workers=1)
            return payload
        finally:
            db.close()


class QueryRuntime:
    def __init__(self, fixture_case=None, engine="sqlite"):
        self.fixture_case, self.engine = fixture_case, engine

    def begin(self, task, lease):
        # GoalExecutor already verified the immutable asset hash before model
        # startup. No per-goal copy: the only exposed tool opens this DB read-only.
        self.database = str(task.asset_path / ("trips.duckdb" if self.engine == "duckdb" else "trips.sqlite"))

    def context(self, task):
        return dict(family="sql-query", tools={"sql": {
            "description": f"{self.engine} read-only database. action=schema returns table columns; action=query requires a single SELECT SQL statement. No writes, attachments, PRAGMAs or external access. Query limit 10 seconds, 128 returned rows, 65536 output bytes, 32768 SQL bytes. Aggregate in SQL; truncated results are labeled. One worker. Strings are case-sensitive unless SQL says otherwise.",
            "args": {"action": "schema|query", "sql": "only for query"}}},
            instruction='Return only JSON: {"tool_calls":[{"id":"unique","tool":"sql","args":{...}}]} or {"answer":{...}}. Use actual tool results, not invented observations. The final answer must follow the goal schema.')

    def tool(self, task, call):
        if self.fixture_case in {"tool_failure", "tool_timeout"}:
            from .workloads import InjectedFailureTool
            return InjectedFailureTool(self.fixture_case == "tool_timeout")
        args = call.get("args", {})
        if call.get("tool") != "sql" or not isinstance(args, dict) or set(args) - {"action", "sql"}:
            raise ValueError("query request is outside declared schema")
        return DuckQueryTool(self.database) if self.engine == "duckdb" else QueryTool(self.database)

    def verify(self, task, answer):
        return dict(passed=valid_answer(answer) and answer == task.expected,
                    reason="independent raw-Parquet reference; exact hour counts and total")


@dataclass
class DuckQueryTool:
    database: str
    max_seconds: float = 10.0

    def execute(self, action, sql=None, workers=1):
        import duckdb

        if workers != 1 or action not in {"schema", "query"} or (action == "schema" and sql is not None):
            raise ValueError("use one-worker schema or query(sql)")
        if action == "query" and (not isinstance(sql, str) or not sql.strip() or len(sql.encode()) > 32768):
            raise ValueError("query must be nonempty SQL up to 32768 bytes")
        started, cpu = time.monotonic_ns(), time.process_time_ns()
        db = duckdb.connect(self.database, read_only=True, config={
            "threads": 1, "memory_limit": "512MB", "max_temp_directory_size": "0B",
            "enable_external_access": False, "autoload_known_extensions": False,
            "autoinstall_known_extensions": False,
        })
        timer = threading.Timer(self.max_seconds, db.interrupt)
        timer.start()
        try:
            if action == "schema":
                payload = {"tables": {name: [dict(name=r[0], type=r[1]) for r in db.execute(f"DESCRIBE {name}").fetchall()] for name in ("trips", "zones")}}
            else:
                statements = db.extract_statements(sql)
                if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
                    raise ValueError("only one SELECT statement is allowed")
                result = db.execute(sql)
                rows = result.fetchmany(129)
                # Timestamps from exploratory queries use ISO-like strings.
                rows = [[v.isoformat(sep=" ") if isinstance(v, datetime) else v for v in row] for row in rows]
                payload = dict(columns=[c[0] for c in result.description], rows=rows[:128], truncated=len(rows)>128)
                if len(json.dumps(payload, allow_nan=False).encode()) > 65536:
                    raise ValueError("query result exceeds 65536 bytes; aggregate or select fewer columns")
            payload["tool_accounting"] = dict(elapsed_ns=time.monotonic_ns()-started, cpu_ns=time.process_time_ns()-cpu,
                                              duckdb=duckdb.__version__, workers=1, memory_limit="512MB", spill_limit="0B")
            return payload
        finally:
            timer.cancel()
            timer.join()
            db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Offline preparation of the pinned TLC query task; no model or energy run")
    parser.add_argument("--trips", required=True)
    parser.add_argument("--zones", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.trips, args.zones, args.output), indent=2))
