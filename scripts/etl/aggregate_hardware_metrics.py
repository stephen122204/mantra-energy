"""
Hardware metrics aggregation ETL.

Aggregates cpu_samples, io_samples, thermal_samples into 7 run-level
columns on the runs table. Called async after every run.

Run manually:
    python scripts/etl/aggregate_hardware_metrics.py --run-id <id>
    python scripts/etl/aggregate_hardware_metrics.py --backfill-all
"""

import sqlite3
import threading
import argparse

DB_PATH = "data/experiments.db"


def _conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def aggregate_hardware_metrics(run_id: int, db_path: str = DB_PATH) -> dict:
    """
    Aggregate hardware sample tables into runs table for one run.

    Columns updated:
        l1d_cache_misses_total  = SUM(cpu_samples.l1d_cache_misses)
        l2_cache_misses_total   = SUM(cpu_samples.l2_cache_misses)
        l3_cache_hits_total     = SUM(cpu_samples.l3_cache_hits)
        l3_cache_misses_total   = SUM(cpu_samples.l3_cache_misses)
        disk_read_bytes_total   = SUM(io_samples.disk_read_bytes)
        disk_write_bytes_total  = SUM(io_samples.disk_write_bytes)
        voltage_vcore_avg       = AVG(thermal_samples.voltage_vcore)
    """
    conn = _conn(db_path)

    row = conn.execute("""
        SELECT
            (SELECT SUM(l1d_cache_misses) FROM cpu_samples     WHERE run_id=?) as l1d,
            (SELECT SUM(l2_cache_misses)  FROM cpu_samples     WHERE run_id=?) as l2,
            (SELECT SUM(l3_cache_hits)    FROM cpu_samples     WHERE run_id=?) as l3h,
            (SELECT SUM(l3_cache_misses)  FROM cpu_samples     WHERE run_id=?) as l3m,
            (SELECT SUM(disk_read_bytes)  FROM io_samples      WHERE run_id=?) as dr,
            (SELECT SUM(disk_write_bytes) FROM io_samples      WHERE run_id=?) as dw,
            (SELECT AVG(voltage_vcore)    FROM thermal_samples WHERE run_id=?) as vcore
    """, (run_id,)*7).fetchone()

    conn.execute("""
        UPDATE runs SET
            l1d_cache_misses_total = ?,
            l2_cache_misses_total  = ?,
            l3_cache_hits_total    = ?,
            l3_cache_misses_total  = ?,
            disk_read_bytes_total  = ?,
            disk_write_bytes_total = ?,
            voltage_vcore_avg      = ?
        WHERE run_id = ?
    """, (row["l1d"], row["l2"], row["l3h"], row["l3m"],
          row["dr"],  row["dw"], row["vcore"], run_id))

    conn.commit()
    conn.close()

    return {
        "l1d_cache_misses_total":  row["l1d"],
        "l2_cache_misses_total":   row["l2"],
        "l3_cache_hits_total":     row["l3h"],
        "l3_cache_misses_total":   row["l3m"],
        "disk_read_bytes_total":   row["dr"],
        "disk_write_bytes_total":  row["dw"],
        "voltage_vcore_avg":       row["vcore"],
    }


def aggregate_async(run_id: int, db_path: str = DB_PATH) -> None:
    """Non-blocking background thread — called from experiment_runner."""
    t = threading.Thread(
        target=aggregate_hardware_metrics,
        args=(run_id, db_path),
        daemon=True,
    )
    t.start()


def backfill_all(db_path: str = DB_PATH) -> None:
    """Backfill all existing runs."""
    conn = _conn(db_path)
    runs = conn.execute("SELECT run_id FROM runs ORDER BY run_id").fetchall()
    conn.close()
    print(f"Backfilling {len(runs)} runs...")
    for row in runs:
        result = aggregate_hardware_metrics(row["run_id"], db_path)
        print(f"  run {row['run_id']}: {result}")
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hardware metrics aggregation ETL")
    parser.add_argument("--run-id",       type=int, help="Single run")
    parser.add_argument("--backfill-all", action="store_true")
    parser.add_argument("--db",           default=DB_PATH)
    args = parser.parse_args()

    if args.backfill_all:
        backfill_all(args.db)
    elif args.run_id:
        print(aggregate_hardware_metrics(args.run_id, args.db))
    else:
        parser.print_help()
