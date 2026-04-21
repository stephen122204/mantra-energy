#!/usr/bin/env python3
"""
================================================================================
scripts/etl/duration_fix_etl.py
================================================================================
PURPOSE:
    Backfills and computes task_duration_ns, framework_overhead_ns,
    pre_task_energy_uj, pre_task_duration_ns, energy_sample_coverage_pct,
    and avg_task_power_watts for all runs.

COMPLETE TIME/ENERGY MODEL:
    ┌──────────────────────────────────────────────────────────────┐
    │ Window      │ Time                 │ Energy                  │
    ├──────────────────────────────────────────────────────────────┤
    │ pre_task    │ pre_task_duration_ns │ pre_task_energy_uj      │
    │             │ (t_pre → t0)         │ (rapl_before → start)   │
    ├──────────────────────────────────────────────────────────────┤
    │ task        │ task_duration_ns     │ pkg_energy_uj (PRIMARY) │
    │             │ (t0 → t1)            │ (rapl_start → end)      │
    ├──────────────────────────────────────────────────────────────┤
    │ framework   │ framework_ovhd_ns    │ not measured (future)   │
    │             │ (t1 → t2)            │                         │
    └──────────────────────────────────────────────────────────────┘

HISTORICAL BACKFILL STRATEGY:
    For pre-v9 runs, rapl_before_pretask was not captured.
    So pre_task_energy_uj = NULL for all historical runs.
    task_duration_ns estimated from energy_samples span (error <1%).
    All historical runs: duration_includes_overhead = 1.

PLATFORM COMPLIANCE (PAC):
    rapl.read_energy() returns None on macOS/ARM/fallback.
    pre_task_energy_uj = NULL on non-RAPL platforms — graceful degradation.
    task_duration_ns and framework_overhead_ns use perf_counter — all platforms.

AUTHOR: Deepak Panigrahy
================================================================================
"""

import logging
import sqlite3
import sys
from pathlib import Path
import threading

logger = logging.getLogger(__name__)

DEFAULT_DB = Path("data/experiments.db")

# Coverage quality thresholds
COVERAGE_GOLD       = 95.0
COVERAGE_ACCEPTABLE = 80.0


def _compute_pre_task_energy(
    rapl_before: dict | None,
    rapl_start:  dict | None,
) -> int | None:
    """
    Compute pre-task window energy from two RAPL snapshots.

    Formula: E_pre_task = rapl_before["package-0"] - rapl_start["package-0"]

    Note: RAPL is a cumulative counter. rapl_before < rapl_start always
    (time moves forward). If rapl_before > rapl_start, counter wrapped
    — return None (invalid).

    Args:
        rapl_before: Dict from rapl.read_energy() before pre-task reads.
                     Keys: "package-0", "core", "dram", "uncore".
        rapl_start:  Dict from rapl.read_energy() inside start_measurement().

    Returns:
        pre_task_energy_uj as int, or None if unavailable/invalid.
    """
    if not rapl_before or not rapl_start:
        return None

    # Use package-0 as the primary domain
    before_pkg = rapl_before.get("package-0") or rapl_before.get("package")
    start_pkg  = rapl_start.get("package-0")  or rapl_start.get("package")

    if before_pkg is None or start_pkg is None:
        return None

    delta = start_pkg - before_pkg
    if delta < 0:
        # RAPL counter wrapped — cannot compute reliably
        logger.warning("RAPL counter wrap detected in pre-task window")
        return None

    return int(delta)


def _fix_run(cursor: sqlite3.Cursor, run_id: int) -> dict | None:
    """
    Compute all corrected duration and energy metrics for a single run.

    For new runs (post-v9): values come from result dict stored in DB.
    For historical runs: task_duration estimated from energy_samples span.

    Args:
        cursor: Open DB cursor.
        run_id: Target run.

    Returns:
        Dict of UPDATE values, or None if insufficient data.
    """
    # Fetch run row
    cursor.execute("""
        SELECT run_id, start_time_ns, end_time_ns, duration_ns,
               pkg_energy_uj, workflow_type,
               task_duration_ns, pre_task_energy_uj
        FROM runs WHERE run_id = ?
    """, (run_id,))
    row = cursor.fetchone()
    if not row:
        logger.warning("Run %d not found", run_id)
        return None

    (run_id, start_ns, end_ns, old_duration_ns,
     pkg_uj, wf_type, existing_task_dur, existing_pre) = row

    if not start_ns or not end_ns:
        logger.warning("Run %d missing start/end timestamps", run_id)
        return None

    # Get energy_samples span — proxy for task end time (t1)
    cursor.execute("""
        SELECT MIN(sample_start_ns) AS first_ns,
               MAX(sample_end_ns)   AS last_ns,
               COUNT(*)             AS sample_count,
               MIN(timestamp_ns)    AS first_ts,
               MAX(timestamp_ns)    AS last_ts
        FROM energy_samples
        WHERE run_id = ?
    """, (run_id,))
    es = cursor.fetchone()

    if not es or es[2] == 0:
        logger.warning("Run %d has no energy_samples — skipping", run_id)
        return None

    # sample_start_ns/end_ns only populated post-Chunk2.
    # Fall back to timestamp_ns for pre-Chunk2 historical runs.
    first_sample_ns = es[0] if es[0] is not None else es[3]
    last_sample_ns  = es[1] if es[1] is not None else es[4]
    sample_count    = es[2]

    if first_sample_ns is None or last_sample_ns is None:
        logger.warning("Run %d has no usable sample timestamps — skipping", run_id)
        return None

    # t0 = start_ns (run_start_perf anchor)
    # t1 ≈ last_sample_ns (energy sampler stops at executor return)
    # t2 = end_ns (run_end_perf anchor)
    # For new runs (post-v9), task_duration_ns is already correctly set
    # from harness perf_counter — use it as-is, only estimate for historical.

    if existing_task_dur:
        # New run — use harness-measured value, derive others
        task_duration_ns      = existing_task_dur
        total_run_duration_ns = max(0, end_ns - start_ns)
        framework_overhead_ns = max(0, total_run_duration_ns - task_duration_ns)
    else:
        # Historical run — estimate from energy_samples span
        task_duration_ns      = max(0, last_sample_ns - start_ns)
        framework_overhead_ns = max(0, end_ns - last_sample_ns)
        total_run_duration_ns = max(0, end_ns - start_ns)

    # Coverage: sample span / task duration
    sample_span_ns = last_sample_ns - first_sample_ns
    coverage_pct = (
        round(sample_span_ns / task_duration_ns * 100, 2)
        if task_duration_ns > 0 else 0.0
    )

    # Corrected average power (task duration only)
    avg_task_power_watts = (
        round(pkg_uj / (task_duration_ns / 1e9) / 1e6, 4)
        if task_duration_ns > 0 and pkg_uj else None
    )

    # pre_task_energy: NULL for historical runs (rapl_before not captured)
    # Will be populated for new runs via experiment_runner result dict
    pre_task_energy_uj   = existing_pre   # preserve if already set
    pre_task_duration_ns = None           # not recoverable for historical runs

    return {
        "run_id":                     run_id,
        "task_duration_ns":           task_duration_ns,
        "framework_overhead_ns":      framework_overhead_ns,
        "total_run_duration_ns":      total_run_duration_ns,
        "duration_includes_overhead": 1,    # all backfilled runs are historical
        "energy_sample_coverage_pct": coverage_pct,
        "avg_task_power_watts":       avg_task_power_watts,
        "pre_task_energy_uj":         pre_task_energy_uj,
        "pre_task_duration_ns":       pre_task_duration_ns,
    }


def fix_run(run_id: int, db_path: Path = DEFAULT_DB) -> bool:
    """
    Compute and write corrected duration metrics for a single run.

    Args:
        run_id:  Target run_id.
        db_path: Path to SQLite DB.

    Returns:
        True on success, False on failure.
    """
    if not db_path.exists():
        logger.error("DB not found: %s", db_path)
        return False

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        data = _fix_run(cursor, run_id)
        if not data:
            return False

        cursor.execute("""
            UPDATE runs SET
                task_duration_ns           = :task_duration_ns,
                framework_overhead_ns      = :framework_overhead_ns,
                total_run_duration_ns      = :total_run_duration_ns,
                duration_includes_overhead = :duration_includes_overhead,
                energy_sample_coverage_pct = :energy_sample_coverage_pct,
                avg_task_power_watts       = :avg_task_power_watts,
                pre_task_energy_uj         = :pre_task_energy_uj,
                pre_task_duration_ns       = :pre_task_duration_ns
            WHERE run_id = :run_id
        """, data)

        conn.commit()
        logger.info(
            "Run %d | task=%dms framework=%dms coverage=%.1f%% "
            "power=%.3fW pre_task=%s",
            run_id,
            (data["task_duration_ns"] or 0) // 1_000_000,
            (data["framework_overhead_ns"] or 0) // 1_000_000,
            data["energy_sample_coverage_pct"] or 0,
            data["avg_task_power_watts"] or 0,
            f"{data['pre_task_energy_uj']}µJ"
            if data["pre_task_energy_uj"] is not None else "NULL(historical)",
        )
        return True

    except Exception as exc:
        logger.error("Duration fix failed for run %d: %s", run_id, exc)
        conn.rollback()
        return False
    finally:
        conn.close()


def fix_run_with_pretask(
    run_id: int,
    rapl_before_pretask: dict | None,
    pre_task_duration_sec: float,
    db_path: Path = DEFAULT_DB,
) -> bool:
    """
    Called by experiment_runner for NEW runs (post-v9).
    Stores pre_task_energy_uj from live RAPL capture.

    The rapl_start value is read from energy_attribution table
    (stored there by the attribution ETL from raw_energy.rapl_start).

    Args:
        run_id:               Target run_id.
        rapl_before_pretask:  Dict from rapl.read_energy() before pre-task reads.
                              None on non-RAPL platforms.
        pre_task_duration_sec: Seconds from _pre_task_start_perf to run_start_perf.
        db_path:              Path to SQLite DB.

    Returns:
        True on success, False on failure.
    """
    if not db_path.exists():
        logger.error("DB not found: %s", db_path)
        return False

    # First run the standard backfill for task/framework duration
    ok = fix_run(run_id, db_path)
    if not ok:
        return False

    if rapl_before_pretask is None:
        # Non-RAPL platform — pre_task_energy stays NULL
        logger.debug("Run %d: non-RAPL platform, pre_task_energy=NULL", run_id)
        return True

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()

        # Get rapl_start from energy_samples first timestamp
        # rapl_start = RAPL value at start_measurement() call
        # We approximate from first energy_sample pkg_start_uj
        cursor.execute("""
            SELECT pkg_start_uj
            FROM energy_samples
            WHERE run_id = ?
            ORDER BY sample_start_ns ASC
            LIMIT 1
        """, (run_id,))
        row = cursor.fetchone()
        if not row:
            logger.warning("Run %d: no energy_samples for pre_task calc", run_id)
            return True

        # rapl_start pkg value (µJ)
        rapl_start_pkg = row[0]
        rapl_before_pkg = (
            rapl_before_pretask.get("package-0")
            or rapl_before_pretask.get("package")
        )

        if rapl_before_pkg is None or rapl_start_pkg is None:
            return True

        pre_task_energy_uj = max(0, int(rapl_start_pkg - rapl_before_pkg))
        pre_task_duration_ns = int(pre_task_duration_sec * 1e9)

        cursor.execute("""
            UPDATE runs SET
                pre_task_energy_uj   = ?,
                pre_task_duration_ns = ?,
                duration_includes_overhead = 0
            WHERE run_id = ?
        """, (pre_task_energy_uj, pre_task_duration_ns, run_id))

        conn.commit()
        logger.info(
            "Run %d | pre_task_energy=%dµJ pre_task_duration=%dms",
            run_id, pre_task_energy_uj, pre_task_duration_ns // 1_000_000,
        )
        return True

    except Exception as exc:
        logger.error("Pre-task energy fix failed for run %d: %s", run_id, exc)
        conn.rollback()
        return False
    finally:
        conn.close()


def backfill_all(db_path: Path = DEFAULT_DB) -> None:
    """
    Backfill duration fix for all existing runs.
    pre_task_energy_uj = NULL for all historical runs (not measurable retroactively).
    """
    if not db_path.exists():
        logger.error("DB not found: %s", db_path)
        return

    conn = sqlite3.connect(str(db_path))
    try:
        runs = conn.execute(
            "SELECT run_id FROM runs ORDER BY run_id"
        ).fetchall()
    finally:
        conn.close()

    total = len(runs)
    passed = failed = 0

    logger.info("Backfilling duration fix for %d runs...", total)
    for (run_id,) in runs:
        ok = fix_run(run_id, db_path)
        if ok:
            passed += 1
        else:
            failed += 1

    # Coverage distribution report
    conn = sqlite3.connect(str(db_path))
    try:
        dist = conn.execute("""
            SELECT
                COUNT(CASE WHEN energy_sample_coverage_pct >= 95 THEN 1 END)  AS gold,
                COUNT(CASE WHEN energy_sample_coverage_pct >= 80
                            AND energy_sample_coverage_pct < 95 THEN 1 END)   AS ok,
                COUNT(CASE WHEN energy_sample_coverage_pct < 80
                            AND energy_sample_coverage_pct IS NOT NULL
                           THEN 1 END)                                         AS poor,
                ROUND(AVG(energy_sample_coverage_pct), 2)                     AS avg_pct,
                ROUND(AVG(framework_overhead_ns) / 1e6, 1)                    AS avg_fw_ms,
                COUNT(CASE WHEN pre_task_energy_uj IS NOT NULL THEN 1 END)    AS has_pretask
            FROM runs
        """).fetchone()
        logger.info(
            "Coverage — gold(≥95%%): %d | ok(80-95%%): %d | poor(<80%%): %d "
            "| avg: %.1f%% | avg_framework: %.1fms | with_pretask: %d",
            dist[0], dist[1], dist[2],
            dist[3] or 0, dist[4] or 0, dist[5],
        )
    finally:
        conn.close()

    logger.info("Backfill done — %d/%d ok, %d failed", passed, total, failed)


def duration_fix_async(
    run_id: int,
    rapl_before_pretask: dict | None = None,
    pre_task_duration_sec: float = 0.0,
    db_path: Path = DEFAULT_DB,
) -> None:
    """
    Non-blocking thread — replaces async def which was never awaited.
    Args:
        run_id: run to fix
        rapl_before_pretask: RAPL snapshot before pre-task window (optional)
        pre_task_duration_sec: pre-task window duration in seconds
        db_path: database path
    """
    if rapl_before_pretask is not None:
        target, args = fix_run_with_pretask, (run_id, rapl_before_pretask, pre_task_duration_sec, db_path)
    else:
        target, args = fix_run, (run_id, db_path)
    threading.Thread(target=target, args=args, daemon=True).start()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    if "--backfill-all" in sys.argv:
        backfill_all()
    elif "--run-id" in sys.argv:
        idx = sys.argv.index("--run-id")
        try:
            rid = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            print("Usage: python duration_fix_etl.py --run-id <id>")
            sys.exit(1)
        ok = fix_run(rid)
        sys.exit(0 if ok else 1)
    else:
        print("Usage:")
        print("  python scripts/etl/duration_fix_etl.py --run-id <id>")
        print("  python scripts/etl/duration_fix_etl.py --backfill-all")
        sys.exit(1)
