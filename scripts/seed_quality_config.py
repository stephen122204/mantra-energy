#!/usr/bin/env python3
"""
================================================================================
SEED QUALITY CONFIG — Populate task_quality_config table
================================================================================
PURPOSE:
    Seeds task_quality_config with judge method, metric type, and threshold
    for every task category. Category-level config — applies uniformly to
    EpG, mEpG, and qEpG tasks without per-task overrides.

    Run ONCE after migration 042. Idempotent — safe to rerun (INSERT OR IGNORE).

USAGE:
    python scripts/seed_quality_config.py
    python scripts/seed_quality_config.py --db-path data/experiments.db

AUTHOR: Deepak Panigrahy
================================================================================
"""

import argparse
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# ============================================================================
# Quality config — 17 rows covering all categories
# (task_category, metric_type, judge_method, threshold, dual_judge)
# dual_judge=1: two independent LLM judges, agreement required
# threshold: minimum normalized_score for pass_fail=1
# ============================================================================
QUALITY_CONFIG = [
    # Original 7 categories
    ("reasoning",        "scalar",    "llm_judge",           0.80, 1),
    ("coding",           "testsuite", "unit_test",           0.80, 0),
    ("qa",               "binary",    "exact_match",         1.00, 0),
    ("summarization",    "scalar",    "llm_judge",           0.75, 1),
    ("classification",   "binary",    "exact_match",         1.00, 0),
    ("extraction",       "scalar",    "llm_judge",           0.80, 1),
    ("custom",           "scalar",    "llm_judge",           0.70, 0),
    # New categories — tool-using and orchestration tasks
    ("multi_tool",       "binary",    "exact_match",         1.00, 0),
    ("planning",         "scalar",    "llm_judge",           0.80, 1),
    ("data_analysis",    "scalar",    "llm_judge",           0.80, 1),
    ("debugging",        "binary",    "exact_match",         1.00, 0),
    ("research",         "scalar",    "llm_judge",           0.75, 1),
    ("orchestration",    "scalar",    "llm_judge",           0.70, 1),
    ("translation",      "scalar",    "semantic_similarity", 0.85, 1),
    ("creative_writing", "scalar",    "llm_judge",           0.70, 1),
    ("web_search",       "binary",    "exact_match",         1.00, 0),
    # Media tasks — TTS/STT/VC quality proxy via semantic similarity
    ("media",            "scalar",    "semantic_similarity", 0.80, 0),
]


def seed(db_path: str) -> None:
    """
    Insert quality config rows. Idempotent — INSERT OR IGNORE on unique task_category.

    Args:
        db_path: Path to experiments.db
    """
    conn = sqlite3.connect(db_path)
    try:
        inserted = 0
        skipped = 0
        for row in QUALITY_CONFIG:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO task_quality_config
                    (task_category, metric_type, judge_method, threshold, dual_judge)
                VALUES (?, ?, ?, ?, ?)
                """,
                row,
            )
            if cur.rowcount > 0:
                inserted += 1
            else:
                skipped += 1  # already seeded — idempotent
        conn.commit()
        logger.info("seed_quality_config: inserted=%d skipped=%d", inserted, skipped)
        print(f"Done: inserted={inserted} skipped={skipped} total={inserted+skipped}")
    finally:
        conn.close()


def verify(db_path: str) -> None:
    """Print seeded rows for manual verification."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT task_category, metric_type, judge_method, threshold, dual_judge "
            "FROM task_quality_config ORDER BY task_category"
        ).fetchall()
        print(f"\ntask_quality_config — {len(rows)} rows:")
        print(f"{'category':<20} {'metric':<12} {'judge':<22} {'thresh':<8} {'dual'}")
        print("-" * 72)
        for r in rows:
            print(f"{r[0]:<20} {r[1]:<12} {r[2]:<22} {r[3]:<8} {r[4]}")
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Seed task_quality_config table")
    parser.add_argument(
        "--db-path",
        default="data/experiments.db",
        help="Path to experiments.db (default: data/experiments.db)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Print seeded rows after insertion",
    )
    args = parser.parse_args()

    db = str(Path(args.db_path).resolve())
    seed(db)
    if args.verify:
        verify(db)
