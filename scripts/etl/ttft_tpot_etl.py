"""
ETL: Populate runs.ttft_ms and runs.tpot_ms from llm_interactions.

Called synchronously from experiment_runner.py after each run completes.
Follows same pattern as phase_attribution_etl.py — opens own DB connection.

Usage from experiment_runner:
    from scripts.etl.ttft_tpot_etl import populate_run as populate_ttft_tpot
    populate_ttft_tpot(run_id)

CLI:
    python scripts/etl/ttft_tpot_etl.py --run-id 1833
    python scripts/etl/ttft_tpot_etl.py --backfill-all
"""

import argparse
import logging
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH   = str(REPO_ROOT / "data" / "experiments.db")

logger = logging.getLogger(__name__)


def _conn() -> sqlite3.Connection:
    """Open DB connection — same pattern as other ETLs."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _compute_prefill_energy(conn, run_id: int, first_token_time_ns: int, request_start_ns: int) -> int:
    """
    Sum pkg RAPL energy during prefill window (request_start to first_token).
    Uses energy_samples table — sample_start_ns/sample_end_ns overlap window.
    """
    row = conn.execute("""
        SELECT SUM(pkg_end_uj - pkg_start_uj)
        FROM energy_samples
        WHERE run_id = ?
          AND sample_end_ns   <= ?
    """, (run_id, first_token_time_ns)).fetchone()

    return row[0] if row and row[0] else 0

def populate_run(run_id: int) -> bool:
    """
    Compute and write for a single run:
      - avg ttft_ms / tpot_ms into runs table
      - prefill_energy_uj into llm_interactions rows
    All streaming interactions processed in one connection.
    Args:
        run_id: target run_id
    Returns:
        True if streaming data found and written, False otherwise
    """
    conn = _conn()
    try:
        # ── 1. prefill_energy_uj per interaction ──────────────────────────
        interactions = conn.execute("""
            SELECT interaction_id, first_token_time_ns
            FROM llm_interactions
            WHERE run_id              = ?
              AND streaming_enabled   = 1
              AND first_token_time_ns IS NOT NULL
              AND prefill_energy_uj   IS NULL
        """, (run_id,)).fetchall()
        for row in interactions:
            energy = _compute_prefill_energy(
                conn, run_id, row["first_token_time_ns"], 0
            )
            conn.execute("""
                UPDATE llm_interactions
                SET prefill_energy_uj = ?
                WHERE interaction_id  = ?
            """, (energy, row["interaction_id"]))

        # ── 2. avg ttft_ms / tpot_ms into runs ───────────────────────────
        row = conn.execute("""
            SELECT
                AVG(ttft_ms) AS avg_ttft,
                AVG(tpot_ms) AS avg_tpot
            FROM llm_interactions
            WHERE run_id            = ?
              AND streaming_enabled = 1
              AND ttft_ms           IS NOT NULL
              AND tpot_ms           IS NOT NULL
        """, (run_id,)).fetchone()
        if not row or row["avg_ttft"] is None:
            logger.debug("run_id=%s: no streaming data, skipping", run_id)
            conn.commit()
            return False
        conn.execute("""
            UPDATE runs
            SET ttft_ms = ?,
                tpot_ms = ?
            WHERE run_id = ?
        """, (row["avg_ttft"], row["avg_tpot"], run_id))
        conn.commit()
        logger.info("run_id=%s  ttft_ms=%.2f ms  tpot_ms=%.4f ms",
                    run_id, row["avg_ttft"], row["avg_tpot"])
        return True
    finally:
        conn.close()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Populate runs.ttft_ms / tpot_ms")
    parser.add_argument("--run-id",       type=int, help="single run to process")
    parser.add_argument("--backfill-all", action="store_true", help="all runs missing values")
    args = parser.parse_args()

    if args.run_id:
        populate_run(args.run_id)
    elif args.backfill_all:
        conn = _conn()
        # Step 1: write prefill_energy_uj for all streaming interactions
        interactions = conn.execute("""
            SELECT li.interaction_id, li.run_id, li.first_token_time_ns
            FROM llm_interactions li
            WHERE li.streaming_enabled    = 1
              AND li.first_token_time_ns  IS NOT NULL
              AND li.prefill_energy_uj    IS NULL
        """).fetchall()
        for row in interactions:
            energy = _compute_prefill_energy(
                conn, row["run_id"], row["first_token_time_ns"], 0
            )
            conn.execute("""
                UPDATE llm_interactions
                SET prefill_energy_uj = ?
                WHERE interaction_id  = ?
            """, (energy, row["interaction_id"]))
        conn.commit()

        # Step 2: update ttft_ms / tpot_ms averages in runs table
        run_ids = conn.execute("""
            SELECT DISTINCT run_id FROM runs WHERE ttft_ms IS NULL
        """).fetchall()
        conn.close()
        updated = sum(populate_run(r["run_id"]) for r in run_ids)
        logger.info("Backfill complete — %d runs updated", updated)
    else:
        conn = _conn()
        row = conn.execute("SELECT MAX(run_id) FROM runs").fetchone()
        conn.close()
        if row and row[0]:
            populate_run(row[0])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
