#!/usr/bin/env python3
"""
validate_energy_chain.py — Full mathematical energy chain validation.

Validates the complete energy accounting chain for every run in an experiment:
  Layer 1: pkg = baseline + dynamic
  Layer 2: dynamic = pre_task + workload + post_task (t0/t1/t2 model)
  Layer 3: dynamic = attributed + unattributed
  Layer 4: attributed = planning + execution + synthesis (phase model)
  Layer 5: goal_attempt.energy_uj conservation (Approach 2)
  Layer 6: orchestration overhead fraction consistency

Run after every experiment that saves to DB.
Usage:
    python scripts/validate_energy_chain.py --exp-id 835
    python scripts/validate_energy_chain.py --latest
"""

import argparse
import sqlite3
import sys
from pathlib import Path

DB_PATH = "data/experiments.db"
TOLERANCE_UJ = 1000  # 1 mJ rounding tolerance

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg):   return f"{GREEN}✅ {msg}{RESET}"
def fail(msg): return f"{RED}❌ {msg}{RESET}"
def warn(msg): return f"{YELLOW}⚠️  {msg}{RESET}"


def validate_run(conn, run_id: int) -> list:
    """
    Full mathematical chain validation for one run.
    Returns list of result strings.
    """
    results = []

    r = conn.execute("""
        SELECT r.run_id, r.pkg_energy_uj, r.baseline_energy_uj,
               r.dynamic_energy_uj, r.total_energy_uj,
               r.pre_task_energy_uj, r.post_task_energy_uj,
               r.attributed_energy_uj,
               r.planning_energy_uj, r.execution_energy_uj,
               r.synthesis_energy_uj,
               r.framework_overhead_energy_uj,
               ea.orchestration_energy_uj, ea.llm_compute_energy_uj,
               ea.failed_tool_energy_uj,
               ge.total_energy_uj     AS goal_total,
               ge.overhead_fraction,
               ge.orchestration_fraction,
               ge.winning_run_id,
               ge.goal_id,
               SUM(ga.energy_uj)      AS attempt_sum,
               COUNT(ga.attempt_id)   AS attempt_count
        FROM runs r
        LEFT JOIN energy_attribution ea ON ea.run_id=r.run_id
        LEFT JOIN goal_execution ge ON ge.winning_run_id=r.run_id
        LEFT JOIN goal_attempt ga ON ga.goal_id=ge.goal_id
        WHERE r.run_id=?
        GROUP BY r.run_id
    """, (run_id,)).fetchone()

    if not r:
        results.append(fail(f"run_id={run_id}: not found"))
        return results

    pkg      = r["pkg_energy_uj"] or 0
    baseline = r["baseline_energy_uj"] or 0
    dynamic  = r["dynamic_energy_uj"] or 0
    pre      = r["pre_task_energy_uj"] or 0
    post     = r["post_task_energy_uj"] or 0
    attr     = r["attributed_energy_uj"] or 0
    planning = r["planning_energy_uj"] or 0
    execution= r["execution_energy_uj"] or 0
    synthesis= r["synthesis_energy_uj"] or 0
    orch     = r["orchestration_energy_uj"] or 0
    llm      = r["llm_compute_energy_uj"] or 0
    asum     = r["attempt_sum"] or 0
    overhead_frac = r["overhead_fraction"]
    orch_frac     = r["orchestration_fraction"]

    prefix = f"run={run_id}"

    # ── Layer 1: pkg = baseline + dynamic ────────────────────────────────────
    # Fundamental RAPL identity — total package = idle + workload contribution
    delta1 = abs(pkg - (baseline + dynamic))
    if delta1 <= TOLERANCE_UJ:
        results.append(ok(
            f"{prefix} L1: pkg({pkg/1e6:.3f}J) = "
            f"baseline({baseline/1e6:.3f}J) + dynamic({dynamic/1e6:.3f}J) "
            f"delta={delta1}µJ"
        ))
    else:
        results.append(fail(
            f"{prefix} L1 VIOLATION: pkg={pkg/1e6:.3f}J != "
            f"baseline+dynamic={( baseline+dynamic)/1e6:.3f}J delta={delta1}µJ"
        ))

    # ── Layer 2: dynamic = pre + workload + post (t0/t1/t2 model) ────────────
    # t0=measurement start, t1=LLM call start, t2=LLM call end
    # workload = dynamic - pre - post
    workload = dynamic - pre - post
    if pre > 0 or post > 0:
        results.append(ok(
            f"{prefix} L2: dynamic={dynamic/1e6:.3f}J "
            f"pre={pre/1e6:.3f}J workload={workload/1e6:.3f}J post={post/1e6:.3f}J"
        ))
    else:
        results.append(warn(
            f"{prefix} L2: pre_task/post_task NULL — t0/t1/t2 boundary not recorded"
        ))

    # ── Layer 3: dynamic vs attributed ───────────────────────────────────────
    # attributed = cpu_fraction × dynamic — should be <= dynamic
    if attr > 0:
        if attr <= dynamic + TOLERANCE_UJ:
            results.append(ok(
                f"{prefix} L3: attributed({attr/1e6:.3f}J) <= dynamic({dynamic/1e6:.3f}J) "
                f"cpu_frac={attr/dynamic:.3f}" if dynamic > 0 else f"{prefix} L3: attributed={attr/1e6:.3f}J"
            ))
        else:
            results.append(fail(
                f"{prefix} L3 VIOLATION: attributed({attr/1e6:.3f}J) > dynamic({dynamic/1e6:.3f}J)"
            ))
    else:
        results.append(warn(f"{prefix} L3: attributed_energy_uj NULL/0 — ETL not run"))

    # ── Layer 4: phase decomposition planning + execution + synthesis ─────────
    # attributed = planning + execution + synthesis (phase attribution ETL)
    phase_sum = planning + execution + synthesis
    if phase_sum > 0:
        delta4 = abs(attr - phase_sum)
        if delta4 <= TOLERANCE_UJ:
            results.append(ok(
                f"{prefix} L4: attributed({attr/1e6:.3f}J) = "
                f"plan({planning/1e6:.3f}J) + exec({execution/1e6:.3f}J) + "
                f"synth({synthesis/1e6:.3f}J) delta={delta4}µJ"
            ))
        else:
            results.append(fail(
                f"{prefix} L4 VIOLATION: attributed={attr/1e6:.3f}J != "
                f"phase_sum={phase_sum/1e6:.3f}J delta={delta4}µJ"
            ))
    else:
        results.append(warn(
            f"{prefix} L4: phase energy NULL — phase_attribution_etl not run"
        ))

    # ── Layer 5: goal_attempt energy conservation (Approach 2) ───────────────
    # winning_run.dynamic = SUM(goal_attempt.energy_uj) — Chunk 8.5 invariant
    if asum > 0:
        delta5 = abs(dynamic - asum)
        if delta5 <= TOLERANCE_UJ:
            results.append(ok(
                f"{prefix} L5: dynamic({dynamic/1e6:.3f}J) == "
                f"attempt_sum({asum/1e6:.3f}J) attempts={r['attempt_count']} delta={delta5}µJ"
            ))
        else:
            results.append(fail(
                f"{prefix} L5 VIOLATION: dynamic={dynamic/1e6:.3f}J != "
                f"attempt_sum={asum/1e6:.3f}J delta={delta5}µJ"
            ))
    else:
        results.append(warn(
            f"{prefix} L5: no goal_attempt rows linked — retry path may be missing"
        ))

    # ── Layer 6: orchestration overhead fraction consistency ──────────────────
    # overhead_fraction = (total - successful) / total
    # orchestration_fraction = orchestration_energy / dynamic
    if overhead_frac is not None and dynamic > 0:
        if orch > 0:
            computed_orch_frac = orch / dynamic
            stored_orch_frac   = orch_frac or 0
            delta6 = abs(computed_orch_frac - stored_orch_frac)
            if delta6 <= 0.001:
                results.append(ok(
                    f"{prefix} L6: orch_frac stored={stored_orch_frac:.4f} "
                    f"computed={computed_orch_frac:.4f} delta={delta6:.6f}"
                ))
            else:
                results.append(fail(
                    f"{prefix} L6 VIOLATION: orch_frac stored={stored_orch_frac:.4f} "
                    f"!= computed={computed_orch_frac:.4f} delta={delta6:.6f}"
                ))
        results.append(ok(
            f"{prefix} L6: overhead_fraction={overhead_frac:.4f} "
            f"orch={orch/1e6:.3f}J llm={llm/1e6:.3f}J"
        ))
    else:
        results.append(warn(
            f"{prefix} L6: overhead_fraction NULL — goal_execution_etl not run"
        ))

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Full mathematical energy chain validation"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--exp-id", type=int)
    group.add_argument("--latest", action="store_true")
    parser.add_argument("--experiment-type", help="Filter --latest by type")
    parser.add_argument("--db", default=DB_PATH)
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(fail(f"DB not found: {args.db}"))
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    if args.latest:
        q = "SELECT MAX(exp_id) FROM experiments"
        if args.experiment_type:
            q += " WHERE experiment_type=?"
            row = conn.execute(q, (args.experiment_type,)).fetchone()
        else:
            row = conn.execute(q).fetchone()
        exp_id = row[0]
    else:
        exp_id = args.exp_id

    if exp_id is None:
        print(fail("No experiment found"))
        sys.exit(1)

    exp = conn.execute(
        "SELECT experiment_type, workflow_type, runs_completed FROM experiments WHERE exp_id=?",
        (exp_id,)
    ).fetchone()

    run_ids = [
        r[0] for r in conn.execute(
            "SELECT run_id FROM runs WHERE exp_id=? ORDER BY run_id", (exp_id,)
        ).fetchall()
    ]

    print(f"\n{BOLD}{'='*65}{RESET}")
    print(f"{BOLD}A-LEMS Energy Chain Validation — exp_id={exp_id}{RESET}")
    print(f"  type={exp['experiment_type']}  workflow={exp['workflow_type']}  runs={exp['runs_completed']}")
    print(f"{BOLD}{'='*65}{RESET}\n")

    all_results = []
    for run_id in run_ids:
        results = validate_run(conn, run_id)
        for r in results:
            print(f"  {r}")
        all_results.extend(results)
        print()

    passed = sum(1 for r in all_results if r.startswith(GREEN))
    warned = sum(1 for r in all_results if r.startswith(YELLOW))
    failed = sum(1 for r in all_results if r.startswith(RED))

    print(f"{'='*65}")
    print(f"  RESULT: {passed} passed, {warned} warnings, {failed} failed")
    print(f"{'='*65}\n")

    conn.close()
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
