#!/usr/bin/env python3
"""
Backfill run_quality table for all existing runs.

Safe to re-run: uses INSERT OR REPLACE and skips runs already scored
(WHERE run_id NOT IN run_quality) by default. Pass --force to re-score all.

Usage:
    python scripts/etl/backfill_run_quality.py
    python scripts/etl/backfill_run_quality.py --db path/to/experiments.db
    python scripts/etl/backfill_run_quality.py --force
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

# Ensure repo root is on path so core imports resolve correctly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from core.utils.quality_scorer import QualityScorer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)


def backfill_all(db_path: str = "data/experiments.db", force: bool = False) -> int:
    """
    Score all unscored runs and insert into run_quality.

    Args:
        db_path: Path to SQLite database.
        force:   If True, re-score runs that already have a run_quality row.

    Returns:
        Number of runs processed.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row   # dict-style access by column name

    # Build query — LEFT JOIN gives us hardware_hash without crashing on NULL hw_id
    skip_clause = "" if force else "WHERE r.run_id NOT IN (SELECT run_id FROM run_quality)"
    query = f"""
        SELECT
            r.run_id,
            r.baseline_id,
            r.dynamic_energy_uj,
            r.duration_ns,
            r.max_temp_c,
            r.start_temp_c,
            r.background_cpu_percent,
            r.interrupts_per_second,
            r.energy_sample_coverage_pct,
            h.hardware_hash
        FROM runs r
        LEFT JOIN hardware_config h ON r.hw_id = h.hw_id
        {skip_clause}
    """

    runs = conn.execute(query).fetchall()
    logger.info("Found %d runs to score", len(runs))

    if not runs:
        logger.info("Nothing to do — all runs already scored. Use --force to re-score.")
        conn.close()
        return 0

    scorer = QualityScorer()
    updated = 0

    for run in runs:
        run_data = dict(run)
        # Runs with no hw_id get NULL hardware_hash — fall back to default profile
        hardware_hash = run_data.get("hardware_hash") or "default"

        valid, score, reason = scorer.compute(run_data, hardware_hash)

        conn.execute(
            """
            INSERT OR REPLACE INTO run_quality
                (run_id, experiment_valid, quality_score, rejection_reason, quality_version)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run["run_id"], valid, score, reason, scorer.VERSION),
        )

        updated += 1
        # Commit and log every 100 rows — avoids huge transactions on large DBs
        if updated % 100 == 0:
            conn.commit()
            logger.info("Processed %d / %d runs...", updated, len(runs))

    conn.commit()
    conn.close()
    logger.info("✅  Backfilled %d runs into run_quality", updated)
    return updated


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Backfill run_quality table.")
    parser.add_argument(
        "--db",
        default="data/experiments.db",
        help="Path to SQLite DB (default: data/experiments.db)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-score runs that already have a run_quality row",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    backfill_all(db_path=args.db, force=args.force)
