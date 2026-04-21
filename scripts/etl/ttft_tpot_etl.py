"""
ETL: Populate runs.ttft_ms and runs.tpot_ms from llm_interactions.

Called synchronously from experiment_runner.py after each run completes.
Averages ttft_ms and tpot_ms across all streaming interactions for the run.
Non-streaming interactions (streaming_enabled=0) are excluded — SQLite
AVG() ignores NULL values automatically.

Usage from experiment_runner:
    from scripts.etl.ttft_tpot_etl import populate_run as populate_ttft_tpot
    populate_ttft_tpot(self.db.conn, run_id)

CLI backfill:
    python scripts/etl/ttft_tpot_etl.py --run-id 1833
    python scripts/etl/ttft_tpot_etl.py --backfill-all
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH   = REPO_ROOT / "data" / "experiments.db"

logger = logging.getLogger(__name__)


def populate_run(conn: sqlite3.Connection, run_id: int) -> bool:
    """
    Compute and write avg ttft_ms and tpot_ms for a single run.

    Reads from llm_interactions, writes to runs in the same transaction.
    Called synchronously — no async, no subprocess.

    Args:
        conn:   open sqlite3 connection (from caller — not opened here)
        run_id: target run_id to update

    Returns:
        True if values written, False if no streaming data for this run
    """
    row = conn.execute("""
        SELECT
            AVG(ttft_ms)  AS avg_ttft,
            AVG(tpot_ms)  AS avg_tpot
        FROM llm_interactions
        WHERE run_id           = ?
          AND streaming_enabled = 1
          AND ttft_ms           IS NOT NULL
          AND tpot_ms           IS NOT NULL
    """, (run_id,)).fetchone()

    if not row or row[0] is None:
        # No streaming interactions for this run — leave NULL, not an error
        logger.debug("run_id=%s: no streaming interactions, ttft/tpot left NULL", run_id)
        return False

    conn.execute("""
        UPDATE runs
        SET ttft_ms = ?,
            tpot_ms = ?
        WHERE run_id = ?
    """, (row[0], row[1], run_id))
    conn.commit()
    logger.info("run_id=%s  ttft_ms=%.2f ms  tpot_ms=%.4f ms", run_id, row[0], row[1])
    return True


def main() -> None:
    """CLI entry point for manual or backfill runs."""
    parser = argparse.ArgumentParser(description="Populate runs.ttft_ms / tpot_ms")
    parser.add_argument("--run-id",       type=int, help="single run to process")
    parser.add_argument("--backfill-all", action="store_true", help="all runs missing values")
    parser.add_argument("--db",           default=str(DB_PATH))
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)

    if args.run_id:
        populate_run(conn, args.run_id)
    elif args.backfill_all:
        rows = conn.execute("""
            SELECT DISTINCT r.run_id
            FROM runs r
            JOIN llm_interactions li ON li.run_id = r.run_id
            WHERE r.ttft_ms IS NULL
              AND li.streaming_enabled = 1
              AND li.ttft_ms IS NOT NULL
        """).fetchall()
        updated = sum(populate_run(conn, r[0]) for r in rows)
        logger.info("Backfill complete — %d runs updated", updated)
    else:
        row = conn.execute("SELECT MAX(run_id) FROM runs").fetchone()
        if row and row[0]:
            populate_run(conn, row[0])

    conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
