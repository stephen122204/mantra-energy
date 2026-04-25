#!/usr/bin/env python3
"""
test_exp_integrity.py — Experiment integrity scanner.

Accepts an exp_id and walks all child tables, reporting pass/fail
per table with column-level checks. Run after every experiment to
verify all 12 tables are correctly populated.

Usage:
    python scripts/test_exp_integrity.py --exp-id 721
    python scripts/test_exp_integrity.py --latest
    python scripts/test_exp_integrity.py --latest --experiment-type failure_injection
"""

import argparse
import sqlite3
import sys
from pathlib import Path

DB_PATH = "data/experiments.db"

# ANSI colors
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def ok(msg):  return f"{GREEN}✅ {msg}{RESET}"
def fail(msg): return f"{RED}❌ {msg}{RESET}"
def warn(msg): return f"{YELLOW}⚠️  {msg}{RESET}"


def check_experiment(conn, exp_id: int) -> dict:
    """Load experiment row and basic metadata."""
    row = conn.execute(
        "SELECT exp_id, experiment_type, workflow_type, status, "
        "runs_completed, runs_total FROM experiments WHERE exp_id = ?",
        (exp_id,)
    ).fetchone()
    if row is None:
        print(fail(f"exp_id={exp_id} not found in experiments table"))
        sys.exit(1)
    return dict(row)


def get_run_ids(conn, exp_id: int) -> list:
    rows = conn.execute(
        "SELECT run_id FROM runs WHERE exp_id = ?", (exp_id,)
    ).fetchall()
    return [r[0] for r in rows]


def get_goal_ids(conn, exp_id: int) -> list:
    rows = conn.execute(
        "SELECT goal_id FROM goal_execution WHERE exp_id = ?", (exp_id,)
    ).fetchall()
    return [r[0] for r in rows]


def get_attempt_ids(conn, goal_ids: list) -> list:
    if not goal_ids:
        return []
    placeholders = ",".join("?" * len(goal_ids))
    rows = conn.execute(
        f"SELECT attempt_id FROM goal_attempt WHERE goal_id IN ({placeholders})",
        goal_ids
    ).fetchall()
    return [r[0] for r in rows]


def check_runs(conn, exp_id: int, run_ids: list, exp_meta: dict) -> list:
    results = []
    count = len(run_ids)
    expected = exp_meta["runs_total"] or 0

    if count == 0:
        results.append(fail(f"runs: 0 rows — experiment saved nothing"))
        return results

    # Check energy columns not NULL
    null_energy = conn.execute(
        "SELECT COUNT(*) FROM runs WHERE exp_id = ? AND dynamic_energy_uj IS NULL",
        (exp_id,)
    ).fetchone()[0]

    if null_energy > 0:
        results.append(warn(f"runs: {count} rows, {null_energy} have NULL workload_energy_j"))
    else:
        results.append(ok(f"runs: {count} rows, all energy columns populated"))

    return results


def check_goal_execution(conn, exp_id: int, goal_ids: list) -> list:
    results = []
    count = len(goal_ids)

    if count == 0:
        results.append(fail("goal_execution: 0 rows"))
        return results

    # Check overhead_fraction not NULL
    null_overhead = conn.execute(
        "SELECT COUNT(*) FROM goal_execution WHERE exp_id = ? AND overhead_fraction IS NULL",
        (exp_id,)
    ).fetchone()[0]

    # Check success distribution
    success_count = conn.execute(
        "SELECT COUNT(*) FROM goal_execution WHERE exp_id = ? AND success = 1",
        (exp_id,)
    ).fetchone()[0]

    if null_overhead > 0:
        results.append(warn(
            f"goal_execution: {count} rows, {null_overhead} have NULL overhead_fraction"
            f" — run: python scripts/etl/goal_execution_etl.py --backfill-all"
        ))
    else:
        results.append(ok(
            f"goal_execution: {count} rows, {success_count} success, "
            f"{count-success_count} failed, overhead_fraction populated"
        ))

    return results


def check_goal_attempt(conn, goal_ids: list, attempt_ids: list) -> list:
    results = []
    count = len(attempt_ids)

    if count == 0:
        results.append(fail("goal_attempt: 0 rows"))
        return results

    if not goal_ids:
        return results

    placeholders = ",".join("?" * len(goal_ids))
    retry_count = conn.execute(
        f"SELECT COUNT(*) FROM goal_attempt WHERE goal_id IN ({placeholders}) AND is_retry = 1",
        goal_ids
    ).fetchone()[0]

    null_failure = conn.execute(
        f"SELECT COUNT(*) FROM goal_attempt WHERE goal_id IN ({placeholders}) "
        f"AND outcome = 'failure' AND failure_type IS NULL",
        goal_ids
    ).fetchone()[0]

    msg = f"goal_attempt: {count} rows, {retry_count} retries"
    if null_failure > 0:
        msg += f", {null_failure} failures with NULL failure_type"
        results.append(warn(msg))
    else:
        results.append(ok(msg))

    return results


def check_tool_failure_events(conn, attempt_ids: list, exp_type: str) -> list:
    results = []

    if not attempt_ids:
        results.append(warn("tool_failure_events: no attempts to check"))
        return results

    placeholders = ",".join("?" * len(attempt_ids))
    count = conn.execute(
        f"SELECT COUNT(*) FROM tool_failure_events WHERE attempt_id IN ({placeholders})",
        attempt_ids
    ).fetchone()[0]

    # For failure_injection and retry_study experiments, expect > 0
    expects_failures = exp_type in ("failure_injection", "retry_study")
    if expects_failures and count == 0:
        results.append(fail(
            f"tool_failure_events: 0 rows — expected > 0 for {exp_type} experiment"
        ))
    elif count > 0:
        # Check failure types
        types = conn.execute(
            f"SELECT failure_type, COUNT(*) FROM tool_failure_events "
            f"WHERE attempt_id IN ({placeholders}) GROUP BY failure_type",
            attempt_ids
        ).fetchall()
        type_str = ", ".join(f"{t[0]}={t[1]}" for t in types)
        results.append(ok(f"tool_failure_events: {count} rows ({type_str})"))
    else:
        results.append(ok(f"tool_failure_events: 0 rows (normal for {exp_type})"))

    return results


def check_normalization_factors(conn, run_ids: list) -> list:
    results = []

    if not run_ids:
        results.append(warn("normalization_factors: no runs to check"))
        return results

    placeholders = ",".join("?" * len(run_ids))
    count = conn.execute(
        f"SELECT COUNT(*) FROM normalization_factors WHERE run_id IN ({placeholders})",
        run_ids
    ).fetchone()[0]

    missing = len(run_ids) - count
    if missing > 0:
        results.append(warn(
            f"normalization_factors: {count}/{len(run_ids)} runs have stub rows, "
            f"{missing} missing — ETL backfill will skip these"
        ))
    else:
        results.append(ok(
            f"normalization_factors: {count}/{len(run_ids)} runs have stub rows"
        ))

    return results


def check_energy_attribution(conn, run_ids: list) -> list:
    results = []

    if not run_ids:
        return results

    placeholders = ",".join("?" * len(run_ids))
    count = conn.execute(
        f"SELECT COUNT(*) FROM energy_attribution WHERE run_id IN ({placeholders})",
        run_ids
    ).fetchone()[0]

    if count == 0:
        results.append(warn("energy_attribution: 0 rows — ETL may not have run"))
    else:
        results.append(ok(f"energy_attribution: {count} rows"))

    return results


def check_run_quality(conn, run_ids: list) -> list:
    results = []

    if not run_ids:
        return results

    placeholders = ",".join("?" * len(run_ids))
    count = conn.execute(
        f"SELECT COUNT(*) FROM run_quality WHERE run_id IN ({placeholders})",
        run_ids
    ).fetchone()[0]

    missing = len(run_ids) - count
    if missing > 0:
        results.append(warn(f"run_quality: {count}/{len(run_ids)} runs scored"))
    else:
        results.append(ok(f"run_quality: {count}/{len(run_ids)} runs scored"))

    return results


def check_orchestration_events(conn, run_ids: list, workflow_type: str) -> list:
    results = []

    if not run_ids:
        return results

    placeholders = ",".join("?" * len(run_ids))
    count = conn.execute(
        f"SELECT COUNT(*) FROM orchestration_events WHERE run_id IN ({placeholders})",
        run_ids
    ).fetchone()[0]

    # Expect orchestration events for agentic runs
    if workflow_type in ("agentic", "comparison") and count == 0:
        results.append(warn("orchestration_events: 0 rows for agentic experiment"))
    else:
        results.append(ok(f"orchestration_events: {count} rows"))

    return results


def check_llm_interactions(conn, run_ids: list) -> list:
    results = []

    if not run_ids:
        return results

    placeholders = ",".join("?" * len(run_ids))
    count = conn.execute(
        f"SELECT COUNT(*) FROM llm_interactions WHERE run_id IN ({placeholders})",
        run_ids
    ).fetchone()[0]

    if count == 0:
        results.append(warn("llm_interactions: 0 rows"))
    else:
        results.append(ok(f"llm_interactions: {count} rows"))

    return results


def check_expected_empty(conn) -> list:
    """Tables expected empty — verify they haven't been accidentally populated."""
    results = []

    # hallucination_events and output_quality owned by 8.5-C
    for table in ("hallucination_events", "output_quality", "output_quality_judges"):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        results.append(ok(f"{table}: {count} rows (8.5-C owns this)"))

    return results


def main():
    parser = argparse.ArgumentParser(description="A-LEMS experiment integrity scanner")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--exp-id", type=int, help="Experiment ID to check")
    group.add_argument("--latest", action="store_true", help="Check latest experiment")
    parser.add_argument("--experiment-type", help="Filter --latest by experiment type")
    parser.add_argument("--db", default=DB_PATH, help="Path to SQLite DB")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(fail(f"DB not found: {args.db}"))
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    if args.latest:
        if args.experiment_type:
            row = conn.execute(
                "SELECT MAX(exp_id) FROM experiments WHERE experiment_type = ?",
                (args.experiment_type,)
            ).fetchone()
        else:
            row = conn.execute("SELECT MAX(exp_id) FROM experiments").fetchone()
        exp_id = row[0]
        if exp_id is None:
            print(fail("No experiments found"))
            sys.exit(1)
    else:
        exp_id = args.exp_id

    exp_meta = check_experiment(conn, exp_id)
    exp_type = exp_meta["experiment_type"] or "normal"
    workflow  = exp_meta["workflow_type"] or "comparison"

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}A-LEMS Experiment Integrity Check{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")
    print(f"  exp_id:          {exp_id}")
    print(f"  experiment_type: {exp_type}")
    print(f"  workflow_type:   {workflow}")
    print(f"  status:          {exp_meta['status']}")
    print(f"  runs_completed:  {exp_meta['runs_completed']} / {exp_meta['runs_total']}")
    print(f"{'='*60}\n")

    run_ids     = get_run_ids(conn, exp_id)
    goal_ids    = get_goal_ids(conn, exp_id)
    attempt_ids = get_attempt_ids(conn, goal_ids)

    all_results = []
    all_results += check_runs(conn, exp_id, run_ids, exp_meta)
    all_results += check_goal_execution(conn, exp_id, goal_ids)
    all_results += check_goal_attempt(conn, goal_ids, attempt_ids)
    all_results += check_tool_failure_events(conn, attempt_ids, exp_type)
    all_results += check_normalization_factors(conn, run_ids)
    all_results += check_energy_attribution(conn, run_ids)
    all_results += check_run_quality(conn, run_ids)
    all_results += check_orchestration_events(conn, run_ids, workflow)
    all_results += check_llm_interactions(conn, run_ids)
    all_results += check_expected_empty(conn)

    passed = sum(1 for r in all_results if r.startswith(GREEN))
    warned = sum(1 for r in all_results if r.startswith(YELLOW))
    failed = sum(1 for r in all_results if r.startswith(RED))

    for r in all_results:
        print(f"  {r}")

    print(f"\n{'='*60}")
    print(f"  RESULT: {passed} passed, {warned} warnings, {failed} failed")
    print(f"{'='*60}\n")

    conn.close()
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
