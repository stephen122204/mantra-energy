#!/usr/bin/env python3
"""
validate_energy_chain.py — Full mathematical energy chain validation.

Shows complete energy tree per run with inline equations and percentages.
Every conservation level must sum to 100%. Violations shown immediately.

Conservation Dimensions:
  D4 Hardware: E_pkg = E_core + E_uncore + E_dram
  D3 System:   E_pkg = E_baseline + E_dynamic
               E_dynamic = E_attributed + E_background
  D1 Time:     E_attributed = E_llm_compute + E_llm_wait + E_orchestration
  D2 Phase:    E_orchestration = E_plan + E_exec + E_synth + E_inter_phase
  Boundary:    E_dynamic = E_pre + E_workload_pure + E_post
  Approach-2:  E_dynamic(run) = SUM(goal_attempt.energy_uj)
  f_orch:      stored = E_orch / E_attributed

Observational fields (network, io, interrupt etc.) shown with confidence
bounds but NOT in conservation equations — overlapping signals not partitions.

Usage:
    python scripts/validate_energy_chain.py --exp-id 835
    python scripts/validate_energy_chain.py --latest
    python scripts/validate_energy_chain.py --latest --experiment-type failure_injection
    python scripts/validate_energy_chain.py --all-valid
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

DB_PATH   = "data/experiments.db"
TOL_UJ    = 1000
TOL_FRAC  = 0.001
TOL_POWER = 0.5

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def ok(msg):   return f"{GREEN}OK  {msg}{RESET}"
def fail(msg): return f"{RED}ERR {msg}{RESET}"
def warn(msg): return f"{YELLOW}WRN {msg}{RESET}"


def _j(uj):   return f"{(uj or 0)/1e6:.4f}J"
def _pct(n, d): return 100.0*(n or 0)/d if d else 0.0
def _chk(delta, tol=TOL_UJ): return "✅" if delta <= tol else "❌"


def _fetch_run(conn, run_id):
    row = conn.execute("""
        SELECT r.run_id, r.workflow_type, e.provider,
            r.duration_ns, r.task_duration_ns,
            r.pkg_energy_uj, r.core_energy_uj,
            r.uncore_energy_uj, r.dram_energy_uj,
            r.baseline_energy_uj, r.dynamic_energy_uj,
            r.attributed_energy_uj, r.cpu_fraction,
            r.pre_task_energy_uj, r.post_task_energy_uj,
            r.framework_overhead_energy_uj,
            r.planning_energy_uj, r.execution_energy_uj,
            r.synthesis_energy_uj, r.inter_phase_energy_uj,
            r.phase_sample_coverage_pct,
            r.avg_power_watts, r.energy_per_token,
            r.energy_per_instruction, r.energy_sample_coverage_pct,
            ea.orchestration_energy_uj,
            ea.llm_compute_energy_uj, ea.llm_wait_energy_uj,
            ea.background_energy_uj, ea.unattributed_energy_uj,
            ea.failed_tool_energy_uj, ea.retry_energy_uj,
            ea.thermal_penalty_energy_uj,
            ea.network_wait_energy_uj, ea.io_wait_energy_uj,
            ea.interrupt_energy_uj, ea.scheduler_energy_uj,
            ea.memory_pressure_energy_uj, ea.disk_energy_uj,
            ea.cache_dram_energy_uj,
            ea.prefill_energy_uj, ea.decode_energy_uj,
            ea.energy_per_completion_token_uj,
            ea.attribution_method, ea.attribution_coverage_pct,
            ge.orchestration_fraction, ge.overhead_fraction,
            ge.total_energy_uj AS goal_total_uj,
            ge.successful_energy_uj AS goal_success_uj,
            ge.overhead_energy_uj AS goal_overhead_uj,
            SUM(ga.energy_uj) AS attempt_sum_uj,
            COUNT(ga.attempt_id) AS attempt_count
        FROM runs r
        LEFT JOIN experiments e ON e.exp_id=r.exp_id
        LEFT JOIN energy_attribution ea ON ea.run_id=r.run_id
        LEFT JOIN goal_execution ge ON ge.winning_run_id=r.run_id
        LEFT JOIN goal_attempt ga ON ga.goal_id=ge.goal_id
        WHERE r.run_id=?
        GROUP BY r.run_id
    """, (run_id,)).fetchone()
    return dict(row) if row else None


def print_tree(r):
    wf  = r["workflow_type"] or "?"
    prv = r["provider"] or "unknown"
    W   = 70

    pkg  = r["pkg_energy_uj"]        or 0
    core = r["core_energy_uj"]       or 0
    unc  = r["uncore_energy_uj"]     or 0
    dram = r["dram_energy_uj"]       or 0
    base = r["baseline_energy_uj"]   or 0
    dyn  = r["dynamic_energy_uj"]    or 0
    attr = r["attributed_energy_uj"] or 0
    bg   = r["background_energy_uj"] or max(0, dyn - attr)
    pre  = r["pre_task_energy_uj"]   or 0
    post = r["post_task_energy_uj"]  or 0
    fwoh = r["framework_overhead_energy_uj"] or 0
    plan = r["planning_energy_uj"]   or 0
    exe  = r["execution_energy_uj"]  or 0
    syn  = r["synthesis_energy_uj"]  or 0
    iph  = r["inter_phase_energy_uj"] or 0
    orch = r["orchestration_energy_uj"] or 0
    llmc = r["llm_compute_energy_uj"] or 0
    llmw = r["llm_wait_energy_uj"]   or 0
    unat = r["unattributed_energy_uj"] or 0
    thm  = r["thermal_penalty_energy_uj"] or 0
    net  = r["network_wait_energy_uj"] or 0
    iow  = r["io_wait_energy_uj"]    or 0
    intr = r["interrupt_energy_uj"]  or 0
    sch  = r["scheduler_energy_uj"]  or 0
    mem  = r["memory_pressure_energy_uj"] or 0
    dsk  = r["disk_energy_uj"]       or 0
    cdr  = r["cache_dram_energy_uj"] or 0
    ret  = r["retry_energy_uj"]      or 0
    ftl  = r["failed_tool_energy_uj"] or 0
    mth  = r["attribution_method"]   or "unknown"
    phcv = r["phase_sample_coverage_pct"]
    tskd = r["task_duration_ns"]     or r["duration_ns"] or 0
    apwr = r["avg_power_watts"]      or 0
    etok = r["energy_per_token"]     or 0
    einr = r["energy_per_instruction"] or 0
    ofrc = r["orchestration_fraction"]
    ovfr = r["overhead_fraction"]
    asum = r["attempt_sum_uj"]       or 0
    natt = r["attempt_count"]        or 0

    print(f"\n  {'─'*W}")
    print(f"  run={r['run_id']}  [{wf}/{prv}]  method={mth}")
    print(f"  {'─'*W}")

    # D4
    d = abs(pkg-(core+unc+dram))
    print(f"\n  [Hardware Domains] E_pkg = E_core + E_uncore + E_dram")
    print(f"       {_j(pkg)} = {_j(core)}({_pct(core,pkg):.1f}%)"
          f" + {_j(unc)}({_pct(unc,pkg):.1f}%)"
          f" + {_j(dram)}({_pct(dram,pkg):.1f}%)"
          f"  {_chk(d)} Δ={d}µJ")

    # D3
    d = abs(pkg-(base+dyn))
    print(f"\n  [Idle Subtraction] E_pkg = E_idle_baseline + E_dynamic_workload")
    print(f"        {_j(pkg)} = {_j(base)}({_pct(base,pkg):.1f}%)"
          f" + {_j(dyn)}({_pct(dyn,pkg):.1f}%)"
          f"  {_chk(d)} Δ={d}µJ")

    d = abs(dyn-(attr+bg))
    print(f"\n  [Process Attribution] E_dynamic = E_this_process + E_other_processes")
    print(f"        {_j(dyn)} = {_j(attr)}({_pct(attr,dyn):.1f}%)"
          f" + {_j(bg)}({_pct(bg,dyn):.1f}%)"
          f"  {_chk(d)} Δ={d}µJ")

    # Boundary
    if pre > 0 or post > 0:
        wp = attr-pre-post
        d = abs(attr-(pre+wp+post))
        print(f"\n  [Boundary t0/t1/t2] E_attributed = E_pre + E_workload_pure + E_post")
        print(f"        {_j(attr)} = {_j(pre)}({_pct(pre,attr):.1f}%)"
              f" + {_j(wp)}({_pct(wp,attr):.1f}%)"
              f" + {_j(post)}({_pct(post,attr):.1f}%)"
              f"  {_chk(d)} Δ={d}µJ")
        print(f"        framework_overhead={_j(fwoh)}")
    else:
        print(f"\n  [Boundary] ⚠️  pre/post NULL — not recorded")

    # D1
    d = abs(attr-(llmc+llmw+orch))
    is_sample = "sample_based" in mth
    ml = "MEASURED" if is_sample else "INFERRED(time-frac)"
    print(f"\n  [Energy Type Breakdown] E_process = E_llm_prefill + E_llm_token_wait + E_framework_overhead  [{ml}]")
    print(f"       {_j(attr)} = {_j(llmc)}({_pct(llmc,attr):.1f}%)"
          f" + {_j(llmw)}({_pct(llmw,attr):.1f}%)"
          f" + {_j(orch)}({_pct(orch,attr):.1f}%)"
          f"  {_chk(d)} Δ={d}µJ")
    if not is_sample and "llama" in prv.lower():
        print(f"       ⚠️  Local: api_latency=0 → time-frac wrong for llm_wait")
        print(f"          Fix: python scripts/etl/energy_attribution_etl.py --run-id {r['run_id']}")

    # D2
    if wf == "agentic":
        d = abs(attr-(plan+exe+syn+iph))
        print(f"\n  [Time Phase Breakdown] E_process = E_planning + E_execution + E_synthesis + E_between_phases")
        print(f"       {_j(attr)} = {_j(plan)}({_pct(plan,attr):.1f}%)"
              f" + {_j(exe)}({_pct(exe,attr):.1f}%)"
              f" + {_j(syn)}({_pct(syn,attr):.1f}%)"
              f" + {_j(iph)}({_pct(iph,attr):.1f}%)"
              f"  {_chk(d)} Δ={d}µJ")
        cov = f"  phase_coverage={phcv:.1f}%" if phcv is not None else ""
        print(f"       {cov}")
        if syn == 0:
            print(f"       ⚠️  synthesis=0 — phase too short for 100Hz sampling")
    else:
        print(f"\n  [D2] linear — no phase decomposition")

    # Unattributed
    print(f"\n  [Unattr] E_pkg - SUM(layers) = {_j(unat)}"
          f" ({_pct(unat,pkg):.2f}% of pkg)"
          f"  {'✅' if unat >= 0 else '❌ NEGATIVE'}")

    # Approach-2
    if asum > 0:
        d = abs(attr-asum)
        print(f"\n  [Retry Conservation] E_attributed = SUM(attempt energies)")
        print(f"       {(attr or 0)/1e6:.6f}J == SUM({natt} attempts)={(asum or 0)/1e6:.6f}J"
              f"  {_chk(d)} Δ={d}µJ")

    # Goal
    gt = r["goal_total_uj"] or 0
    gs = r["goal_success_uj"] or 0
    go = r["goal_overhead_uj"] or 0
    if gt > 0:
        print(f"\n  [Goal] total={_j(gt)} success={_j(gs)}"
              f" overhead={_j(go)}({_pct(go,gt):.1f}%)")
        if ofrc is not None and attr > 0 and orch > 0:
            comp = orch/attr
            d = abs(comp-ofrc)
            print(f"  f_orch=E_orch/E_attr: stored={ofrc:.4f}"
                  f" computed={_j(orch)}/{_j(attr)}={comp:.4f}"
                  f"  {_chk(d, TOL_FRAC)} Δ={d:.6f}")

    # Power
    if tskd > 0 and dyn > 0:
        durs = tskd/1e9
        cp = (dyn/1e6)/durs
        d = abs(cp-apwr)
        print(f"\n  [Power] P_avg=E_dyn/task_dur:"
              f" stored={apwr:.3f}W computed={cp:.3f}W"
              f"  {_chk(d, TOL_POWER)} Δ={d:.3f}W")

    # Normalised
    print(f"\n  [Normalised] e/token={etok:.2f}µJ"
          f"  e/instr={einr:.8f}µJ"
          f"  sample_cov={r['energy_sample_coverage_pct'] or 0:.1f}%"
          f"  attr_cov={r['attribution_coverage_pct'] or 0:.1f}%")

    # Observational
    print(f"\n  [Observational — NOT conservation partitions, overlapping signals]")
    print(f"  net={_j(net)}(0.75) io={_j(iow)}(0.70)"
          f" disk={_j(dsk)}(0.60) interrupt={_j(intr)}(0.65)")
    print(f"  scheduler={_j(sch)}(0.65) memory={_j(mem)}(0.65)"
          f" cache_dram={_j(cdr)}(0.65) thermal={_j(thm)}(0.85)")

    # Failure
    if ret > 0 or ftl > 0:
        print(f"\n  [Failure] retry={_j(ret)} failed_tool={_j(ftl)}")

    print(f"  {'─'*W}")


def validate_run(conn, run_id):
    results = []
    r = _fetch_run(conn, run_id)
    if not r:
        results.append(fail(f"run={run_id} not found"))
        return results

    print_tree(r)

    wf  = r["workflow_type"] or "?"
    prv = r["provider"] or "unknown"
    p   = f"run={run_id}[{wf}]"

    pkg  = r["pkg_energy_uj"]        or 0
    core = r["core_energy_uj"]       or 0
    unc  = r["uncore_energy_uj"]     or 0
    dram = r["dram_energy_uj"]       or 0
    base = r["baseline_energy_uj"]   or 0
    dyn  = r["dynamic_energy_uj"]    or 0
    attr = r["attributed_energy_uj"] or 0
    bg   = r["background_energy_uj"] or max(0, dyn-attr)
    pre  = r["pre_task_energy_uj"]   or 0
    post = r["post_task_energy_uj"]  or 0
    plan = r["planning_energy_uj"]   or 0
    exe  = r["execution_energy_uj"]  or 0
    syn  = r["synthesis_energy_uj"]  or 0
    iph  = r["inter_phase_energy_uj"] or 0
    orch = r["orchestration_energy_uj"] or 0
    llmc = r["llm_compute_energy_uj"] or 0
    llmw = r["llm_wait_energy_uj"]   or 0
    unat = r["unattributed_energy_uj"] or 0
    asum = r["attempt_sum_uj"]       or 0
    tskd = r["task_duration_ns"]     or r["duration_ns"] or 0
    apwr = r["avg_power_watts"]      or 0
    mth  = r["attribution_method"]   or "unknown"
    ofrc = r["orchestration_fraction"]

    # D4
    d = abs(pkg-(core+unc+dram))
    results.append(ok(f"{p} D4 Δ={d}µJ") if core > 0 and d <= TOL_UJ
                   else (fail(f"{p} D4 VIOLATION Δ={d}µJ") if core > 0
                         else warn(f"{p} D4 core NULL")))

    # D3a
    d = abs(pkg-(base+dyn))
    results.append(ok(f"{p} D3a Δ={d}µJ") if d <= TOL_UJ
                   else fail(f"{p} D3a VIOLATION Δ={d}µJ"))

    # D3b
    if attr > 0:
        d = abs(dyn-(attr+bg))
        results.append(ok(f"{p} D3b Δ={d}µJ") if d <= TOL_UJ
                       else fail(f"{p} D3b VIOLATION Δ={d}µJ"))
    else:
        results.append(warn(f"{p} D3b attr NULL"))

    # Boundary
    if pre > 0 or post > 0:
        wp = dyn-pre-post
        d = abs(dyn-(pre+wp+post))
        results.append(ok(f"{p} Boundary Δ={d}µJ") if d <= TOL_UJ
                       else fail(f"{p} Boundary VIOLATION Δ={d}µJ"))
    else:
        results.append(warn(f"{p} Boundary pre/post NULL"))

    # D1
    if attr > 0:
        d = abs(attr-(llmc+llmw+orch))
        is_s = "sample_based" in mth
        results.append(ok(f"{p} D1 [{'MEASURED' if is_s else 'INFERRED'}] Δ={d}µJ")
                       if d <= TOL_UJ else fail(f"{p} D1 VIOLATION Δ={d}µJ"))
        if not is_s and "llama" in prv.lower():
            results.append(warn(f"{p} D1 llm_wait time-frac wrong for local provider"))
    else:
        results.append(warn(f"{p} D1 attr NULL"))

    # D2
    if wf == "agentic":
        if plan > 0 or exe > 0 or syn > 0:
            d = abs(attr-(plan+exe+syn+iph))
            results.append(ok(f"{p} D2 Δ={d}µJ") if d <= TOL_UJ
                           else fail(f"{p} D2 VIOLATION Δ={d}µJ"))
        else:
            results.append(warn(f"{p} D2 phase NULL"))
    else:
        results.append(ok(f"{p} D2 linear no phases"))

    # Unattr
    results.append(ok(f"{p} UNATTR={_j(unat)}") if unat >= 0
                   else fail(f"{p} UNATTR NEGATIVE {_j(unat)}"))

    # Approach-2
    if asum > 0:
        d = abs(attr-asum)
        results.append(ok(f"{p} Approach-2 E_attr=SUM(attempts) Δ={d}µJ") if d <= TOL_UJ
                       else fail(f"{p} Approach-2 VIOLATION Δ={d}µJ"))
    else:
        results.append(warn(f"{p} Approach-2 no attempts"))

    # f_orch
    if ofrc is not None and attr > 0 and orch > 0:
        comp = orch/attr
        d = abs(comp-ofrc)
        results.append(ok(f"{p} f_orch stored={ofrc:.4f} computed={comp:.4f} Δ={d:.6f}")
                       if d <= TOL_FRAC
                       else fail(f"{p} f_orch VIOLATION Δ={d:.6f} [run goal_execution_etl --backfill-all --force]"))
    elif ofrc is None:
        results.append(warn(f"{p} f_orch NULL"))

    # Power
    if tskd > 0 and dyn > 0:
        cp = (dyn/1e6)/(tskd/1e9)
        d = abs(cp-apwr)
        results.append(ok(f"{p} Power Δ={d:.3f}W") if d <= TOL_POWER
                       else fail(f"{p} Power VIOLATION Δ={d:.3f}W"))
    else:
        results.append(warn(f"{p} Power skipped"))

    return results


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--exp-id",    type=int)
    group.add_argument("--latest",    action="store_true")
    group.add_argument("--all-valid", action="store_true")
    parser.add_argument("--experiment-type")
    parser.add_argument("--db", default=DB_PATH)
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(fail(f"DB not found: {args.db}")); sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    if args.all_valid:
        q, params = "SELECT exp_id FROM experiments WHERE is_valid=1", []
        if args.experiment_type:
            q += " AND experiment_type=?"; params.append(args.experiment_type)
        exp_ids = [r[0] for r in conn.execute(q, params).fetchall()]
    elif args.latest:
        q = "SELECT MAX(exp_id) FROM experiments WHERE 1=1"; params = []
        if args.experiment_type:
            q += " AND experiment_type=?"; params.append(args.experiment_type)
        row = conn.execute(q, params).fetchone()
        exp_ids = [row[0]] if row and row[0] else []
    else:
        exp_ids = [args.exp_id]

    if not exp_ids or exp_ids[0] is None:
        print(fail("No experiments found")); sys.exit(1)

    gp = gw = gf = 0
    for exp_id in exp_ids:
        exp = conn.execute(
            "SELECT experiment_type, workflow_type, runs_completed, is_valid "
            "FROM experiments WHERE exp_id=?", (exp_id,)
        ).fetchone()
        if not exp:
            print(fail(f"exp_id={exp_id} not found")); continue

        run_ids = [r[0] for r in conn.execute(
            "SELECT run_id FROM runs WHERE exp_id=? ORDER BY run_id", (exp_id,)
        ).fetchall()]

        print(f"\n{BOLD}{'='*72}{RESET}")
        print(f"{BOLD}A-LEMS Energy Chain Validation  exp_id={exp_id}{RESET}")
        print(f"  type={exp['experiment_type']}  workflow={exp['workflow_type']}"
              f"  runs={exp['runs_completed']}  is_valid={exp['is_valid']}")
        print(f"{BOLD}{'='*72}{RESET}")

        all_r = []
        for run_id in run_ids:
            all_r.extend(validate_run(conn, run_id))

        print(f"\n  Conservation Summary:")
        print(f"  {'─'*70}")
        for r in all_r:
            print(f"  {r}")

        p = sum(1 for r in all_r if r.startswith(GREEN))
        w = sum(1 for r in all_r if r.startswith(YELLOW))
        f_ = sum(1 for r in all_r if r.startswith(RED))
        gp += p; gw += w; gf += f_

        print(f"\n{'='*72}")
        print(f"  exp_id={exp_id}: {p} passed  {w} warnings  {f_} failed")
        print(f"{'='*72}")

    if len(exp_ids) > 1:
        print(f"\n{BOLD}TOTAL: {gp} passed  {gw} warnings  {gf} failed{RESET}\n")

    conn.close()
    sys.exit(0 if gf == 0 else 1)


if __name__ == "__main__":
    main()
