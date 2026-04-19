"""
Phase Attribution ETL v1 — Normalized CPU-signal weighting.

Formula (guaranteed accounting closure):
    score_i     = cpu_fraction_i x raw_energy_i          (signal per phase)
    weight_i    = score_i / sum(scores)                   (normalized share)
    E_phase_i   = weight_i x attributed_energy_uj         (allocated from run total)

Guarantee: sum(E_phase_i) == attributed_energy_uj (rounding residual added to largest phase)

Data sources:
    raw_energy      : energy_samples  MAX(pkg_end_uj) - MIN(pkg_start_uj)
    cpu_fraction    : interrupt_samples MAX(proc_ticks) - MIN / MAX(total_ticks) - MIN
    run_attributed  : runs.attributed_energy_uj

Run modes:
    Async per-run : process_run_async(run_id)        called from experiment_runner
    Manual        : python scripts/etl/phase_attribution_etl.py --run-id <id>
    Backfill      : python scripts/etl/phase_attribution_etl.py --backfill-all
"""

import sqlite3
import threading
import argparse

DB_PATH = "data/experiments.db"
PHASES  = ("planning", "execution", "synthesis")


def _conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _get_phases(conn, run_id: int) -> list:
    return conn.execute("""
        SELECT event_id, phase, start_time_ns, end_time_ns
        FROM orchestration_events
        WHERE run_id = ? AND phase IN ('planning','execution','synthesis')
        ORDER BY start_time_ns
    """, (run_id,)).fetchall()


def _raw_phase_energy(conn, run_id: int, start_ns: int, end_ns: int, dynamic_energy: int) -> tuple:
    """
    MAX(pkg_end_uj) - MIN(pkg_start_uj) within phase window.
    Capped at dynamic_energy to avoid physics violations.
    Returns (energy_uj, sample_count).
    """
    row = conn.execute("""
        SELECT MIN(pkg_start_uj) as min_start,
               MAX(pkg_end_uj)   as max_end,
               COUNT(*)          as n
        FROM energy_samples
        WHERE run_id = ? AND sample_start_ns >= ? AND sample_end_ns <= ?
    """, (run_id, start_ns, end_ns)).fetchone()

    if not row or row["min_start"] is None:
        return 0, 0
    raw = max(0, row["max_end"] - row["min_start"])
    if dynamic_energy > 0:
        raw = min(raw, dynamic_energy)   # cap at run dynamic energy
    return raw, row["n"]


def _phase_cpu_fraction(conn, run_id: int, start_ns: int, end_ns: int) -> tuple:
    """
    Counter delta method — MAX-MIN, not AVG.
    Returns (cpu_fraction, proc_min, proc_max, total_min, total_max).
    cpu_fraction is None when insufficient data.
    """
    row = conn.execute("""
        SELECT MIN(proc_ticks_start)  as proc_min,
               MAX(proc_ticks_end)    as proc_max,
               MIN(total_ticks_start) as total_min,
               MAX(total_ticks_end)   as total_max
        FROM interrupt_samples
        WHERE run_id = ? AND sample_start_ns >= ? AND sample_end_ns <= ?
    """, (run_id, start_ns, end_ns)).fetchone()

    if not row or row["proc_min"] is None or row["total_min"] is None:
        return None, 0, 0, 0, 0

    proc_delta  = row["proc_max"]  - row["proc_min"]
    total_delta = row["total_max"] - row["total_min"]

    if total_delta <= 0:
        return None, row["proc_min"], row["proc_max"], row["total_min"], row["total_max"]

    frac = max(0.0, min(1.0, proc_delta / total_delta))
    return frac, row["proc_min"], row["proc_max"], row["total_min"], row["total_max"]


def _fallback_fraction(conn, run_id: int) -> float:
    """Run-level cpu_fraction fallback when phase ticks unavailable."""
    row = conn.execute(
        "SELECT cpu_fraction FROM runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    if not row or row["cpu_fraction"] is None:
        return 0.0
    return row["cpu_fraction"]


def compute_phase_attribution(run_id: int, db_path: str = DB_PATH) -> dict:
    """
    Compute normalized phase attribution for one run.

    Normalizes phase scores so planning + execution + synthesis == attributed_energy_uj.
    Updates orchestration_events and runs tables atomically.
    """
    conn = _conn(db_path)
    phases = _get_phases(conn, run_id)

    if not phases:
        conn.close()
        return {"error": f"no phases for run {run_id}"}

    # Get run-level values
    run_row = conn.execute(
        "SELECT attributed_energy_uj, dynamic_energy_uj FROM runs WHERE run_id=?",
        (run_id,)
    ).fetchone()

    if not run_row:
        conn.close()
        return {"error": f"run {run_id} not found"}

    run_attributed = run_row["attributed_energy_uj"] or 0
    dynamic_energy = run_row["dynamic_energy_uj"]    or 0

    # Step 1: compute per-phase scores and metadata
    phase_data = {}
    for phase in phases:
        start_ns = phase["start_time_ns"]
        end_ns   = phase["end_time_ns"]

        raw_energy, sample_count = _raw_phase_energy(
            conn, run_id, start_ns, end_ns, dynamic_energy
        )
        cpu_frac, proc_min, proc_max, total_min, total_max = _phase_cpu_fraction(
            conn, run_id, start_ns, end_ns
        )

        if cpu_frac is None:
            cpu_frac = _fallback_fraction(conn, run_id)
            method   = "fallback_run_level"
            quality  = 0.3
        else:
            method  = "cpu_counter_delta"
            quality = min(1.0, sample_count / 10) if sample_count > 0 else 0.5

        # signal = cpu_fraction x raw_energy (unnormalized weight)
        score = cpu_frac * raw_energy

        phase_data[phase["event_id"]] = {
            "phase":      phase["phase"],
            "raw_energy": raw_energy,
            "cpu_frac":   cpu_frac,
            "score":      score,
            "method":     method,
            "quality":    quality,
            "proc_min":   proc_min,
            "proc_max":   proc_max,
            "total_min":  total_min,
            "total_max":  total_max,
        }

    # Step 2: normalize scores → weights → allocated energies
    total_score = sum(d["score"] for d in phase_data.values())
    phase_totals = {p: 0 for p in PHASES}
    allocated    = {}

    for event_id, d in phase_data.items():
        if total_score > 0:
            attributed = int((d["score"] / total_score) * run_attributed)
        else:
            attributed = 0
        allocated[event_id] = attributed
        phase_totals[d["phase"]] = phase_totals.get(d["phase"], 0) + attributed

    # Step 3: rounding residual → add to phase with largest score
    total_allocated = sum(allocated.values())
    residual = run_attributed - total_allocated
    if residual != 0 and phase_data:
        largest_id = max(phase_data, key=lambda k: phase_data[k]["score"])
        allocated[largest_id]              += residual
        phase_totals[phase_data[largest_id]["phase"]] += residual

    # Step 4: write orchestration_events
    for event_id, d in phase_data.items():
        conn.execute("""
            UPDATE orchestration_events
            SET raw_energy_uj         = ?,
                cpu_fraction_per_phase = ?,
                attributed_energy_uj   = ?,
                attribution_method     = ?,
                quality_score          = ?,
                proc_ticks_min         = ?,
                proc_ticks_max         = ?,
                total_ticks_min        = ?,
                total_ticks_max        = ?
            WHERE event_id = ?
        """, (d["raw_energy"], d["cpu_frac"], allocated[event_id],
              d["method"], d["quality"],
              d["proc_min"], d["proc_max"], d["total_min"], d["total_max"],
              event_id))

    # Step 5: write runs table
    conn.execute("""
        UPDATE runs
        SET planning_energy_uj  = ?,
            execution_energy_uj = ?,
            synthesis_energy_uj = ?
        WHERE run_id = ?
    """, (phase_totals["planning"], phase_totals["execution"],
          phase_totals["synthesis"], run_id))

    conn.commit()
    conn.close()
    return phase_totals


def process_run_async(run_id: int, db_path: str = DB_PATH) -> None:
    """Non-blocking background thread — called from experiment_runner after save_pair."""
    t = threading.Thread(
        target=compute_phase_attribution,
        args=(run_id, db_path),
        daemon=True,
    )
    t.start()


def backfill_all(db_path: str = DB_PATH) -> None:
    """One-time backfill for all existing agentic runs."""
    conn = _conn(db_path)
    runs = conn.execute(
        "SELECT run_id FROM runs WHERE workflow_type='agentic' ORDER BY run_id"
    ).fetchall()
    conn.close()
    print(f"Backfilling {len(runs)} agentic runs...")
    for row in runs:
        result = compute_phase_attribution(row["run_id"], db_path)
        print(f"  run {row['run_id']}: {result}")
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase attribution ETL")
    parser.add_argument("--run-id",       type=int, help="Process single run")
    parser.add_argument("--backfill-all", action="store_true")
    parser.add_argument("--db",           default=DB_PATH)
    args = parser.parse_args()

    if args.backfill_all:
        backfill_all(args.db)
    elif args.run_id:
        print(compute_phase_attribution(args.run_id, args.db))
    else:
        parser.print_help()
