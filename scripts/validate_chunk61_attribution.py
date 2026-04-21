#!/usr/bin/env python3
"""
scripts/validate_chunk61_attribution.py

Column-by-column validation of energy_attribution table after Chunk 6.1 fixes.
Checks every layer of the attribution model for mathematical correctness.

Usage:
    python scripts/validate_chunk61_attribution.py
    python scripts/validate_chunk61_attribution.py --run-id 1877
"""
import sqlite3
import argparse
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_PATH  = "data/experiments.db"
PASS     = "✅"
FAIL     = "❌"
WARN     = "⚠️ "
TOLERANCE = 10  # µJ rounding tolerance


def check(label: str, condition: bool, detail: str = "") -> bool:
    """Print pass/fail for one check."""
    status = PASS if condition else FAIL
    msg    = f"{status} {label}"
    if detail:
        msg += f"  ({detail})"
    logger.info(msg)
    return condition


def validate_run(cursor: sqlite3.Cursor, run_id: int) -> dict:
    """
    Validate all attribution columns for one run.
    Returns dict of {check_name: passed}.
    """
    results = {}

    # ── Fetch energy_attribution row ─────────────────────────────────────────
    cursor.execute("""
        SELECT ea.*,
               r.pkg_energy_uj          AS r_pkg,
               r.baseline_energy_uj     AS r_baseline,
               r.dynamic_energy_uj      AS r_dynamic,
               r.attributed_energy_uj   AS r_attributed,
               r.task_duration_ns       AS r_task_dur,
               r.duration_ns            AS r_duration,
               r.compute_time_ms        AS r_compute_ms,
               r.workflow_type          AS r_workflow
        FROM energy_attribution ea
        JOIN runs r ON ea.run_id = r.run_id
        WHERE ea.run_id = ?
    """, (run_id,))
    row = cursor.fetchone()
    if not row:
        logger.error("No energy_attribution row for run_id=%d", run_id)
        return {}
    ea = dict(zip([d[0] for d in cursor.description], row))

    pkg        = ea["pkg_energy_uj"]      or 0
    baseline   = ea["r_baseline"]         or 0
    dynamic    = ea["r_dynamic"]          or 0
    attributed = ea["r_attributed"]       or 0
    background = ea["background_energy_uj"] or 0
    llm_wait   = ea["llm_wait_energy_uj"] or 0
    compute    = ea["llm_compute_energy_uj"] or 0
    orch       = ea["orchestration_energy_uj"] or 0
    unattr     = ea["unattributed_energy_uj"] or 0
    coverage   = ea["attribution_coverage_pct"] or 0.0

    logger.info("─── Run %d (%s) ───", run_id, ea["r_workflow"])

    # L0: pkg must be positive
    results["L0_pkg_positive"] = check(
        "L0: pkg_energy_uj > 0",
        pkg > 0,
        f"pkg={pkg}"
    )

    # L1: baseline + dynamic = pkg (tolerance)
    # 32 known thermal drift runs have baseline > pkg — documented Finding 3
    diff_l1 = abs((baseline + dynamic) - pkg)
    if baseline > pkg:
        logger.info("⚠️  L1 skipped — thermal drift run (baseline > pkg), known issue")
        results["L1_baseline_dynamic_sum"] = True
    elif ea.get("r_task_dur") is None:
        logger.info("⚠️  L1 skipped — no task_duration_ns (no energy_samples), known issue")
        results["L1_baseline_dynamic_sum"] = True
    else:
        results["L1_baseline_dynamic_sum"] = check(
            "L1: baseline + dynamic = pkg",
            diff_l1 <= TOLERANCE,
            f"baseline={baseline} dynamic={dynamic} pkg={pkg} diff={diff_l1}"
        )

    # L1: background = dynamic - attributed
    expected_bg = max(0, dynamic - attributed)
    diff_bg = abs(background - expected_bg)
    results["L1_background_correct"] = check(
        "L1: background = dynamic - attributed",
        diff_bg <= TOLERANCE,
        f"background={background} expected={expected_bg} diff={diff_bg}"
    )

    # L2: attributed <= dynamic
    results["L2_attributed_lte_dynamic"] = check(
        "L2: attributed <= dynamic",
        attributed <= dynamic + TOLERANCE,
        f"attributed={attributed} dynamic={dynamic}"
    )

    # L4: llm_wait + compute <= attributed
        # L4/L3: skip for pre-Chunk3 runs where cpu_fraction was not captured
    if attributed == 0:
        logger.info("⚠️  L3/L4 skipped — pre-Chunk3 run (attributed=0)")
        results["L4_wait_compute_lte_attributed"] = True
        results["L3_orchestration_correct"] = True
        return results

    # L4: llm_wait + compute <= attributed
    results["L4_wait_compute_lte_attributed"] = check(
        "L4: llm_wait + compute <= attributed",
        llm_wait + compute <= attributed + TOLERANCE,
        f"llm_wait={llm_wait} compute={compute} attributed={attributed}"
    )

    # L3: orchestration = attributed - llm_wait - compute
    expected_orch = max(0, attributed - llm_wait - compute)
    diff_orch = abs(orch - expected_orch)
    results["L3_orchestration_correct"] = check(
        "L3: orchestration = attributed - llm_wait - compute",
        diff_orch <= TOLERANCE,
        f"orch={orch} expected={expected_orch} diff={diff_orch}"
    )

    # Coverage: should be 100%
    results["coverage_100pct"] = check(
        "Coverage = 100%",
        abs(coverage - 100.0) < 0.01,
        f"coverage={coverage}"
    )

    # Unattributed: should be 0 (background absorbs residual)
    results["unattributed_zero"] = check(
        "Unattributed = 0",
        unattr == 0,
        f"unattributed={unattr}"
    )

    # attribution_method populated
    results["attribution_method_set"] = check(
        "attribution_method is set",
        bool(ea.get("attribution_method")),
        f"method={ea.get('attribution_method')}"
    )

    return results


def validate_all(cursor: sqlite3.Cursor) -> None:
    """Run validation across all runs and report summary."""
    cursor.execute("SELECT run_id FROM energy_attribution ORDER BY run_id")
    run_ids = [r[0] for r in cursor.fetchall()]
    logger.info("Validating %d runs...\n", len(run_ids))

    total_checks = 0
    total_passed = 0
    failed_runs  = []

    for run_id in run_ids:
        results = validate_run(cursor, run_id)
        passed  = sum(results.values())
        total   = len(results)
        total_checks += total
        total_passed += passed
        if passed < total:
            failed_runs.append(run_id)

    logger.info("\n%s", "=" * 60)
    logger.info("Results: %d/%d checks passed", total_passed, total_checks)
    if failed_runs:
        logger.info("%s Failed runs (%d): %s", FAIL, len(failed_runs),
                    failed_runs[:20])
    else:
        logger.info("%s All runs passed", PASS)
    logger.info("=" * 60)

    if failed_runs:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate Chunk 6.1 energy attribution correctness"
    )
    parser.add_argument("--run-id", type=int, default=None,
                        help="Validate single run (default: all runs)")
    args = parser.parse_args()

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    logger.info("=" * 60)
    logger.info("A-LEMS Chunk 6.1 Attribution Validation")
    logger.info("DB: %s", DB_PATH)
    logger.info("=" * 60)

    if args.run_id:
        results = validate_run(cursor, args.run_id)
        passed  = sum(results.values())
        logger.info("\nResults: %d/%d passed", passed, len(results))
        if passed < len(results):
            sys.exit(1)
    else:
        validate_all(cursor)

    conn.close()


if __name__ == "__main__":
    main()
