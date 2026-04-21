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

import asyncio
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Default DB path — overridable for testing
DEFAULT_DB = Path("data/experiments.db")

# Thermal throttle threshold in Celsius
THERMAL_THRESHOLD_C = 85.0

# Thermal penalty fraction applied to throttled energy
THERMAL_PENALTY_FRACTION = 0.20

# Attribution model version — bump when formula changes
ATTRIBUTION_MODEL_VERSION = "v1"


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

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
        SELECT phase, SUM(event_energy_uj) AS energy
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


def _compute_attribution(run: dict, cursor: sqlite3.Cursor) -> dict:
    """
    Core attribution model v1. Computes all L0–L5 values.

    Args:
        run:    Full runs row as dict.
        cursor: Open DB cursor for sub-queries.

    Returns:
        Dict of all energy_attribution column values.
    """
    run_id = run["run_id"]

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
    api_latency_ms = _get_api_latency_ms(cursor, run_id)
    llm_wait_frac  = min(1.0, api_latency_ms / duration_ms) if duration_ms > 0 else 0.0
    compute_frac   = min(1.0, compute_ms / duration_ms)     if duration_ms > 0 else 0.0
    # Clamp so fractions don't exceed 1.0 together
    if llm_wait_frac + compute_frac > 1.0:
        compute_frac = max(0.0, 1.0 - llm_wait_frac)
 
    llm_wait_uj    = int(attributed * llm_wait_frac)   # L4a: LLM API blocked
    application_uj = int(attributed * compute_frac)    # L4b: active CPU compute

    # ── L3: Orchestration — everything attributed but not pure compute ────────
    # ── L3: Orchestration — attributed energy minus LLM wait and compute ──────
    # Represents pure framework overhead: tool dispatch, planning, synthesis
    orchestration_uj = max(0, attributed - llm_wait_uj - application_uj)

    # ── L2: Resource contention (time-fraction INFERRED) ─────────────────────
    network_wait_ms = _get_network_wait_ms(cursor, run_id)
    io_wait_ms      = _get_io_wait_ms(cursor, run_id)

    # Energy proportional to fraction of total time spent waiting
    # non_local_ms = TCP round-trip only (distinct from api_latency which includes inference)
    network_wait_uj = int((network_wait_ms / duration_ms) * attributed) if duration_ms > 0 else 0    
    io_wait_uj      = int((io_wait_ms      / duration_ms) * pkg) if duration_ms > 0 else 0

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
        "tool_energy_uj":                  None,   # Chunk 8
        "retry_energy_uj":                 None,   # Chunk 8
        "failed_tool_energy_uj":           None,   # Chunk 8
        "rejected_generation_energy_uj":   None,   # Chunk 8
        # L4
        "llm_wait_energy_uj":              llm_wait_uj,
        "llm_compute_energy_uj":           application_uj,
        "attribution_method":              "cpu_fraction_v1",
        "ml_model_version":                None,   # Chunk 1.2: ARM ML estimator        
        "prefill_energy_uj":               None,   # Chunk 4 TTFT
        "decode_energy_uj":                None,   # Chunk 4 TTFT
        # L5
        "energy_per_completion_token_uj":  energy_per_token_uj,
        "energy_per_successful_step_uj":   energy_per_step_uj,
        "energy_per_accepted_answer_uj":   None,   # Chunk 8
        "energy_per_solved_task_uj":       None,   # Chunk 8
        # Thermal
        "thermal_penalty_energy_uj":       thermal_penalty_uj,
        "thermal_penalty_time_ms":         thermal_ms,
        # Residual + quality
        "unattributed_energy_uj":          unattributed_uj,
        "attribution_coverage_pct":        coverage_pct,
        "attribution_model_version":       ATTRIBUTION_MODEL_VERSION,
        "updated_at":                      datetime.now().isoformat(),
    }


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

        data = _compute_attribution(run, cursor)

        # INSERT OR REPLACE handles both first-time insert and ETL re-runs
        cursor.execute("""
            INSERT OR REPLACE INTO energy_attribution (
                run_id,
                pkg_energy_uj, core_energy_uj, dram_energy_uj, uncore_energy_uj,
                background_energy_uj, interrupt_energy_uj, scheduler_energy_uj,
                llm_wait_energy_uj, network_wait_energy_uj, io_wait_energy_uj, disk_energy_uj,
                memory_pressure_energy_uj, cache_dram_energy_uj,
                orchestration_energy_uj, planning_energy_uj, execution_energy_uj,
                synthesis_energy_uj, tool_energy_uj, retry_energy_uj,
                failed_tool_energy_uj, rejected_generation_energy_uj,
                llm_compute_energy_uj, prefill_energy_uj, decode_energy_uj,
                energy_per_completion_token_uj, energy_per_successful_step_uj,
                energy_per_accepted_answer_uj, energy_per_solved_task_uj,
                thermal_penalty_energy_uj, thermal_penalty_time_ms,
                unattributed_energy_uj, attribution_coverage_pct,
                attribution_model_version, updated_at
            ) VALUES (
                :run_id,
                :pkg_energy_uj, :core_energy_uj, :dram_energy_uj, :uncore_energy_uj,
                :background_energy_uj, :interrupt_energy_uj, :scheduler_energy_uj,
                :llm_wait_energy_uj, :network_wait_energy_uj, :io_wait_energy_uj, :disk_energy_uj,
                :memory_pressure_energy_uj, :cache_dram_energy_uj,
                :orchestration_energy_uj, :planning_energy_uj, :execution_energy_uj,
                :synthesis_energy_uj, :tool_energy_uj, :retry_energy_uj,
                :failed_tool_energy_uj, :rejected_generation_energy_uj,
                :llm_compute_energy_uj, :prefill_energy_uj, :decode_energy_uj,
                :energy_per_completion_token_uj, :energy_per_successful_step_uj,
                :energy_per_accepted_answer_uj, :energy_per_solved_task_uj,
                :thermal_penalty_energy_uj, :thermal_penalty_time_ms,
                :unattributed_energy_uj, :attribution_coverage_pct,
                :attribution_model_version, :updated_at
            )
        """, data)

        conn.commit()
        logger.info(
            "Attribution v1 complete — run %d | coverage=%.1f%% | unattributed=%d µJ",
            run_id,
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


async def attribution_async(run_id: int, db_path: Path = DEFAULT_DB) -> None:
    """
    Async wrapper for use in experiment_runner.py save_pair().
    Runs attribution in executor to avoid blocking the event loop.

    Usage in experiment_runner.py:
        from scripts.etl.energy_attribution_etl import attribution_async
        attribution_async(agentic_id)
        attribution_async(linear_id)
    """
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        compute_energy_attribution,
        run_id,
        db_path,
    )


# =============================================================================
# CLI
# =============================================================================

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
            print("Usage: python energy_attribution_etl.py --run-id <id>")
            sys.exit(1)
        ok = compute_energy_attribution(rid)
        sys.exit(0 if ok else 1)
    else:
        print("Usage:")
        print("  python scripts/etl/energy_attribution_etl.py --run-id <id>")
        print("  python scripts/etl/energy_attribution_etl.py --backfill-all")
        sys.exit(1)
