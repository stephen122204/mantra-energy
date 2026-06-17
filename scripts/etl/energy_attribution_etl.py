#!/usr/bin/env python3
"""
================================================================================
scripts/etl/energy_attribution_etl.py
================================================================================
PURPOSE:
    Computes and inserts the full multi-layer energy attribution for every run
    into the energy_attribution table.

    This ETL runs automatically after save_pair() completes, in parallel with
    phase_attribution_etl.py and aggregate_hardware_metrics.py.

ATTRIBUTION MODEL v1 — Layer Decomposition:
    L0 Hardware:   raw RAPL domain readings (pkg, core, dram, uncore)
    L1 System:     background energy not attributable to workload
    L2 Resource:   I/O, network, memory pressure (time-fraction INFERRED)
    L3 Workflow:   orchestration phases, tools, retries
    L4 Model:      LLM compute fraction
    L5 Outcome:    energy per token / step / answer

FORMULAS:
    ucr (utilisation compute ratio) = compute_time_ms / duration_ms
    application_energy = core × ucr
    orchestration_energy = attributed_energy - application_energy
    background = max(0, pkg - core - dram - orchestration
                        - application - network_wait - io_wait)
    unattributed = max(0, pkg - Σ all attributed layers)
    thermal_penalty = pkg × throttle_ratio × 0.20
        where throttle_ratio = Σ(interval_ns if temp>85) / Σ(interval_ns)

USAGE:
    # Single run
    python scripts/etl/energy_attribution_etl.py --run-id 1234

    # Backfill all existing runs
    python scripts/etl/energy_attribution_etl.py --backfill-all

    # Async call from experiment_runner.py
    from scripts.etl.energy_attribution_etl import attribution_async
    attribution_async(run_id)

AUTHOR: Deepak Panigrahy
================================================================================
"""

import threading
import asyncio
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
import importlib.util as _ilu
import os as _os
_llm_helper_path = _os.path.join(_os.path.dirname(__file__), "_llm_energy_from_samples.py")
_llm_spec = _ilu.spec_from_file_location("_llm_energy_from_samples", _llm_helper_path)
_llm_mod  = _ilu.module_from_spec(_llm_spec)
_llm_spec.loader.exec_module(_llm_mod)
get_llm_energy_from_samples = _llm_mod.get_llm_energy_from_samples

logger = logging.getLogger(__name__)

# Default DB path — overridable for testing
from scripts.tools.path_loader import get_alems_db_path
DB_PATH = get_alems_db_path()

# Thermal throttle threshold in Celsius
THERMAL_THRESHOLD_C = 85.0

# Thermal penalty fraction applied to throttled energy
THERMAL_PENALTY_FRACTION = 0.20

# Attribution model version — bump when formula changes
# Attribution model version — bump when formula changes
ATTRIBUTION_MODEL_VERSION = "v2"
 
# Minimum normalized score to count as an accepted answer
# Documented in: 19-hallucination-output-quality-methodology.md
# Method: output_quality_normalization_v1
ACCEPTANCE_THRESHOLD = 0.7  # output_quality_normalization_v1


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def populate_attribution_stubs(run_id: int, conn: sqlite3.Connection) -> bool:
    """
    Populate the 5 Chunk 8 stub columns in energy_attribution for one run.
    Also backfills hallucination_count, hallucination_rate, failed_tool_calls
    in normalization_factors.
 
    Called after goal_execution_etl completes for this run.
    Idempotent — safe to rerun (UPDATE not INSERT).
 
    Returns True on success, False if energy_attribution row missing.
    """
    # ── Invariant: energy_attribution row must exist ──────────────────────────
    ea_exists = conn.execute(
        "SELECT run_id FROM energy_attribution WHERE run_id = ?", (run_id,)
    ).fetchone()
 
    if ea_exists is None:
        logger.warning(
            "run_id=%d has no energy_attribution row — stub population skipped",
            run_id
        )
        return False
 
    # ── Get attempt_ids for this run ──────────────────────────────────────────
    attempt_ids = [
        r[0] for r in conn.execute(
            "SELECT attempt_id FROM goal_attempt WHERE run_id = ?", (run_id,)
        ).fetchall()
    ]
 
    if not attempt_ids:
        logger.debug("run_id=%d has no goal_attempt rows — stubs set to 0", run_id)
        attempt_ids = []
 
    placeholders = ",".join("?" * len(attempt_ids)) if attempt_ids else "NULL"
 
    # ── retry_energy_uj ───────────────────────────────────────────────────────
    # Energy spent on non-first attempts (attempt_number > 1) = retry cost
    retry_energy = 0
    if attempt_ids:
        row = conn.execute(f"""
            SELECT COALESCE(SUM(energy_uj), 0)
            FROM goal_attempt
            WHERE run_id = ? AND attempt_number > 1
        """, (run_id,)).fetchone()
        retry_energy = row[0] or 0
 
    # ── failed_tool_energy_uj ─────────────────────────────────────────────────
    failed_tool_energy = 0
    if attempt_ids:
        row = conn.execute(f"""
            SELECT COALESCE(SUM(wasted_energy_uj), 0)
            FROM tool_failure_events
            WHERE attempt_id IN ({placeholders})
        """, attempt_ids).fetchone()
        failed_tool_energy = row[0] or 0
 
    # ── rejected_generation_energy_uj ────────────────────────────────────────
    # Energy wasted on hallucinated outputs (uses REAL column for precision)
    rejected_energy = 0
    if attempt_ids:
        row = conn.execute(f"""
            SELECT COALESCE(SUM(wasted_energy_uj_real), 0)
            FROM hallucination_events
            WHERE attempt_id IN ({placeholders})
        """, attempt_ids).fetchone()
        rejected_energy = row[0] or 0
 
    # ── energy_per_accepted_answer_uj ────────────────────────────────────────
    # Total run energy / count of quality-passing answers
    # Accepted = normalized_score >= ACCEPTANCE_THRESHOLD and not needs_review
    energy_per_accepted = None
    if attempt_ids:
        pkg_row = conn.execute(
            "SELECT pkg_energy_uj FROM energy_attribution WHERE run_id = ?",
            (run_id,)
        ).fetchone()
        accepted_count_row = conn.execute(f"""
            SELECT COUNT(*)
            FROM output_quality
            WHERE attempt_id IN ({placeholders})
              AND normalized_score >= ?
              AND score_method != 'needs_review'
        """, (*attempt_ids, ACCEPTANCE_THRESHOLD)).fetchone()
 
        pkg_energy = pkg_row[0] if pkg_row else None
        accepted_count = accepted_count_row[0] if accepted_count_row else 0
 
        if pkg_energy and accepted_count > 0:
            energy_per_accepted = pkg_energy / accepted_count
 
    # ── energy_per_solved_task_uj ─────────────────────────────────────────────
    # Successful goal energy / count of solved goals for this run
    energy_per_solved = None
    solved_row = conn.execute("""
        SELECT COALESCE(SUM(successful_energy_uj), 0), COUNT(*)
        FROM goal_execution
        WHERE first_run_id = ? AND success = 1
    """, (run_id,)).fetchone()
 
    total_successful_energy = solved_row[0] or 0
    solved_count = solved_row[1] or 0
 
    if solved_count > 0 and total_successful_energy > 0:
        energy_per_solved = total_successful_energy / solved_count
 
    # ── UPDATE energy_attribution stubs ──────────────────────────────────────
    conn.execute("""
        UPDATE energy_attribution
        SET retry_energy_uj                = ?,
            failed_tool_energy_uj          = ?,
            rejected_generation_energy_uj  = ?,
            energy_per_accepted_answer_uj  = ?,
            energy_per_solved_task_uj      = ?
        WHERE run_id = ?
    """, (
        retry_energy,
        failed_tool_energy,
        rejected_energy,
        energy_per_accepted,
        energy_per_solved,
        run_id,
    ))
 
    # ── Backfill normalization_factors ────────────────────────────────────────
    halluc_count = 0
    failed_tool_count = 0
 
    if attempt_ids:
        h_row = conn.execute(f"""
            SELECT COUNT(*) FROM hallucination_events
            WHERE attempt_id IN ({placeholders})
        """, attempt_ids).fetchone()
        halluc_count = h_row[0] or 0
 
        t_row = conn.execute(f"""
            SELECT COUNT(*) FROM tool_failure_events
            WHERE attempt_id IN ({placeholders})
        """, attempt_ids).fetchone()
        failed_tool_count = t_row[0] or 0
 
    # hallucination_rate = hallucination_count / total_attempts for this run
    total_attempts_row = conn.execute(
        "SELECT COUNT(*) FROM goal_attempt WHERE run_id = ?", (run_id,)
    ).fetchone()
    total_attempts = total_attempts_row[0] or 0
    halluc_rate = (halluc_count / total_attempts) if total_attempts > 0 else 0.0
 
    nf_exists = conn.execute(
        "SELECT run_id FROM normalization_factors WHERE run_id = ?", (run_id,)
    ).fetchone()
 
    if nf_exists:
        conn.execute("""
            UPDATE normalization_factors
            SET hallucination_count = ?,
                hallucination_rate  = ?,
                failed_tool_calls   = ?
            WHERE run_id = ?
        """, (halluc_count, halluc_rate, failed_tool_count, run_id))
    else:
        logger.warning(
            "run_id=%d has no normalization_factors row — skipping backfill",
            run_id
        )
 
    logger.debug(
        "run_id=%d stubs updated: retry=%.0f failed_tool=%.0f rejected=%.0f",
        run_id, retry_energy, failed_tool_energy, rejected_energy
    )
    return True
 
 
def backfill_attribution_stubs(db_path: str) -> None:
    """
    Backfill Chunk 8 stub columns for all runs where they are still NULL.
    Run after goal_execution_etl.py --backfill-all completes.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
 
    try:
        pending = conn.execute("""
            SELECT run_id FROM energy_attribution
            WHERE retry_energy_uj IS NULL
        """).fetchall()
 
        logger.info(
            "Backfilling Chunk 8 attribution stubs for %d runs", len(pending)
        )
 
        processed = 0
        failed = 0
        for row in pending:
            success = populate_attribution_stubs(row["run_id"], conn)
            if success:
                processed += 1
            else:
                failed += 1
 
        conn.commit()
        logger.info(
            "attribution stub backfill complete: processed=%d failed=%d",
            processed, failed
        )
 
    except Exception:
        conn.rollback()
        logger.exception("attribution stub backfill failed — rolled back")
        raise
    finally:
        conn.close()

def _get_run(cursor: sqlite3.Cursor, run_id: int) -> dict | None:
    """Fetch run row as dict. Returns None if run not found."""
    cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    row = cursor.fetchone()
    if not row:
        logger.warning("Run %d not found — skipping attribution", run_id)
        return None
    return dict(zip([c[0] for c in cursor.description], row))


def _get_phase_energy(cursor: sqlite3.Cursor, run_id: int) -> dict:
    """
    Fetch per-phase energy from orchestration_events.
    Returns dict keyed by phase name → total µJ.
    Falls back to runs.planning_energy_uj etc. if events table is empty.
    """
    cursor.execute("""
        SELECT phase, SUM(attributed_energy_uj) AS energy
        FROM orchestration_events
        WHERE run_id = ?
        GROUP BY phase
    """, (run_id,))
    phase_energy = {row[0]: row[1] or 0 for row in cursor.fetchall()}
    return phase_energy


def _get_network_wait_ms(cursor: sqlite3.Cursor, run_id: int) -> float:
    """
    Sum non_local_ms from llm_interactions — represents network round-trip
    latency not doing compute. Confirmed column: llm_interactions.non_local_ms.
    """
    cursor.execute("""
        SELECT COALESCE(SUM(non_local_ms), 0)
        FROM llm_interactions
        WHERE run_id = ?
    """, (run_id,))
    row = cursor.fetchone()
    return float(row[0]) if row else 0.0

def _get_network_wait_energy_uj(
    cursor: sqlite3.Cursor,
    run_id: int,
    cpu_fraction: float,
) -> int:
    """
    Measure energy during network wait windows using direct RAPL sample slice.
 
    Uses request_start_ns → first_token_time_ns as the wait window per
    llm_interaction. Slices energy_samples directly — MEASURED not MODELED.
 
    Falls back to time-fraction if timestamps unavailable (pre-migration-038 runs).
 
    Args:
        cursor:       Open DB cursor.
        run_id:       runs.run_id.
        cpu_fraction: Process CPU fraction for attribution.
 
    Returns:
        Energy in µJ attributed to network wait windows.
    """
    # Primary: RAPL slice over [request_start_ns → first_token_time_ns] windows
    # These windows represent pure network wait — CPU≈0 but pkg non-zero
    cursor.execute("""
        SELECT request_start_ns, first_token_time_ns
        FROM llm_interactions
        WHERE run_id = ?
          AND request_start_ns IS NOT NULL
          AND first_token_time_ns IS NOT NULL
          AND non_local_ms > 0
        ORDER BY request_start_ns
    """, (run_id,))
    windows = cursor.fetchall()
 
    if windows:
        # Direct RAPL slice — sum sample deltas within each wait window
        total_uj = 0
        for (start_ns, end_ns) in windows:
            if end_ns <= start_ns:
                continue
            cursor.execute("""
                SELECT COALESCE(SUM(pkg_energy_uj), 0) AS window_energy,
                       COUNT(*) AS n_samples
                FROM (
                    SELECT (e1.pkg_energy_uj - e2.pkg_energy_uj) AS pkg_energy_uj
                    FROM energy_samples e1
                    JOIN energy_samples e2
                      ON e1.run_id = e2.run_id
                     AND e1.sample_id = e2.sample_id + 1
                    WHERE e1.run_id = ?
                      AND e1.timestamp_ns >= ?
                      AND e1.timestamp_ns <= ?
                      AND e1.pkg_energy_uj > e2.pkg_energy_uj
                )
            """, (run_id, start_ns, end_ns))
            row = cursor.fetchone()
            if row and row[0]:
                # Apply cpu_fraction to attribute to this process
                total_uj += int(row[0] * cpu_fraction)
        if total_uj > 0:
            logger.debug(
                "network_wait: run=%d RAPL slice %d windows → %dµJ",
                run_id, len(windows), total_uj,
            )
            return total_uj
 
    # Fallback: time-fraction when timestamps unavailable (pre-migration-038)
    cursor.execute("""
        SELECT COALESCE(SUM(non_local_ms), 0),
               COALESCE(SUM(api_latency_ms), 1)
        FROM llm_interactions WHERE run_id = ?
    """, (run_id,))
    row = cursor.fetchone()
    non_local_ms = float(row[0]) if row else 0.0
 
    if non_local_ms <= 0:
        return 0
 
    # Time-fraction fallback — less accurate, documented in attribution_method
    cursor.execute(
        "SELECT task_duration_ns, attributed_energy_uj FROM runs WHERE run_id = ?",
        (run_id,)
    )
    run_row = cursor.fetchone()
    if not run_row or not run_row[1]:
        return 0
    duration_ms = (run_row[0] or 0) / 1e6
    attributed = run_row[1]
    if duration_ms <= 0:
        return 0
    result = int((non_local_ms / duration_ms) * attributed)
    logger.debug(
        "network_wait: run=%d time-fraction fallback %dms/%dms → %dµJ",
        run_id, non_local_ms, duration_ms, result,
    )
    return result

def _get_api_latency_ms(cursor: sqlite3.Cursor, run_id: int) -> float:
    """Sum api_latency_ms from llm_interactions — full LLM response wait time."""
    cursor.execute("SELECT COALESCE(SUM(api_latency_ms), 0) FROM llm_interactions WHERE run_id = ?", (run_id,))
    row = cursor.fetchone()
    return float(row[0]) if row else 0.0



def _get_io_wait_ms(cursor: sqlite3.Cursor, run_id: int) -> float:
    """
    Sum io_block_time_ms from io_samples — time process was blocked on I/O.
    Confirmed column: io_samples.io_block_time_ms.
    """
    cursor.execute("""
        SELECT COALESCE(SUM(io_block_time_ms), 0)
        FROM io_samples
        WHERE run_id = ?
    """, (run_id,))
    row = cursor.fetchone()
    return float(row[0]) if row else 0.0
def _get_io_wait_energy_uj(
    cursor: sqlite3.Cursor,
    run_id: int,
    attributed: int,
    duration_ms: float,
) -> int:
    """
    Measure energy during IO wait periods.
 
    Uses io_samples.io_block_time_ms as time fraction of attributed energy.
    Base is attributed_energy_uj (not pkg — BUG-E2 fix).
 
    Args:
        cursor:       Open DB cursor.
        run_id:       runs.run_id.
        attributed:   attributed_energy_uj from runs table.
        duration_ms:  task_duration_ns / 1e6.
 
    Returns:
        Energy in µJ attributed to IO wait periods.
    """
    cursor.execute("""
        SELECT COALESCE(SUM(io_block_time_ms), 0)
        FROM io_samples
        WHERE run_id = ?
    """, (run_id,))
    row = cursor.fetchone()
    io_wait_ms = float(row[0]) if row else 0.0
 
    if io_wait_ms <= 0 or duration_ms <= 0 or not attributed:
        return 0
 
    # Time-fraction against attributed (not pkg — BUG-E2 fix)
    result = int((io_wait_ms / duration_ms) * attributed)
    logger.debug(
        "io_wait: run=%d %dms/%dms × %dµJ → %dµJ",
        run_id, io_wait_ms, duration_ms, attributed, result,
    )
    return result

def _get_thermal_penalty(
    cursor: sqlite3.Cursor,
    run_id: int,
    pkg_energy_uj: int,
) -> tuple[int, float]:
    """
    Compute time-weighted thermal penalty.

    Only intervals where cpu_temp > THERMAL_THRESHOLD_C contribute.
    Formula:
        throttle_ratio = Σ(sample_end_ns - sample_start_ns | temp > threshold)
                       / Σ(sample_end_ns - sample_start_ns)
        penalty_uj = pkg × throttle_ratio × THERMAL_PENALTY_FRACTION

    Returns:
        (penalty_uj: int, throttled_ms: float)
    """
    cursor.execute("""
        SELECT
            COALESCE(SUM(
                CASE WHEN cpu_temp > ?
                THEN (sample_end_ns - sample_start_ns)
                ELSE 0 END
            ), 0) AS throttle_ns,
            COALESCE(SUM(sample_end_ns - sample_start_ns), 1) AS total_ns
        FROM thermal_samples
        WHERE run_id = ?
    """, (THERMAL_THRESHOLD_C, run_id))

    row = cursor.fetchone()
    if not row or row[1] == 0:
        return 0, 0.0

    throttle_ns = float(row[0])
    total_ns = float(row[1])
    throttle_ratio = throttle_ns / total_ns

    penalty_uj = int(pkg_energy_uj * throttle_ratio * THERMAL_PENALTY_FRACTION)
    throttled_ms = throttle_ns / 1e6  # ns → ms

    return penalty_uj, throttled_ms


def _get_cache_dram_energy(
    cursor: sqlite3.Cursor,
    run_id: int,
    dram_energy_uj: int,
) -> int:
    """
    Estimate DRAM energy attributable to cache misses.
    Formula: dram_energy × (l3_misses / (l3_hits + l3_misses))
    Uses aggregate columns from runs table (populated by Chunk 12 ETL).
    Returns 0 if cache counter data unavailable.
    """
    cursor.execute("""
        SELECT l3_cache_hits_total, l3_cache_misses_total
        FROM runs WHERE run_id = ?
    """, (run_id,))
    row = cursor.fetchone()
    if not row:
        return 0

    hits = row[0] or 0
    misses = row[1] or 0
    total = hits + misses

    if total == 0:
        # l1d_cache_misses = 0 on this ThinkPad PMU — expected behaviour
        return 0

    miss_ratio = misses / total
    return int(dram_energy_uj * miss_ratio)

def _compute_tool_energy(run_id: int, cursor: sqlite3.Cursor) -> int:
    """
    Compute tool_energy_uj by slicing RAPL energy_samples within each
    tool_call orchestration event window, scaled by cpu_fraction.
 
    Method: MEASURED — direct sample integration, same as phase_attribution v2.
    cpu_fraction sourced from energy_attribution row (populated earlier in
    compute_energy_attribution before this function is called via INSERT OR REPLACE).
    Falls back to runs.cpu_fraction if energy_attribution not yet written.
    Returns 0 if no tool events or insufficient samples.
    """
    # cpu_fraction from runs table — always available at ETL time
    frac_row = cursor.execute(
        "SELECT cpu_fraction FROM runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    if not frac_row or not frac_row[0]:
        logger.debug("_compute_tool_energy: no cpu_fraction for run_id=%d — skipping", run_id)
        return 0
 
    cpu_fraction = frac_row[0]
 
    # All tool_call events with valid time windows for this run
    tool_events = cursor.execute("""
        SELECT start_time_ns, end_time_ns
        FROM orchestration_events
        WHERE run_id = ?
          AND event_type = 'tool_call'
          AND start_time_ns IS NOT NULL
          AND end_time_ns IS NOT NULL
          AND end_time_ns > start_time_ns
    """, (run_id,)).fetchall()
 
    if not tool_events:
        logger.debug("_compute_tool_energy: no tool_call events for run_id=%d", run_id)
        return 0
 
    # Load all samples once — cumulative RAPL counters, delta between adjacent
    samples = cursor.execute("""
        SELECT timestamp_ns, pkg_energy_uj
        FROM energy_samples
        WHERE run_id = ?
          AND pkg_energy_uj IS NOT NULL
        ORDER BY timestamp_ns ASC
    """, (run_id,)).fetchall()
 
    if len(samples) < 2:
        logger.debug("_compute_tool_energy: insufficient samples for run_id=%d", run_id)
        return 0
 
    total_tool_uj = 0.0
    for start_ns, end_ns in tool_events:
        prev_e = None
        for ts, e in samples:
            if ts < start_ns:
                prev_e = e  # last sample before window
                continue
            if ts > end_ns:
                break
            if prev_e is not None:
                delta = e - prev_e
                if delta > 0:  # guard against RAPL counter wrap
                    total_tool_uj += delta * cpu_fraction
            prev_e = e
 
    result = int(total_tool_uj)

    if result == 0:
        # Fallback: sample window too short for delta computation (tool < 1 sample interval).
        # Use time-fraction method: (tool_cpu_time_ns / run_duration_ns) × attributed_energy_uj
        # Method: INFERRED — less accurate than MEASURED but honest for short tool calls.
        tool_ns_row = cursor.execute("""
            SELECT COALESCE(SUM(oe.tool_cpu_time_ns), 0),
                   r.duration_ns,
                   r.attributed_energy_uj
            FROM orchestration_events oe
            JOIN runs r ON r.run_id = oe.run_id
            WHERE oe.run_id = ?
              AND oe.event_type = 'tool_call'
              AND oe.tool_cpu_time_ns IS NOT NULL
        """, (run_id,)).fetchone()
        if tool_ns_row and tool_ns_row[1] and tool_ns_row[2]:
            tool_ns, duration_ns, attributed_uj = tool_ns_row
            if duration_ns > 0 and tool_ns > 0:
                result = int((tool_ns / duration_ns) * attributed_uj)
                logger.debug(
                    "_compute_tool_energy: run_id=%d fallback time-fraction "
                    "tool_ns=%d duration_ns=%d attributed_uj=%d → %d µJ",
                    run_id, tool_ns, duration_ns, attributed_uj, result
                )

    logger.debug(
        "_compute_tool_energy: run_id=%d events=%d tool_energy_uj=%d",
        run_id, len(tool_events), result
    )
    return result
 
def _compute_attribution(run: dict, cursor: sqlite3.Cursor, conn: sqlite3.Connection) -> dict:
    """
    Core attribution model v1. Computes all L0–L5 values including
    goal_attempt aggregations (retry, failed_tool, rejected_generation,
    energy_per_accepted_answer, energy_per_solved_task).
 
    Args:
        run:    Full runs row as dict.
        cursor: Open DB cursor for RAPL/sample sub-queries.
        conn:   Open DB connection for goal_attempt aggregation queries.
 
    Returns:
        Dict of all energy_attribution column values.
    """
    run_id = run["run_id"]
 
    # ── goal_attempt aggregations (require conn for multi-row queries) ────────
    attempt_ids = [
        r[0] for r in conn.execute(
            "SELECT attempt_id FROM goal_attempt WHERE run_id = ?", (run_id,)
        ).fetchall()
    ]
    placeholders = ",".join("?" * len(attempt_ids)) if attempt_ids else "NULL"
 
    # retry_energy_uj: energy on non-first attempts = wasted retry cost
    retry_energy = 0
    if attempt_ids:
        row = conn.execute(
            "SELECT COALESCE(SUM(energy_uj), 0) FROM goal_attempt "
            "WHERE run_id = ? AND attempt_number > 1", (run_id,)
        ).fetchone()
        retry_energy = row[0] or 0
 
    # failed_tool_energy_uj: wasted energy from tool failures this run
    failed_tool_energy = 0
    if attempt_ids:
        row = conn.execute(
            f"SELECT COALESCE(SUM(wasted_energy_uj), 0) "
            f"FROM tool_failure_events WHERE attempt_id IN ({placeholders})",
            attempt_ids
        ).fetchone()
        failed_tool_energy = row[0] or 0
 
    # rejected_generation_energy_uj: energy on hallucinated outputs
    rejected_energy = 0
    if attempt_ids:
        row = conn.execute(
            f"SELECT COALESCE(SUM(wasted_energy_uj_real), 0) "
            f"FROM hallucination_events WHERE attempt_id IN ({placeholders})",
            attempt_ids
        ).fetchone()
        rejected_energy = row[0] or 0
 
    # energy_per_accepted_answer_uj: pkg energy / accepted answer count
    # accepted = normalized_score >= threshold and not needs_review
    energy_per_accepted = None
    if attempt_ids:
        pkg_row = conn.execute(
            "SELECT pkg_energy_uj FROM energy_attribution WHERE run_id = ?",
            (run_id,)
        ).fetchone()
        accepted_row = conn.execute(
            f"SELECT COUNT(*) FROM output_quality "
            f"WHERE attempt_id IN ({placeholders}) "
            f"AND normalized_score >= ? AND score_method != 'needs_review'",
            (*attempt_ids, ACCEPTANCE_THRESHOLD)
        ).fetchone()
        pkg_energy = pkg_row[0] if pkg_row else None
        accepted_count = accepted_row[0] if accepted_row else 0
        if pkg_energy and accepted_count > 0:
            energy_per_accepted = pkg_energy / accepted_count
 
    # energy_per_solved_task_uj: successful goal energy / solved goal count
    energy_per_solved = None
    solved_row = conn.execute(
        "SELECT COALESCE(SUM(successful_energy_uj), 0), COUNT(*) "
        "FROM goal_execution WHERE first_run_id = ? AND success = 1",
        (run_id,)
    ).fetchone()
    if solved_row and solved_row[1] > 0 and solved_row[0] > 0:
        energy_per_solved = solved_row[0] / solved_row[1]

    # ── L0: Hardware — direct from runs RAPL columns ─────────────────────────
    pkg    = int(run.get("pkg_energy_uj")   or 0)
    core   = int(run.get("core_energy_uj")  or 0)
    dram   = int(run.get("dram_energy_uj")  or 0)
    uncore = int(run.get("uncore_energy_uj") or 0)

# REPLACE WITH:
    # ── Time fractions for energy split ──────────────────────────────────────
    # Use task_duration_ns (corrected, Chunk 6 fix) as denominator
    duration_ms = (run.get("task_duration_ns") or run.get("duration_ns") or 1) / 1e6
    compute_ms  = float(run.get("compute_time_ms") or 0)
 
    # ── cpu_fraction: workload share of total CPU ticks (from Chunk 3) ───────
    cpu_fraction = float(run.get("cpu_fraction") or 0.0)
 
    # ── attributed energy: fraction of dynamic energy belonging to workload ──
    # Already computed at capture time: cpu_fraction × dynamic_energy_uj
    attributed = int(run.get("attributed_energy_uj") or pkg)
    
 
    # ── LLM API wait energy (novel finding) ──────────────────────────────────
    # api_latency_ms = total time blocked waiting for LLM API responses
    # This energy is real (process alive, ~12.9W) but not CPU compute
    # Provision: attribution_method field allows future ML model override
    # ── L4/L5: LLM energy from RAPL samples (v2 — MEASURED not INFERRED) ────
    # Uses llm_interactions.first_token_time_ns and last_token_time_ns to
    # slice energy_samples into prefill (compute) and decode (wait) windows.
    # For local models: api_latency_ms=0 but timestamps exist — correctly
    # measures decode energy that time-fraction missed entirely.
    # Fallback to time-fraction when timestamps NULL (older runs).
    api_latency_ms = _get_api_latency_ms(cursor, run_id)
    provider       = run.get("provider")
    llm_energy = get_llm_energy_from_samples(
        cursor         = cursor,
        run_id         = run_id,
        attributed     = attributed,
        cpu_fraction   = cpu_fraction,
        duration_ms    = duration_ms,
        api_latency_ms = api_latency_ms,
        compute_ms     = compute_ms,
        provider       = provider,
    )
    llm_wait_uj       = llm_energy["llm_wait_uj"]
    application_uj    = llm_energy["llm_compute_uj"]
    orchestration_uj  = llm_energy["orchestration_uj"]
    inter_phase_uj        = int(run.get("inter_phase_energy_uj") or 0)
    attribution_method_v2 = llm_energy["attribution_method"]

    # ── L2: Resource contention (time-fraction INFERRED) ─────────────────────
    network_wait_ms = _get_network_wait_ms(cursor, run_id)
    io_wait_ms      = _get_io_wait_ms(cursor, run_id)

    # network_wait: RAPL slice over [request_start_ns → first_token_time_ns]
    # Falls back to time-fraction if timestamps unavailable (pre-migration-038)
    network_wait_uj = _get_network_wait_energy_uj(cursor, run_id, cpu_fraction)
 
    # io_wait: time-fraction against attributed (not pkg — BUG-E2 fix)
    io_wait_uj = _get_io_wait_energy_uj(cursor, run_id, attributed, duration_ms)

    # Memory pressure: page_faults × 10µJ constant (INFERRED heuristic)
    # 10µJ = empirical cost of TLB miss + page fill on x86 at 3GHz
    page_faults        = int(run.get("minor_page_faults") or 0)
    memory_pressure_uj = page_faults * 10  # µJ per fault

    # Cache/DRAM attributable energy
    cache_dram_uj = _get_cache_dram_energy(cursor, run_id, dram)

    # Disk energy: proportional to bytes transferred vs capacity proxy
    # Simple estimate: disk_read+write bytes × 0.1 µJ/KB (INFERRED)
    disk_read  = int(run.get("disk_read_bytes_total")  or 0)
    disk_write = int(run.get("disk_write_bytes_total") or 0)
    disk_uj    = int((disk_read + disk_write) / 1024 * 0.1)

    # ── L3: Phase energy — from orchestration_events (Chunk 5 ETL) ───────────
    phase_energy = _get_phase_energy(cursor, run_id)

    # Fall back to runs.planning_energy_uj if events table has no data
    planning_uj   = int(phase_energy.get("planning",   0)
                        or run.get("planning_energy_uj")   or 0)
    execution_uj  = int(phase_energy.get("execution",  0)
                        or run.get("execution_energy_uj")  or 0)
    synthesis_uj  = int(phase_energy.get("synthesis",  0)
                        or run.get("synthesis_energy_uj")  or 0)

    # ── L1: Background — idle system energy (from 2-sigma baseline protocol) ─
    # baseline_energy_uj already computed at capture time: P_idle_min × duration
    # dynamic_energy_uj = pkg - baseline (workload above idle)
    # background = dynamic energy NOT attributed to our process
    baseline_uj   = int(run.get("baseline_energy_uj")  or 0)
    dynamic_uj    = int(run.get("dynamic_energy_uj")   or 0)
    attributed_uj = int(run.get("attributed_energy_uj") or 0)
    background_uj = max(0, dynamic_uj - attributed_uj)

    # Interrupt and scheduler energy — INFERRED from rates
    # interrupt_energy ≈ interrupt_rate × 0.5µJ/interrupt × duration_s
    duration_s     = duration_ms / 1000.0
    interrupt_rate = float(run.get("interrupt_rate") or 0)
    interrupt_uj   = int(interrupt_rate * 0.5 * duration_s)

    ctx_switches   = int(run.get("total_context_switches") or 0)
    # Context switch cost ≈ 1µJ each (INFERRED — kernel + TLB flush)
    scheduler_uj   = ctx_switches * 1

    # ── Thermal penalty (time-weighted) ──────────────────────────────────────
    thermal_penalty_uj, thermal_ms = _get_thermal_penalty(cursor, run_id, pkg)

    # ── L5: Outcome normalisation ─────────────────────────────────────────────
    completion_tokens = int(run.get("completion_tokens") or 0)
    steps             = int(run.get("steps") or 0)

    energy_per_token_uj = (
        pkg / completion_tokens if completion_tokens > 0 else None
    )
    energy_per_step_uj = (
        pkg / steps if steps > 0 else None
    )

    # ── Residual: unattributed energy ────────────────────────────────────────
    # Sum of all explicitly attributed energy
    total_attributed = (
        core + dram + uncore
        + background_uj
        + network_wait_uj + io_wait_uj + disk_uj + memory_pressure_uj
        + llm_wait_uj
        + orchestration_uj
        + application_uj
        + thermal_penalty_uj
    )
    unattributed_uj = max(0, pkg - total_attributed)

    # Attribution coverage: % of pkg energy we can explain
    coverage_pct = (
        round((pkg - unattributed_uj) / pkg * 100, 2)
        if pkg > 0 else 0.0
    )

    return {
        "run_id":                          run_id,
        "attribution_method":              attribution_method_v2,
        "inter_phase_energy_uj":           inter_phase_uj,
        # L0
        "pkg_energy_uj":                   pkg,
        "core_energy_uj":                  core,
        "dram_energy_uj":                  dram,
        "uncore_energy_uj":                uncore,
        # L1
        "background_energy_uj":            background_uj,
        "interrupt_energy_uj":             interrupt_uj,
        "scheduler_energy_uj":             scheduler_uj,
        # L2
        "network_wait_energy_uj":          network_wait_uj,
        "io_wait_energy_uj":               io_wait_uj,
        "disk_energy_uj":                  disk_uj,
        "memory_pressure_energy_uj":       memory_pressure_uj,
        "cache_dram_energy_uj":            cache_dram_uj,
        # L3
        "orchestration_energy_uj":         orchestration_uj,
        "planning_energy_uj":              planning_uj,
        "execution_energy_uj":             execution_uj,
        "synthesis_energy_uj":             synthesis_uj,
        "tool_energy_uj":                  _compute_tool_energy(run_id, cursor),  # MEASURED: RAPL sample slice
        "retry_energy_uj":                 retry_energy,
        "failed_tool_energy_uj":           failed_tool_energy,
        "rejected_generation_energy_uj":   rejected_energy,
        # L4
        "llm_wait_energy_uj":              llm_wait_uj,
        "llm_compute_energy_uj":           application_uj,
        "ml_model_version":                None,   # Chunk 1.2: ARM ML estimator        
        "prefill_energy_uj":               None,   # Chunk 4 TTFT
        "decode_energy_uj":                None,   # Chunk 4 TTFT
        # L5
        "energy_per_completion_token_uj":  energy_per_token_uj,
        "energy_per_successful_step_uj":   energy_per_step_uj,
        "energy_per_accepted_answer_uj":   energy_per_accepted,
        "energy_per_solved_task_uj":       energy_per_solved,
        # Thermal
        "thermal_penalty_energy_uj":       thermal_penalty_uj,
        "thermal_penalty_time_ms":         thermal_ms,
        # Residual + quality
        "unattributed_energy_uj":          unattributed_uj,
        "attribution_coverage_pct":        coverage_pct,
        "attribution_model_version":       ATTRIBUTION_MODEL_VERSION,
        "updated_at":                      datetime.now().isoformat(),
    }


def populate_tool_failure_wasted_energy(run_id: int, db_path: Path = DEFAULT_DB) -> None:
    """
    Populate tool_failure_events.wasted_energy_uj from orchestration_events.
    Two strategies:
      1. Via orchestration_event_id FK if set (preferred)
      2. Via run_id join on goal_attempt — fallback when FK not set
    Must run after phase_attribution_etl so attributed_energy_uj is populated.
    Idempotent — safe to rerun.
    """
    if not db_path.exists():
        return
    conn = sqlite3.connect(str(db_path))
    try:
        # Strategy 1: via orchestration_event_id FK
        conn.execute("""
            UPDATE tool_failure_events
            SET wasted_energy_uj = (
                SELECT oe.attributed_energy_uj
                FROM orchestration_events oe
                WHERE oe.event_id = tool_failure_events.orchestration_event_id
            )
            WHERE orchestration_event_id IS NOT NULL
              AND wasted_energy_uj IS NULL
              AND attempt_id IN (
                SELECT ga.attempt_id FROM goal_attempt ga
                JOIN goal_execution ge ON ga.goal_id = ge.goal_id
                JOIN runs r ON r.run_id = ?
                WHERE ga.goal_id = ge.goal_id
              )
        """, (run_id,))

        # Strategy 2: via run_id join — fires when orchestration_event_id not set.
        # Sums attributed_energy_uj across execution-phase events for the attempt's
        # run. Conservative estimate: full execution phase energy attributed to failure.
        # Methodologically sound — execution phase IS where tool failures occur.
        conn.execute("""
            UPDATE tool_failure_events
            SET wasted_energy_uj = (
                SELECT COALESCE(SUM(oe.attributed_energy_uj), 0)
                FROM orchestration_events oe
                JOIN goal_attempt ga ON ga.run_id = oe.run_id
                                    AND ga.attempt_id = tool_failure_events.attempt_id
                WHERE oe.phase = 'execution'
            )
            WHERE orchestration_event_id IS NULL
              AND wasted_energy_uj IS NULL
              AND attempt_id IN (
                SELECT attempt_id FROM goal_attempt WHERE run_id = ?
              )
        """, (run_id,))
        # Strategy 3: use goal_attempt.energy_uj directly when run_id=-1
        # Injected failures abort before producing a run row — energy still captured in attempt
        conn.execute("""
            UPDATE tool_failure_events
            SET wasted_energy_uj = (
                SELECT ga.energy_uj
                FROM goal_attempt ga
                WHERE ga.attempt_id = tool_failure_events.attempt_id
                  AND ga.run_id = -1
                  AND ga.energy_uj IS NOT NULL
            )
            WHERE wasted_energy_uj IS NULL
              AND attempt_id IN (
                SELECT attempt_id FROM goal_attempt WHERE run_id = -1
              )
        """)
        conn.commit()
        logger.debug("populate_tool_failure_wasted_energy: run_id=%d done", run_id)
    except Exception as e:
        logger.warning("populate_tool_failure_wasted_energy failed run_id=%d: %s", run_id, e)
    finally:
        conn.close()
# =============================================================================
# PUBLIC API
# =============================================================================

def compute_energy_attribution(run_id: int, db_path: Path = DEFAULT_DB) -> bool:
    """
    Compute and upsert energy attribution for a single run.

    Args:
        run_id:  Target run_id from runs table.
        db_path: Path to SQLite database.

    Returns:
        True on success, False on failure.
    """
    if not db_path.exists():
        logger.error("DB not found: %s", db_path)
        return False

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.cursor()
        run = _get_run(cursor, run_id)
        if not run:
            return False

        data = _compute_attribution(run, cursor, conn)

        # INSERT OR REPLACE handles both first-time insert and ETL re-runs
        cursor.execute("""
            INSERT OR REPLACE INTO energy_attribution (
                run_id,
                pkg_energy_uj, core_energy_uj, dram_energy_uj, uncore_energy_uj,
                background_energy_uj, interrupt_energy_uj, scheduler_energy_uj,
                llm_wait_energy_uj, network_wait_energy_uj, io_wait_energy_uj, disk_energy_uj,
                memory_pressure_energy_uj, cache_dram_energy_uj,
                orchestration_energy_uj, planning_energy_uj, execution_energy_uj,
                synthesis_energy_uj, inter_phase_energy_uj, tool_energy_uj, retry_energy_uj,
                failed_tool_energy_uj, rejected_generation_energy_uj,
                llm_compute_energy_uj, prefill_energy_uj, decode_energy_uj,
                energy_per_completion_token_uj, energy_per_successful_step_uj,
                energy_per_accepted_answer_uj, energy_per_solved_task_uj,
                thermal_penalty_energy_uj, thermal_penalty_time_ms,
                unattributed_energy_uj, attribution_coverage_pct,
                attribution_method, attribution_model_version, updated_at
            ) VALUES (
                :run_id,
                :pkg_energy_uj, :core_energy_uj, :dram_energy_uj, :uncore_energy_uj,
                :background_energy_uj, :interrupt_energy_uj, :scheduler_energy_uj,
                :llm_wait_energy_uj, :network_wait_energy_uj, :io_wait_energy_uj, :disk_energy_uj,
                :memory_pressure_energy_uj, :cache_dram_energy_uj,
                :orchestration_energy_uj, :planning_energy_uj, :execution_energy_uj,
                :synthesis_energy_uj, :inter_phase_energy_uj, :tool_energy_uj, :retry_energy_uj,
                :failed_tool_energy_uj, :rejected_generation_energy_uj,
                :llm_compute_energy_uj, :prefill_energy_uj, :decode_energy_uj,
                :energy_per_completion_token_uj, :energy_per_successful_step_uj,
                :energy_per_accepted_answer_uj, :energy_per_solved_task_uj,
                :thermal_penalty_energy_uj, :thermal_penalty_time_ms,
                :unattributed_energy_uj, :attribution_coverage_pct,
                :attribution_method, :attribution_model_version, :updated_at
            )
        """, data)
        conn.commit()
        logger.info(
            "Attribution complete — run %d | method=%s | coverage=%.1f%% | unattributed=%d µJ",
            run_id,
            data["attribution_method"],
            data["attribution_coverage_pct"],
            data["unattributed_energy_uj"],
        )
        return True

    except Exception as exc:
        logger.error("Attribution ETL failed for run %d: %s", run_id, exc)
        conn.rollback()
        return False

    finally:
        conn.close()


def backfill_all(db_path: Path = DEFAULT_DB) -> None:
    """
    Backfill energy_attribution for all existing runs.
    Safe to re-run — uses INSERT OR REPLACE.
    """
    if not db_path.exists():
        logger.error("DB not found: %s", db_path)
        return

    conn = sqlite3.connect(str(db_path))
    try:
        runs = conn.execute("SELECT run_id FROM runs ORDER BY run_id").fetchall()
    finally:
        conn.close()

    total  = len(runs)
    passed = 0
    failed = 0

    logger.info("Backfilling attribution for %d runs...", total)
    for (run_id,) in runs:
        ok = compute_energy_attribution(run_id, db_path)
        if ok:
            passed += 1
        else:
            failed += 1

    logger.info(
        "Backfill complete — %d/%d succeeded, %d failed",
        passed, total, failed,
    )


def attribution_async(run_id: int, db_path: Path = DEFAULT_DB) -> None:
    """
    Non-blocking thread — replaces async def which was never awaited.
    Args:
        run_id: run to attribute
        db_path: database path
    """
    threading.Thread(target=compute_energy_attribution, args=(run_id, db_path), daemon=True).start()


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    if "--backfill-attribution" in sys.argv:
        db = DEFAULT_DB
        for i, arg in enumerate(sys.argv):
            if arg == "--db" and i + 1 < len(sys.argv):
                db = sys.argv[i + 1]
        backfill_attribution_stubs(str(db))
        sys.exit(0)
    elif "--backfill-all" in sys.argv:
        backfill_all()
    elif "--run-id" in sys.argv:
        idx = sys.argv.index("--run-id")
        try:
            rid = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            print("Usage: python energy_attribution_etl.py --run-id <id>")
            sys.exit(1)
        ok = compute_energy_attribution(rid)
        sys.exit(0 if ok else 1)
    else:
        print("Usage:")
        print("  python scripts/etl/energy_attribution_etl.py --run-id <id>")
        print("  python scripts/etl/energy_attribution_etl.py --backfill-all")
        print("  python scripts/etl/energy_attribution_etl.py --backfill-attribution")
        sys.exit(1)
