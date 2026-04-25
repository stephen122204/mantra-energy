"""
goal_execution_etl.py — Energy rollup ETL for goal_execution rows.

Populates ETL columns that are NULL at INSERT time:
    total_energy_uj, successful_energy_uj, overhead_energy_uj,
    overhead_fraction, orchestration_fraction

Also backfills normalization_factors per run:
    successful_goals, attempted_goals, failed_attempts

Follows the existing ETL pattern from phase_attribution_etl.py exactly.
All operations are sync. Safe to rerun (idempotent).

Usage:
    python scripts/etl/goal_execution_etl.py --backfill-all
    python scripts/etl/goal_execution_etl.py --goal-id 42
"""

import argparse
import logging
import sqlite3
import sys

logger = logging.getLogger(__name__)

# Default DB path — override with --db-path flag
DEFAULT_DB_PATH = "data/experiments.db"


def process_one(goal_id: int, conn) -> None:
    """
    Populate ETL energy columns for one goal_execution row.

    Reads all goal_attempt rows for this goal_id.
    Validates exactly one is_winning=1 — logs and skips on violation.
    Computes overhead and orchestration fractions.
    Backfills normalization_factors for affected runs.

    Args:
        goal_id: The goal_execution.goal_id to process.
        conn:    Active DB connection — not owned by this function.
    """
    # Guard: goal must exist
    goal_row = conn.execute(
        "SELECT goal_id, winning_run_id, success FROM goal_execution WHERE goal_id = ?",
        (goal_id,),
    ).fetchone()
    if goal_row is None:
        logger.warning("process_one: goal_id=%d not found — skipping", goal_id)
        return

    winning_run_id = goal_row[1]

    # Load all attempts for energy summation
    attempts = conn.execute(
        """SELECT attempt_id, run_id, is_winning, energy_uj
           FROM goal_attempt
           WHERE goal_id = ?
           ORDER BY attempt_number""",
        (goal_id,),
    ).fetchall()

    if not attempts:
        logger.warning("process_one: goal_id=%d has no attempts — skipping", goal_id)
        return

    # Validate exactly one winning attempt — data integrity guard
    winning_attempts = [a for a in attempts if a[2] == 1]
    if len(winning_attempts) > 1:
        logger.warning(
            "process_one: goal_id=%d has %d winning attempts (expected 0 or 1) — skipping",
            goal_id, len(winning_attempts),
        )
        return

    total_energy_uj = _sum_attempt_energies(attempts)

    # Failed goals — no winning attempt means all energy was wasted.
    # overhead_fraction = 1.0 is the correct paper signal: 100% overhead, 0% productive.
    # Must be set explicitly — NULL would be silently excluded from paper Figure 3 aggregations.
    if not winning_attempts:
        _update_goal_execution(
            conn, goal_id,
            total_energy_uj=total_energy_uj,
            successful_energy_uj=0,
            overhead_energy_uj=total_energy_uj,
            overhead_fraction=1.0,
            orchestration_fraction=None,
        )
        run_ids = list({a[1] for a in attempts if a[1] and a[1] != -1})
        for run_id in run_ids:
            _backfill_normalization_factors(conn, run_id)
        logger.info(
            "process_one: goal_id=%d FAILED — overhead_fraction=1.0 total=%.0f",
            goal_id, total_energy_uj or 0,
        )
        return

    successful_energy_uj = _get_winning_energy(winning_attempts)
    overhead_energy_uj = _compute_overhead(total_energy_uj, successful_energy_uj)
    overhead_fraction = _compute_fraction(overhead_energy_uj, total_energy_uj)
    orchestration_fraction = _get_orchestration_fraction(conn, winning_run_id)

    _update_goal_execution(
        conn, goal_id,
        total_energy_uj, successful_energy_uj, overhead_energy_uj,
        overhead_fraction, orchestration_fraction,
    )


def backfill_all(db_path: str) -> None:
    """
    Process all goal_execution rows where total_energy_uj IS NULL.

    Idempotent — rows already populated are skipped automatically.
    Processes one goal at a time to limit transaction scope.

    Args:
        db_path: Filesystem path to the SQLite experiments DB.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # Only process goals with NULL ETL columns and at least one attempt
        pending = conn.execute(
            """SELECT ge.goal_id
               FROM goal_execution ge
               WHERE ge.total_energy_uj IS NULL
                  OR (ge.success = 0 AND ge.overhead_fraction IS NULL)
               ORDER BY ge.goal_id"""
        ).fetchall()

        logger.info("backfill_all: %d goals pending ETL", len(pending))

        success_count = 0
        fail_count = 0
        for row in pending:
            try:
                process_one(row[0], conn)
                success_count += 1
            except Exception as e:
                # Log and continue — one bad goal must not abort the batch
                logger.warning("backfill_all: goal_id=%d failed: %s", row[0], e)
                fail_count += 1

        logger.info(
            "backfill_all: complete — %d processed, %d failed",
            success_count, fail_count,
        )
    finally:
        conn.close()


# ── Private computation helpers ───────────────────────────────────────────────

def _sum_attempt_energies(attempts: list) -> int:
    """
    Sum energy_uj across all attempts. NULL attempt energy treated as 0.
    Returns None if all attempts have NULL energy (no data yet).
    """
    values = [a[3] for a in attempts if a[3] is not None]
    if not values:
        return None
    return sum(values)


def _get_winning_energy(winning_attempts: list):
    """
    Return energy_uj from the single winning attempt, or None if no winner.
    Called only after the is_winning=1 count has been validated as 0 or 1.
    """
    if not winning_attempts:
        return None
    return winning_attempts[0][3]  # energy_uj


def _compute_overhead(total_energy_uj, successful_energy_uj):
    """
    overhead = total - successful.
    Returns None if either input is None (data not yet available).
    """
    if total_energy_uj is None or successful_energy_uj is None:
        return None
    return total_energy_uj - successful_energy_uj


def _compute_fraction(numerator, denominator):
    """
    Safe division returning REAL fraction or None.
    Returns None rather than 0 when denominator is 0 — avoids misleading 0.0.
    """
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _get_orchestration_fraction(conn, winning_run_id) -> float:
    """
    Read orchestration_fraction from energy_attribution for the winning run.

    energy_attribution must exist for winning_run_id — missing row is a warning,
    not an error. Returns None so ETL column stays NULL rather than corrupting
    data with a zero.

    Args:
        conn:           Active DB connection.
        winning_run_id: run_id of the winning attempt. None → returns None.
    """
    if winning_run_id is None or winning_run_id == -1:
        return None

    row = conn.execute(
        """SELECT orchestration_energy_uj, pkg_energy_uj
           FROM energy_attribution
           WHERE run_id = ?""",
        (winning_run_id,),
    ).fetchone()

    if row is None:
        # energy_attribution row missing — ETL has not run yet for this run
        logger.warning(
            "_get_orchestration_fraction: energy_attribution missing run_id=%d",
            winning_run_id,
        )
        return None

    orch_uj, pkg_uj = row[0], row[1]
    return _compute_fraction(orch_uj, pkg_uj)


def _update_goal_execution(
    conn, goal_id: int,
    total_energy_uj, successful_energy_uj, overhead_energy_uj,
    overhead_fraction, orchestration_fraction,
) -> None:
    """
    UPDATE goal_execution ETL columns for one goal_id.
    All five columns written in one UPDATE for atomicity.
    """
    conn.execute(
        """UPDATE goal_execution SET
               total_energy_uj        = ?,
               successful_energy_uj   = ?,
               overhead_energy_uj     = ?,
               overhead_fraction      = ?,
               orchestration_fraction = ?
           WHERE goal_id = ?""",
        (
            total_energy_uj, successful_energy_uj, overhead_energy_uj,
            overhead_fraction, orchestration_fraction,
            goal_id,
        ),
    )
    conn.commit()


def _backfill_normalization_factors(conn, run_id: int) -> None:
    """
    Backfill normalization_factors for one run_id from goal_execution aggregates.

    Populates: successful_goals, attempted_goals, failed_attempts.
    These three are derived from goal_attempt counts — not recomputed from energy.

    normalization_factors row must already exist (created by experiment_runner).
    Missing row → log warning, skip. Never INSERT here — that is runner's job.
    """
    # Verify normalization_factors row exists before attempting UPDATE
    exists = conn.execute(
        "SELECT 1 FROM normalization_factors WHERE run_id = ?", (run_id,),
    ).fetchone()
    if not exists:
        logger.warning(
            "_backfill_normalization_factors: run_id=%d not in normalization_factors — skipping",
            run_id,
        )
        return

    # Count goals associated with this run through goal_attempt
    stats = conn.execute(
        """SELECT
               COUNT(DISTINCT ge.goal_id)                          AS attempted_goals,
               SUM(CASE WHEN ge.success = 1 THEN 1 ELSE 0 END)    AS successful_goals
           FROM goal_execution ge
           JOIN goal_attempt ga ON ga.goal_id = ge.goal_id
           WHERE ga.run_id = ?""",
        (run_id,),
    ).fetchone()

    if stats is None:
        return

    attempted = stats[0] or 0
    successful = stats[1] or 0
    failed = attempted - successful

    conn.execute(
        """UPDATE normalization_factors SET
               attempted_goals  = ?,
               successful_goals = ?,
               failed_attempts  = ?
           WHERE run_id = ?""",
        (attempted, successful, failed, run_id),
    )
    conn.commit()


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    """CLI entry point. Accepts --backfill-all and --goal-id N flags."""
    parser = argparse.ArgumentParser(
        description="Populate goal_execution ETL energy columns."
    )
    parser.add_argument(
        "--backfill-all",
        action="store_true",
        help="Process all goal_execution rows with NULL total_energy_uj.",
    )
    parser.add_argument(
        "--goal-id",
        type=int,
        default=None,
        help="Process a single goal_execution row by goal_id.",
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to experiments SQLite DB (default: {DEFAULT_DB_PATH}).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.backfill_all:
        backfill_all(args.db_path)
    elif args.goal_id is not None:
        conn = sqlite3.connect(args.db_path)
        conn.row_factory = sqlite3.Row
        try:
            process_one(args.goal_id, conn)
        finally:
            conn.close()
    else:
        # No flag given — print usage and exit cleanly
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
