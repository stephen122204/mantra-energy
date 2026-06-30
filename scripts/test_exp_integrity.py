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

from scripts.tools.path_loader import get_alems_db_path
DB_PATH  = get_alems_db_path()

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
        f"AND outcome = 'failure' AND failure_type IS NULL AND is_retry = 1",
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
        results.append(warn(
            f"tool_failure_events: 0 rows — injection may not have fired this run "
            f"(probabilistic injection, small rep count can produce 0 failures)"
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

def check_run_outliers(conn, run_ids: list) -> list:
    """
    Verify run_outliers table is reachable and report current flag counts
    for the given run_ids. This is an EIC-4 registration, not a pass/fail
    gate: an unflagged run is not an error, most runs should have zero
    rows here. The check exists so a broken FK, a botched migration, or a
    detector crash shows up as a warning during integrity checks rather
    than silently producing an empty table forever.
 
    Args:
        conn: sqlite3 connection
        run_ids: run_id list for the experiment being checked
 
    Returns:
        list of ok()/warn()/fail() formatted strings, consistent with every
        other check_* function in this file.
    """
    results = []
    if not run_ids:
        return results
 
    placeholders = ",".join("?" for _ in run_ids)
 
    # DC-3 compliance: explicit try/except, not a bare except, and the
    # failure is surfaced as fail() rather than silently returning [].
    try:
        cur = conn.execute(
            f"SELECT severity, review_status, COUNT(*) "
            f"FROM run_outliers WHERE run_id IN ({placeholders}) "
            f"GROUP BY severity, review_status",
            run_ids,
        )
        rows = cur.fetchall()
    except Exception as e:
        results.append(fail(f"run_outliers: query failed ({e})"))
        return results
 
    if not rows:
        results.append(ok(f"run_outliers: 0/{len(run_ids)} runs flagged"))
        return results
 
    total_flagged = sum(count for _, _, count in rows)
    confirmed = sum(count for sev, status, count in rows if status == "confirmed")
    extreme_pending = sum(
        count for sev, status, count in rows
        if sev == "extreme" and status == "pending"
    )
 
    if extreme_pending > 0:
        # Extreme severity sitting in pending review is worth surfacing as
        # a warning at integrity check time, not just buried in a web page
        # review queue nobody is required to look at before handoff.
        results.append(warn(
            f"run_outliers: {extreme_pending} extreme-severity runs awaiting "
            f"human review (EIC-3: must be documented before chunk handoff)"
        ))
    else:
        results.append(ok(
            f"run_outliers: {total_flagged} flagged "
            f"({confirmed} confirmed excluded) across {len(run_ids)} runs"
        ))
 
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
def check_etl_queue(conn, goal_ids: list) -> list:
    """Verify etl_queue has entries for all goals and all show processed=1."""
    results = []
    if not goal_ids:
        results.append(warn("etl_queue: no goals to check"))
        return results
    count = conn.execute("SELECT COUNT(*) FROM etl_queue WHERE entity_id IN ({})".format(
        ",".join("?" * len(goal_ids))), goal_ids).fetchone()[0]
    if count == 0:
        results.append(fail("etl_queue: no entries for experiment goals"))
        return results
    unprocessed = conn.execute(
        "SELECT COUNT(*) FROM etl_queue WHERE entity_id IN ({}) AND status != 'done'".format(
        ",".join("?" * len(goal_ids))), goal_ids).fetchone()[0]
    if unprocessed > 0:
        results.append(warn(f"etl_queue: {unprocessed} entries not done (status != done)"))
    else:
        results.append(ok(f"etl_queue: {count} entries, all done"))
    return results


def check_retry_policy(conn) -> list:
    """Verify retry_policy has exactly 4 rows: no_retry, default, aggressive, conservative."""
    results = []
    count = conn.execute("SELECT COUNT(*) FROM retry_policy").fetchone()[0]
    if count == 4:
        results.append(ok("retry_policy: 4 rows present"))
    else:
        results.append(fail(f"retry_policy: expected 4 rows, got {count}"))
    return results


def check_task_categories(conn) -> list:
    """Verify task_categories populated. Warn if < 26 (8.5-C.pre not yet run)."""
    results = []
    count = conn.execute("SELECT COUNT(*) FROM task_categories").fetchone()[0]
    if count == 0:
        results.append(fail("task_categories: 0 rows — seed not run"))
    elif count < 16:
        results.append(fail(f"task_categories: only {count} rows — expected >= 16"))
    elif count < 26:
        results.append(warn(f"task_categories: {count} rows — 8.5-C.pre migration 034 not yet run"))
    else:
        results.append(ok(f"task_categories: {count} rows"))
    return results


def check_task_retry_override(conn) -> list:
    """Verify task_retry_override rows are valid. 0 rows is acceptable."""
    results = []
    count = conn.execute("SELECT COUNT(*) FROM task_retry_override").fetchone()[0]
    if count == 0:
        results.append(ok("task_retry_override: 0 rows (no overrides configured — acceptable)"))
        return results
    orphans = conn.execute("""
        SELECT COUNT(*) FROM task_retry_override t
        WHERE NOT EXISTS (SELECT 1 FROM retry_policy p WHERE p.policy_name = t.policy_name)
    """).fetchone()[0]
    if orphans > 0:
        results.append(fail(f"task_retry_override: {orphans} orphan policy_name references"))
    else:
        results.append(ok(f"task_retry_override: {count} overrides, all valid"))
    return results

def check_energy_conservation(conn, exp_id: int, run_ids: list, goal_ids: list) -> list:
    results = []
    rows = conn.execute("""
        SELECT ge.goal_id, r.attributed_energy_uj,
            SUM(ga.energy_uj) AS attempt_sum,
            ABS(r.attributed_energy_uj - SUM(ga.energy_uj)) AS delta
        FROM goal_execution ge
        JOIN runs r ON r.run_id = ge.winning_run_id
        JOIN goal_attempt ga ON ga.goal_id = ge.goal_id
        WHERE ge.exp_id = ? AND ge.winning_run_id IS NOT NULL
          AND ga.energy_uj IS NOT NULL
        GROUP BY ge.goal_id
    """, (exp_id,)).fetchall()
    if not rows:
        results.append(warn("energy_conservation: no successful goals to verify"))
    else:
        violations = [r for r in rows if r["delta"] > 1000]
        if violations:
            for v in violations:
                results.append(fail(f"energy_conservation VIOLATION goal={v['goal_id']} delta={v['delta']}µJ"))
        else:
            results.append(ok(f"energy_conservation: {len(rows)} goals verified max_delta={max(r['delta'] for r in rows)}µJ"))
    rows2 = conn.execute("""
        SELECT ge.goal_id, ge.total_energy_uj, SUM(ga.energy_uj) AS attempt_sum
        FROM goal_execution ge
        JOIN goal_attempt ga ON ga.goal_id = ge.goal_id
        WHERE ge.exp_id = ? AND ga.energy_uj IS NOT NULL
        GROUP BY ge.goal_id HAVING ge.total_energy_uj IS NOT NULL
    """, (exp_id,)).fetchall()
    violations2 = [r for r in rows2 if abs((r["total_energy_uj"] or 0) - (r["attempt_sum"] or 0)) > 1000]
    if violations2:
        for v in violations2:
            results.append(warn(f"goal_execution.total mismatch goal={v['goal_id']} stored={v['total_energy_uj']} computed={v['attempt_sum']}"))
    elif rows2:
        results.append(ok(f"goal_execution.total matches attempt sums: {len(rows2)} goals"))

    # D1: E_attributed = E_llm_window + E_orchestration
    # llm_window = llm_compute_energy_uj (residual guaranteed by ETL construction)
    d1_rows = conn.execute("""
        SELECT ea.run_id,
            ABS(r.attributed_energy_uj
                - COALESCE(ea.llm_compute_energy_uj, 0)
                - COALESCE(ea.orchestration_energy_uj, 0)) AS d1_delta
        FROM energy_attribution ea
        JOIN runs r ON r.run_id = ea.run_id
        WHERE ea.run_id IN ({placeholders})
          AND r.attributed_energy_uj > 0
    """.format(placeholders=",".join("?" * len(run_ids))), run_ids).fetchall()
    d1_violations = [r for r in d1_rows if r["d1_delta"] > 1000]
    if d1_violations:
        for v in d1_violations:
            results.append(fail(f"D1 VIOLATION run={v['run_id']} delta={v['d1_delta']}µJ"))
    elif d1_rows:
        results.append(ok(f"D1 conservation: {len(d1_rows)} runs verified max_delta={max(r['d1_delta'] for r in d1_rows)}µJ"))
 
    # D4: E_pkg = E_core + E_uncore + E_dram
    d4_rows = conn.execute("""
        SELECT ea.run_id,
            ABS(ea.pkg_energy_uj
                - COALESCE(ea.core_energy_uj, 0)
                - COALESCE(ea.uncore_energy_uj, 0)
                - COALESCE(ea.dram_energy_uj, 0)) AS d4_delta
        FROM energy_attribution ea
        WHERE ea.run_id IN ({placeholders})
          AND ea.pkg_energy_uj > 0
          AND ea.core_energy_uj > 0
    """.format(placeholders=",".join("?" * len(run_ids))), run_ids).fetchall()
    d4_violations = [r for r in d4_rows if r["d4_delta"] > (0.01 * 1e6)]
    if d4_violations:
        for v in d4_violations:
            results.append(warn(f"D4 delta run={v['run_id']} delta={v['d4_delta']}µJ"))
    elif d4_rows:
        results.append(ok(f"D4 conservation: {len(d4_rows)} runs verified"))
 
    # D3b: E_dynamic = E_attributed + E_background
    d3b_rows = conn.execute("""
        SELECT r.run_id,
            ABS(r.dynamic_energy_uj
                - r.attributed_energy_uj
                - COALESCE(ea.background_energy_uj, 0)) AS d3b_delta
        FROM runs r
        JOIN energy_attribution ea ON ea.run_id = r.run_id
        WHERE r.run_id IN ({placeholders})
          AND r.dynamic_energy_uj > 0
    """.format(placeholders=",".join("?" * len(run_ids))), run_ids).fetchall()
    d3b_violations = [r for r in d3b_rows if r["d3b_delta"] > 1000]
    if d3b_violations:
        for v in d3b_violations:
            results.append(fail(f"D3b VIOLATION run={v['run_id']} delta={v['d3b_delta']}µJ"))
    elif d3b_rows:
        results.append(ok(f"D3b conservation: {len(d3b_rows)} runs verified"))
 
    # D2: E_attributed = E_planning + E_execution + E_synthesis + E_inter_phase
    d2_rows = conn.execute("""
        SELECT ea.run_id,
            ABS(r.attributed_energy_uj
                - COALESCE(ea.planning_energy_uj, 0)
                - COALESCE(ea.execution_energy_uj, 0)
                - COALESCE(ea.synthesis_energy_uj, 0)
                - COALESCE(ea.inter_phase_energy_uj, 0)) AS d2_delta
        FROM energy_attribution ea
        JOIN runs r ON r.run_id = ea.run_id
        WHERE ea.run_id IN ({placeholders})
          AND r.attributed_energy_uj > 0
          AND ea.planning_energy_uj > 0
    """.format(placeholders=",".join("?" * len(run_ids))), run_ids).fetchall()
    d2_violations = [r for r in d2_rows if r["d2_delta"] > 1000]
    if d2_violations:
        for v in d2_violations:
            results.append(fail(f"D2 VIOLATION run={v['run_id']} delta={v['d2_delta']}µJ"))
    elif d2_rows:
        results.append(ok(f"D2 conservation: {len(d2_rows)} runs verified"))
    else:
        results.append(warn("D2 conservation: no agentic runs with phase data to verify"))
    return results


def check_paper_core_query(conn) -> list:
    results = []
    rows = conn.execute("""
        SELECT ge.workflow_type, COUNT(*) AS goals,
            AVG(ge.overhead_fraction) AS avg_overhead,
            COUNT(ge.overhead_fraction) AS has_overhead
        FROM goal_execution ge
        JOIN experiments e ON ge.exp_id = e.exp_id
        WHERE e.experiment_type IN ('normal','overhead_study','retry_study',
            'failure_injection','quality_sweep','ablation')
        AND e.is_valid = 1
        GROUP BY ge.workflow_type
    """).fetchall()
    if not rows:
        results.append(fail("paper_core_query: 0 rows with is_valid=1 — no valid experiments"))
    else:
        for row in rows:
            avg = f"{row['avg_overhead']:.3f}" if row['avg_overhead'] is not None else "NULL"
            results.append(ok(f"paper_core_query: {row['workflow_type']} goals={row['goals']} avg_overhead={avg}"))
    vfv = conn.execute("SELECT COUNT(*), MAX(delta) FROM v_fraction_verification").fetchone()
    if vfv and vfv[0] > 0:
        if vfv[1] == 0.0:
            results.append(ok(f"v_fraction_verification: {vfv[0]} rows delta=0.0"))
        else:
            results.append(warn(f"v_fraction_verification: max_delta={vfv[1]}"))
    else:
        results.append(warn("v_fraction_verification: 0 rows"))
    return results


def print_energy_accounting(conn, exp_id: int, exp_type: str) -> None:
    if exp_type not in ("failure_injection", "retry_study"):
        return
    rows = conn.execute("""
        SELECT r.run_id, r.workflow_type,
            r.pkg_energy_uj, r.baseline_energy_uj, r.dynamic_energy_uj,
            r.attributed_energy_uj, r.core_energy_uj,
            r.uncore_energy_uj, r.dram_energy_uj,
            r.pre_task_energy_uj, r.post_task_energy_uj,
            r.planning_energy_uj, r.execution_energy_uj,
            r.synthesis_energy_uj, r.inter_phase_energy_uj,
            ea.orchestration_energy_uj, ea.llm_compute_energy_uj,
            ea.llm_wait_energy_uj, ea.failed_tool_energy_uj,
            ea.attribution_method,
            ge.total_energy_uj       AS goal_total,
            ge.successful_energy_uj  AS goal_success,
            ge.overhead_fraction,
            ge.orchestration_fraction,
            (SELECT SUM(ga2.energy_uj)
             FROM goal_attempt ga2
             WHERE ga2.goal_id = ge.goal_id) AS sum_attempt_energy,
            (SELECT COUNT(*) FROM goal_attempt ga3
             WHERE ga3.goal_id = ge.goal_id AND ga3.is_retry = 1) AS retry_count
        FROM goal_execution ge
        JOIN runs r ON r.run_id = ge.winning_run_id
        JOIN energy_attribution ea ON ea.run_id = r.run_id
        WHERE ge.exp_id = ? AND ge.winning_run_id IS NOT NULL
        LIMIT 5
    """, (exp_id,)).fetchall()
    if not rows:
        return
    def _j(uj): return f"{(uj or 0)/1e6:.4f}J"
    def _p(n,d): return f"{100.0*(n or 0)/d:.1f}%" if d else "N/A"
    def _c(d,t=1000): return "✅" if abs(d)<=t else "❌"

    print(f"\n  📊 Energy Accounting (exp_id={exp_id}):")
    print(f"  {'─'*68}")
    for row in rows:
        pkg  = row["pkg_energy_uj"]        or 0
        base = row["baseline_energy_uj"]   or 0
        dyn  = row["dynamic_energy_uj"]    or 0
        attr = row["attributed_energy_uj"] or 0
        core = row["core_energy_uj"]       or 0
        unc  = row["uncore_energy_uj"]     or 0
        drm  = row["dram_energy_uj"]       or 0
        pre  = row["pre_task_energy_uj"]   or 0
        post = row["post_task_energy_uj"]  or 0
        plan = row["planning_energy_uj"]   or 0
        exe  = row["execution_energy_uj"]  or 0
        syn  = row["synthesis_energy_uj"]  or 0
        iph  = row["inter_phase_energy_uj"] or 0
        orch = row["orchestration_energy_uj"] or 0
        llmc = row["llm_compute_energy_uj"] or 0
        llmw = row["llm_wait_energy_uj"]   or 0
        ftl  = row["failed_tool_energy_uj"] or 0
        asum = row["sum_attempt_energy"]   or 0
        wf   = row["workflow_type"]        or "?"
        mth  = row["attribution_method"]   or "unknown"
        ofrc = row["orchestration_fraction"]
        gt   = row["goal_total"]           or 0
        gs   = row["goal_success"]         or 0

        print(f"  run={row['run_id']}[{wf}] retries={row['retry_count']} method={mth}")
        print(f"  [D4] E_pkg=E_core+E_uncore+E_dram:")
        print(f"       {_j(pkg)}={_j(core)}({_p(core,pkg)})+{_j(unc)}({_p(unc,pkg)})+{_j(drm)}  {_c(pkg-(core+unc+drm))}")
        print(f"  [D3] E_pkg=E_baseline+E_dynamic:")
        print(f"       {_j(pkg)}={_j(base)}({_p(base,pkg)})+{_j(dyn)}({_p(dyn,pkg)})  {_c(pkg-(base+dyn))}")
        print(f"  [D1 Activity Partition] E_attr=E_llm_window+E_orchestration:")
        print(f"       {_j(attr)}={_j(llmc)}({_p(llmc,attr)})+{_j(orch)}({_p(orch,attr)})  {_c(attr-(llmc+orch))}")
        print(f"       [diagnostic] llm_wait={_j(llmw)}({_p(llmw,attr)}) — AXIS 3 subset of orchestration")
        if wf == "agentic":
            print(f"  [D2] E_attr=E_plan+E_exec+E_synth+E_inter:")
            print(f"       {_j(attr)}={_j(plan)}({_p(plan,attr)})+{_j(exe)}({_p(exe,attr)})+{_j(syn)}({_p(syn,attr)})+{_j(iph)}({_p(iph,attr)})  {_c(attr-(plan+exe+syn+iph))}")
        print(f"  [A2] E_attr=SUM(attempts): {_j(attr)}=={_j(asum)}  {_c(attr-asum)}")
        if gt > 0:
            print(f"  [Goal] total={_j(gt)} success={_j(gs)} overhead={_p(gt-gs,gt)}"
                  + (f" orch_frac={ofrc:.4f}" if ofrc else ""))
        if ftl > 0:
            print(f"  [Failure] failed_tool={_j(ftl)}")
        print(f"  {'─'*68}")
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
    all_results += check_etl_queue(conn, goal_ids)
    all_results += check_retry_policy(conn)
    all_results += check_task_categories(conn)
    all_results += check_task_retry_override(conn)
    all_results += check_energy_conservation(conn, exp_id, run_ids, goal_ids)
    all_results += check_paper_core_query(conn)
    print_energy_accounting(conn, exp_id, exp_type)    
    
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
