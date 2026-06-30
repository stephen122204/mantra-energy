#!/usr/bin/env python3
"""
validate_energy_chain.py — Platform-aware energy chain validation.

Validates the A-LEMS measurement DAG conservation invariants per run.
Works on all platforms: x86/RAPL, ARM/GN100/SPBM, macOS/IOKit.
Platform is detected at runtime from the DB — no flags needed.

Conservation Layers (renamed from D1-D4 for clarity):

  DOMAIN-PARTITION  Hardware domain decomposition
    x86:  pkg = core + uncore + dram  (RAPL, exact)
    ARM:  pkg >= cpu_p + cpu_e + gpu  (SPBM, residual = unmetered fabric)
    macOS: LIMITED (no DRAM domain)

  IDLE-SPLIT        pkg = idle_baseline + dynamic_workload

  PROC-ATTR         dynamic = this_process + background
                    (cpu_fraction x dynamic = attributed)

  ACTIVITY-DECOMP   attributed = llm_window + orchestration  [D1]
                    Two-term exact partition.

  PHASE-PARTITION   attributed = planning + execution + synthesis + inter_phase  [D2]
                    Parallel view to ACTIVITY-DECOMP. Same denominator.

  GOAL-AGGREGATION  goal_energy = SUM(attempt energies including failed)  [Approach-2]

  GPU-C1            pkg >= cpu_p + cpu_e + gpu_spbm + dla  (ARM only)
                    Residual = CMN-700 mesh + L3 + mem controllers (~30%)

  GPU-C2            integrated(dc_input) >= pkg  (ARM only, cross-source)
                    Difference = off-die power (LPDDR5X, NVMe, fans, VRM)

  GPU-C3            gpu_spbm >= gpu_dcgm  (ARM only, cross-source)
                    Difference = NVLink-C2C + GPU memory interface

Cross-tabulation (CROSS-TAB):
  ACTIVITY-DECOMP x PHASE-PARTITION = 2x4 joint distribution
  Marginals must recover each projection exactly.

Usage:
  python scripts/validate_energy_chain.py --exp-id 144
  python scripts/validate_energy_chain.py --latest
  python scripts/validate_energy_chain.py --all-valid
  python scripts/validate_energy_chain.py --run-id 1378
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

from scripts.tools.path_loader import get_alems_db_path
DB_PATH = get_alems_db_path()

TOL_UJ    = 1000       # 1 mJ tolerance for exact invariants
TOL_FRAC  = 0.001      # 0.1% tolerance for fraction checks
TOL_POWER = 0.5        # 0.5W tolerance for power checks
TOL_C1_PCT = 60.0      # C1 residual >60% is anomalous (expected ~30%)
TOL_C2_PCT = 99.0      # C2 board overhead >99% is implausible
TOL_C3_RATIO = 10.0    # C3 ratio >10x is anomalous (expected 2-3x)

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def ok(msg):   return f"{GREEN}OK  {msg}{RESET}"
def fail(msg): return f"{RED}ERR {msg}{RESET}"
def warn(msg): return f"{YELLOW}WRN {msg}{RESET}"
def info(msg): return f"{BLUE}INF {msg}{RESET}"


def _j(uj):
    # type: (object) -> str
    return f"{(uj or 0)/1e6:.4f}J"


def _pct(n, d):
    # type: (object, object) -> float
    return 100.0 * (n or 0) / d if d else 0.0


def _chk(delta, tol=TOL_UJ):
    # type: (float, float) -> str
    return "OK" if abs(delta) <= tol else "ERR"


def _detect_platform(conn, run_id):
    # type: (sqlite3.Connection, int) -> str
    """
    Detect platform from DB data for this run.
    Returns: 'arm_spbm', 'x86_rapl', 'macos_iokit', 'unknown'
    Platform-detection never fails — falls back to 'unknown'.
    """
    # Check energy_measurement_mode in runs table
    row = conn.execute(
        "SELECT energy_measurement_mode FROM runs WHERE run_id=?",
        (run_id,)
    ).fetchone()
    if row and row[0]:
        mode = (row[0] or "").lower()
        if "spbm" in mode:
            return "arm_spbm"
        if "measured" in mode or "rapl" in mode:
            return "x86_rapl"
        if "iokit" in mode:
            return "macos_iokit"

    # Fallback: check if SPBM data exists for this run
    spbm_row = conn.execute("""
        SELECT COUNT(*) FROM energy_sample_domains esd
        JOIN energy_domains ed ON ed.domain_id = esd.domain_id
        WHERE esd.run_id = ? AND ed.name = 'PACKAGE'
    """, (run_id,)).fetchone()
    if spbm_row and spbm_row[0] > 0:
        return "arm_spbm"

    # Fallback: check if RAPL energy_samples exist
    rapl_row = conn.execute(
        "SELECT COUNT(*) FROM energy_samples WHERE run_id=?",
        (run_id,)
    ).fetchone()
    if rapl_row and rapl_row[0] > 0:
        return "x86_rapl"

    return "unknown"


def _get_spbm_domain_energy(conn, run_id, domain_name):
    # type: (sqlite3.Connection, int, str) -> Optional[float]
    """Sum energy_uj for a named SPBM domain from energy_sample_domains."""
    row = conn.execute("""
        SELECT COALESCE(SUM(esd.energy_uj), 0), COUNT(*)
        FROM energy_sample_domains esd
        JOIN energy_domains ed ON ed.domain_id = esd.domain_id
        WHERE esd.run_id = ? AND ed.name = ?
    """, (run_id, domain_name)).fetchone()
    return float(row[0]) if row and row[1] > 0 else None


def _get_rail_energy(conn, run_id, rail_name):
    # type: (sqlite3.Connection, int, str) -> Optional[float]
    """Integrate power_mw x interval_ns for a named power rail."""
    row = conn.execute("""
        SELECT COALESCE(SUM(ps.power_mw * ps.interval_ns / 1000000.0), 0), COUNT(*)
        FROM power_rail_samples ps
        JOIN power_rails pr ON pr.rail_id = ps.rail_id
        WHERE ps.run_id = ? AND pr.rail_name = ?
    """, (run_id, rail_name)).fetchone()
    return float(row[0]) if row and row[1] > 0 else None


def _get_gpu_dcgm_energy(conn, run_id):
    # type: (sqlite3.Connection, int) -> Optional[float]
    """Sum GPU energy from gpu_samples (DCGM field 156)."""
    row = conn.execute("""
        SELECT COALESCE(SUM(energy_uj), 0), COUNT(*)
        FROM gpu_samples
        WHERE run_id = ? AND energy_uj IS NOT NULL AND energy_uj > 0
    """, (run_id,)).fetchone()
    return float(row[0]) if row and row[1] > 0 else None


def _fetch_run(conn, run_id):
    # type: (sqlite3.Connection, int) -> Optional[dict]
    """Fetch all run data needed for validation."""
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
            r.gpu_total_energy_uj, r.gpu_dynamic_energy_uj,
            r.gpu_spbm_total_uj, r.gpu_attribution_method,
            r.energy_measurement_mode,
            ea.orchestration_energy_uj,
            ea.llm_compute_energy_uj, ea.llm_wait_energy_uj,
            ea.background_energy_uj, ea.unattributed_energy_uj,
            ea.failed_tool_energy_uj, ea.retry_energy_uj,
            ea.thermal_penalty_energy_uj,
            ea.prefill_energy_uj, ea.decode_energy_uj,
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
        LEFT JOIN goal_execution ge ON COALESCE(ge.winning_run_id, ge.first_run_id)=r.run_id
        LEFT JOIN goal_attempt ga ON ga.goal_id=ge.goal_id
        WHERE r.run_id=?
        GROUP BY r.run_id
    """, (run_id,)).fetchone()
    return dict(row) if row else None


def _print_tree(r, platform, spbm=None):
    # type: (dict, str, Optional[dict]) -> None
    """Print the full energy chain tree for one run."""
    wf  = r["workflow_type"] or "?"
    prv = r["provider"] or "unknown"
    mth = r["attribution_method"] or "unknown"
    W   = 72

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
    phcv = r["phase_sample_coverage_pct"]
    tskd = r["task_duration_ns"]     or r["duration_ns"] or 0
    apwr = r["avg_power_watts"]      or 0
    etok = r["energy_per_token"]     or 0
    einr = r["energy_per_instruction"] or 0
    ofrc = r["orchestration_fraction"]
    asum = r["attempt_sum_uj"]       or 0
    natt = r["attempt_count"]        or 0
    ret  = r["retry_energy_uj"]      or 0
    ftl  = r["failed_tool_energy_uj"] or 0
    unat = r["unattributed_energy_uj"] or 0

    print(f"\n  {'─'*W}")
    print(f"  run={r['run_id']}  [{wf}/{prv}]  platform={platform}  method={mth}")
    print(f"  {'─'*W}")

    # DOMAIN-PARTITION
    if platform == "x86_rapl":
        d = abs(pkg - (core + unc + dram))
        has_domains = core > 0
        status = _chk(d) if has_domains else "WRN"
        detail = (f"{_j(core)}({_pct(core,pkg):.1f}%)"
                  f" + {_j(unc)}({_pct(unc,pkg):.1f}%)"
                  f" + {_j(dram)}({_pct(dram,pkg):.1f}%)")
        print(f"\n  [DOMAIN-PARTITION / x86 RAPL]")
        print(f"  E_pkg = E_core + E_uncore + E_dram")
        print(f"  {_j(pkg)} = {detail}  [{status}] delta={d}µJ")

    elif platform == "arm_spbm" and spbm:
        pkg_s    = spbm.get("pkg_uj") or 0
        cpu_p    = spbm.get("cpu_p_uj") or 0
        cpu_e    = spbm.get("cpu_e_uj") or 0
        gpu_spbm = spbm.get("gpu_spbm_uj") or 0
        dla      = spbm.get("dla_uj") or 0
        residual = spbm.get("soc_residual_uj") or 0
        c1_pct   = spbm.get("c1_residual_pct") or 0
        print(f"\n  [DOMAIN-PARTITION / ARM SPBM — C1 intra-source]")
        print(f"  E_pkg >= E_cpu_p + E_cpu_e + E_gpu_spbm + E_dla")
        print(f"  {_j(pkg_s)} >= {_j(cpu_p)} + {_j(cpu_e)} + {_j(gpu_spbm)} + {_j(dla)}")
        print(f"  Residual (unmetered fabric) = {_j(residual)} ({c1_pct:.1f}%)")
        print(f"  [C1: {spbm.get('C1','?')}] Expected ~30% residual (CMN-700 mesh, L3, mem ctrl)")

        # GPU-C2: Wall conservation
        dc_in = spbm.get("dc_input_uj") or 0
        board = spbm.get("board_overhead_uj") or 0
        c2_pct = spbm.get("C2_board_pct") or 0
        if dc_in > 0:
            print(f"\n  [GPU-C2 / Wall Conservation — cross-source ML0->ML1]")
            print(f"  E_dc_input >= E_pkg (off-die = LPDDR5X + NVMe + USB + fans + VRM)")
            print(f"  {_j(dc_in)} >= {_j(pkg_s)}")
            print(f"  Off-die power = {_j(board)} ({c2_pct:.1f}%)")
            print(f"  [C2: {spbm.get('C2','?')}] Note: includes AC-DC adapter losses")

        # GPU-C3: Cross-interface conservation
        gpu_dcgm = spbm.get("gpu_dcgm_uj") or 0
        c2c      = spbm.get("nvlink_c2c_uj") or 0
        c3_ratio = spbm.get("C3_ratio") or 0
        if gpu_spbm > 0 and gpu_dcgm > 0:
            print(f"\n  [GPU-C3 / Cross-Interface — cross-source ML1->ML2]")
            print(f"  E_gpu_spbm >= E_gpu_dcgm (diff = NVLink-C2C + GPU memory + VRM)")
            print(f"  {_j(gpu_spbm)} >= {_j(gpu_dcgm)}")
            print(f"  NVLink-C2C energy = {_j(c2c)} (ratio={c3_ratio:.2f}x)")
            print(f"  [C3: {spbm.get('C3','?')}] Expected 2-3x for inference workloads")
    else:
        print(f"\n  [DOMAIN-PARTITION] platform={platform} — limited or unknown")

    # IDLE-SPLIT
    d = abs(pkg - (base + dyn))
    print(f"\n  [IDLE-SPLIT] E_pkg = E_idle_baseline + E_dynamic_workload")
    print(f"  {_j(pkg)} = {_j(base)}({_pct(base,pkg):.1f}%)"
          f" + {_j(dyn)}({_pct(dyn,pkg):.1f}%)"
          f"  [{_chk(d)}] delta={d}µJ")

    # PROC-ATTR
    d = abs(dyn - (attr + bg))
    print(f"\n  [PROC-ATTR] E_dynamic = E_this_process + E_background")
    print(f"  {_j(dyn)} = {_j(attr)}({_pct(attr,dyn):.1f}%)"
          f" + {_j(bg)}({_pct(bg,dyn):.1f}%)"
          f"  [{_chk(d)}] delta={d}µJ")

    # Boundary
    if pre > 0 or post > 0:
        wp = attr - pre - post
        d = abs(attr - (pre + wp + post))
        print(f"\n  [Boundary t0/t1/t2] E_attributed = E_pre + E_work + E_post")
        print(f"  {_j(attr)} = {_j(pre)}({_pct(pre,attr):.1f}%)"
              f" + {_j(wp)}({_pct(wp,attr):.1f}%)"
              f" + {_j(post)}({_pct(post,attr):.1f}%)"
              f"  [{_chk(d)}] delta={d}µJ")
        print(f"  framework_overhead={_j(fwoh)}")
    else:
        print(f"\n  [Boundary] pre/post NULL — framework_overhead={_j(fwoh)}")

    # ACTIVITY-DECOMP (D1)
    d = abs(attr - (llmc + orch))
    is_sample = "sample_based" in mth
    ml = "MEASURED" if is_sample else "INFERRED(time-frac)"
    print(f"\n  [ACTIVITY-DECOMP] E_attributed = E_llm_window + E_orchestration  [{ml}]")
    print(f"  {_j(attr)} = {_j(llmc)}({_pct(llmc,attr):.1f}%)"
          f" + {_j(orch)}({_pct(orch,attr):.1f}%)"
          f"  [{_chk(d)}] delta={d}µJ")

    pref = r.get("prefill_energy_uj") or 0
    dec  = r.get("decode_energy_uj")  or 0
    if pref > 0 or dec > 0:
        print(f"  E_prefill={_j(pref)}({_pct(pref,attr):.1f}%)"
              f"  E_decode={_j(dec)}({_pct(dec,attr):.1f}%)"
              f"  [MEASURED from timestamps]")
    print(f"  E_llm_wait={_j(llmw)} [DIAGNOSTIC — subset of E_orchestration]")

    # PHASE-PARTITION (D2)
    if wf == "agentic":
        d = abs(attr - (plan + exe + syn + iph))
        print(f"\n  [PHASE-PARTITION] E_attributed = plan+exec+synth+inter  [parallel to ACTIVITY-DECOMP]")
        print(f"  {_j(attr)} = {_j(plan)}({_pct(plan,attr):.1f}%)"
              f" + {_j(exe)}({_pct(exe,attr):.1f}%)"
              f" + {_j(syn)}({_pct(syn,attr):.1f}%)"
              f" + {_j(iph)}({_pct(iph,attr):.1f}%)"
              f"  [{_chk(d)}] delta={d}µJ")
        cov = f"phase_coverage={phcv:.1f}%" if phcv is not None else "phase_coverage=NULL"
        print(f"  {cov}")
        if syn == 0 and platform == "arm_spbm":
            print(f"  WRN synthesis=0 — phase too short for 10Hz SPBM sampling")
        elif syn == 0:
            print(f"  WRN synthesis=0 — phase too short for sampling")

        # CROSS-TAB preview
        if llmc > 0 and plan > 0:
            print(f"\n  [CROSS-TAB preview — ACTIVITY-DECOMP x PHASE-PARTITION]")
            print(f"  Row marginals (ACTIVITY): llm={_j(llmc)} orch={_j(orch)}")
            print(f"  Col marginals (PHASE): plan={_j(plan)} exec={_j(exe)}"
                  f" synth={_j(syn)} inter={_j(iph)}")
            print(f"  Grand total: {_j(attr)}")
    else:
        print(f"\n  [PHASE-PARTITION] linear run — no phase decomposition")

    # GOAL-AGGREGATION (Approach-2)
    if asum > 0:
        d = abs(attr - asum)
        print(f"\n  [GOAL-AGGREGATION] E_attributed = SUM(attempt energies)")
        print(f"  {attr/1e6:.6f}J == SUM({natt} attempts)={asum/1e6:.6f}J"
              f"  [{_chk(d)}] delta={d}µJ")

    # Goal metrics
    gt = r["goal_total_uj"] or 0
    gs = r["goal_success_uj"] or 0
    go = r["goal_overhead_uj"] or 0
    if gt > 0:
        print(f"\n  [Goal] total={_j(gt)} success={_j(gs)}"
              f" overhead={_j(go)}({_pct(go,gt):.1f}%)")
        if ofrc is not None and attr > 0 and orch > 0:
            comp = orch / attr
            d = abs(comp - ofrc)
            print(f"  f_orch stored={ofrc:.4f} computed={comp:.4f}"
                  f"  [{_chk(d, TOL_FRAC)}] delta={d:.6f}")

    # Power check
    if tskd > 0 and dyn > 0:
        durs = tskd / 1e9
        cp = (dyn / 1e6) / durs
        d = abs(cp - apwr)
        print(f"\n  [Power] P_avg=E_dyn/task_dur:"
              f" stored={apwr:.3f}W computed={cp:.3f}W"
              f"  [{_chk(d, TOL_POWER)}] delta={d:.3f}W")

    # Normalised
    print(f"\n  [Normalised] e/token={etok:.2f}µJ"
          f"  e/instr={einr:.8f}µJ"
          f"  sample_cov={r['energy_sample_coverage_pct'] or 0:.1f}%"
          f"  attr_cov={r['attribution_coverage_pct'] or 0:.1f}%")

    # Failure events
    if ret > 0 or ftl > 0:
        print(f"\n  [Failure] retry={_j(ret)} failed_tool={_j(ftl)}")

    print(f"  {'─'*W}")


def validate_run(conn, run_id):
    # type: (sqlite3.Connection, int) -> list
    """Validate one run. Returns list of result strings."""
    results = []
    r = _fetch_run(conn, run_id)
    if not r:
        results.append(fail(f"run={run_id} not found"))
        return results

    platform = _detect_platform(conn, run_id)

    # Fetch SPBM derived metrics if ARM
    spbm = None
    if platform == "arm_spbm":
        spbm = {}
        spbm["pkg_uj"]       = _get_spbm_domain_energy(conn, run_id, "PACKAGE")
        spbm["cpu_p_uj"]     = _get_spbm_domain_energy(conn, run_id, "CPU_P")
        spbm["cpu_e_uj"]     = _get_spbm_domain_energy(conn, run_id, "CPU_E")
        spbm["gpu_spbm_uj"]  = _get_spbm_domain_energy(conn, run_id, "GPU")
        spbm["dc_input_uj"]  = _get_rail_energy(conn, run_id, "dc_input")
        spbm["dla_uj"]       = _get_rail_energy(conn, run_id, "dla")
        spbm["gpu_dcgm_uj"]  = _get_gpu_dcgm_energy(conn, run_id)

        # Derived
        pkg_s    = spbm["pkg_uj"] or 0
        cpu_p    = spbm["cpu_p_uj"] or 0
        cpu_e    = spbm["cpu_e_uj"] or 0
        gpu_s    = spbm["gpu_spbm_uj"] or 0
        dla      = spbm["dla_uj"] or 0
        dc_in    = spbm["dc_input_uj"] or 0
        gpu_d    = spbm["gpu_dcgm_uj"] or 0

        children = cpu_p + cpu_e + gpu_s + dla
        spbm["soc_residual_uj"]  = max(0.0, pkg_s - children)
        spbm["board_overhead_uj"] = max(0.0, dc_in - pkg_s)
        spbm["nvlink_c2c_uj"]    = max(0.0, gpu_s - gpu_d) if gpu_d else None
        spbm["c1_residual_pct"]  = 100.0 * spbm["soc_residual_uj"] / pkg_s if pkg_s else 0

        # C1
        if pkg_s > 0 and cpu_p > 0:
            residual = pkg_s - children
            if residual < -1000:
                spbm["C1"] = "FAIL"
            elif spbm["c1_residual_pct"] > TOL_C1_PCT:
                spbm["C1"] = "WARN"
            else:
                spbm["C1"] = "PASS"
        else:
            spbm["C1"] = "SKIP"

        # C2
        if dc_in > 0 and pkg_s > 0:
            spbm["C2_board_pct"] = 100.0 * spbm["board_overhead_uj"] / dc_in
            if dc_in < pkg_s:
                spbm["C2"] = "FAIL"
            elif spbm["C2_board_pct"] > TOL_C2_PCT:
                spbm["C2"] = "WARN"
            else:
                spbm["C2"] = "PASS"
        else:
            spbm["C2"] = "SKIP"
            spbm["C2_board_pct"] = None

        # C3
        if gpu_s > 0 and gpu_d > 0:
            spbm["C3_ratio"] = gpu_s / gpu_d
            if gpu_s < gpu_d:
                spbm["C3"] = "FAIL"
            elif spbm["C3_ratio"] > TOL_C3_RATIO:
                spbm["C3"] = "WARN"
            else:
                spbm["C3"] = "PASS"
        else:
            spbm["C3"] = "SKIP"
            spbm["C3_ratio"] = None

    _print_tree(r, platform, spbm)

    p   = f"run={run_id}[{r['workflow_type']}]"
    pkg  = r["pkg_energy_uj"]        or 0
    core = r["core_energy_uj"]       or 0
    unc  = r["uncore_energy_uj"]     or 0
    dram = r["dram_energy_uj"]       or 0
    base = r["baseline_energy_uj"]   or 0
    dyn  = r["dynamic_energy_uj"]    or 0
    attr = r["attributed_energy_uj"] or 0
    bg   = r["background_energy_uj"] or max(0, dyn - attr)
    plan = r["planning_energy_uj"]   or 0
    exe  = r["execution_energy_uj"]  or 0
    syn  = r["synthesis_energy_uj"]  or 0
    iph  = r["inter_phase_energy_uj"] or 0
    orch = r["orchestration_energy_uj"] or 0
    llmc = r["llm_compute_energy_uj"] or 0
    asum = r["attempt_sum_uj"]       or 0
    tskd = r["task_duration_ns"]     or r["duration_ns"] or 0
    apwr = r["avg_power_watts"]      or 0
    mth  = r["attribution_method"]   or "unknown"
    ofrc = r["orchestration_fraction"]
    unat = r["unattributed_energy_uj"] or 0
    wf   = r["workflow_type"] or "?"

    # DOMAIN-PARTITION
    if platform == "x86_rapl":
        d = abs(pkg - (core + unc + dram))
        if core > 0:
            results.append(ok(f"{p} DOMAIN-PARTITION x86 delta={d}µJ")
                           if d <= TOL_UJ
                           else fail(f"{p} DOMAIN-PARTITION x86 VIOLATION delta={d}µJ"))
        else:
            results.append(warn(f"{p} DOMAIN-PARTITION x86 core=NULL"))
    elif platform == "arm_spbm" and spbm:
        results.append(ok(f"{p} DOMAIN-PARTITION ARM C1={spbm['C1']}"
                          f" residual={spbm['c1_residual_pct']:.1f}%")
                       if spbm["C1"] in ("PASS", "SKIP")
                       else (warn(f"{p} DOMAIN-PARTITION ARM C1=WARN residual={spbm['c1_residual_pct']:.1f}%")
                             if spbm["C1"] == "WARN"
                             else fail(f"{p} DOMAIN-PARTITION ARM C1=FAIL children>pkg")))
        if spbm["C2"] != "SKIP":
            results.append(ok(f"{p} GPU-C2 board_overhead={spbm.get('C2_board_pct',0):.1f}%")
                           if spbm["C2"] == "PASS"
                           else (warn(f"{p} GPU-C2 WARN board={spbm.get('C2_board_pct',0):.1f}%")
                                 if spbm["C2"] == "WARN"
                                 else fail(f"{p} GPU-C2 FAIL dc_input<pkg")))
        if spbm["C3"] != "SKIP":
            results.append(ok(f"{p} GPU-C3 C3={spbm['C3']} ratio={spbm.get('C3_ratio',0):.2f}x")
                           if spbm["C3"] == "PASS"
                           else (warn(f"{p} GPU-C3 WARN ratio={spbm.get('C3_ratio',0):.2f}x")
                                 if spbm["C3"] == "WARN"
                                 else fail(f"{p} GPU-C3 FAIL gpu_spbm<gpu_dcgm")))
    else:
        results.append(warn(f"{p} DOMAIN-PARTITION platform={platform} limited"))

    # IDLE-SPLIT
    d = abs(pkg - (base + dyn))
    results.append(ok(f"{p} IDLE-SPLIT delta={d}µJ") if d <= TOL_UJ
                   else fail(f"{p} IDLE-SPLIT VIOLATION delta={d}µJ"))

    # PROC-ATTR
    if attr > 0:
        d = abs(dyn - (attr + bg))
        results.append(ok(f"{p} PROC-ATTR delta={d}µJ") if d <= TOL_UJ
                       else fail(f"{p} PROC-ATTR VIOLATION delta={d}µJ"))
    else:
        results.append(warn(f"{p} PROC-ATTR attr=NULL"))

    # ACTIVITY-DECOMP
    if attr > 0:
        d = abs(attr - (llmc + orch))
        is_s = "sample_based" in mth
        results.append(ok(f"{p} ACTIVITY-DECOMP [{'MEASURED' if is_s else 'INFERRED'}] delta={d}µJ")
                       if d <= TOL_UJ
                       else fail(f"{p} ACTIVITY-DECOMP VIOLATION delta={d}µJ"))
    else:
        results.append(warn(f"{p} ACTIVITY-DECOMP attr=NULL"))

    # PHASE-PARTITION
    if wf == "agentic":
        if plan > 0 or exe > 0 or syn > 0:
            d = abs(attr - (plan + exe + syn + iph))
            results.append(ok(f"{p} PHASE-PARTITION delta={d}µJ") if d <= TOL_UJ
                           else fail(f"{p} PHASE-PARTITION VIOLATION delta={d}µJ"))
        else:
            results.append(warn(f"{p} PHASE-PARTITION phases=NULL"))
    else:
        results.append(ok(f"{p} PHASE-PARTITION linear no phases"))

    # GOAL-AGGREGATION
    if asum > 0:
        d = abs(attr - asum)
        results.append(ok(f"{p} GOAL-AGGREGATION delta={d}µJ") if d <= TOL_UJ
                       else fail(f"{p} GOAL-AGGREGATION VIOLATION delta={d}µJ"))
    else:
        results.append(warn(f"{p} GOAL-AGGREGATION no attempts"))

    # f_orch
    if ofrc is not None and attr > 0 and orch > 0:
        comp = orch / attr
        d = abs(comp - ofrc)
        results.append(ok(f"{p} f_orch stored={ofrc:.4f} computed={comp:.4f} delta={d:.6f}")
                       if d <= TOL_FRAC
                       else fail(f"{p} f_orch VIOLATION delta={d:.6f}"))
    elif ofrc is None:
        results.append(warn(f"{p} f_orch NULL"))

    # Power
    if tskd > 0 and dyn > 0:
        cp = (dyn / 1e6) / (tskd / 1e9)
        d = abs(cp - apwr)
        results.append(ok(f"{p} Power delta={d:.3f}W") if d <= TOL_POWER
                       else fail(f"{p} Power VIOLATION delta={d:.3f}W"))
    else:
        results.append(warn(f"{p} Power skipped"))

    return results


def main():
    # type: () -> None
    parser = argparse.ArgumentParser(
        description="A-LEMS platform-aware energy chain validation"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--exp-id",    type=int)
    group.add_argument("--run-id",    type=int)
    group.add_argument("--latest",    action="store_true")
    group.add_argument("--all-valid", action="store_true")
    parser.add_argument("--experiment-type")
    parser.add_argument("--db", default=DB_PATH)
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(fail(f"DB not found: {args.db}"))
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    if args.run_id:
        results = validate_run(conn, args.run_id)
        print(f"\n  Conservation Summary:")
        for r in results:
            print(f"  {r}")
        conn.close()
        sys.exit(0 if not any(r.startswith(RED) for r in results) else 1)

    if args.all_valid:
        q, params = "SELECT exp_id FROM experiments WHERE is_valid=1", []
        if args.experiment_type:
            q += " AND experiment_type=?"
            params.append(args.experiment_type)
        exp_ids = [r[0] for r in conn.execute(q, params).fetchall()]
    elif args.latest:
        q = "SELECT MAX(exp_id) FROM experiments WHERE 1=1"
        params = []
        if args.experiment_type:
            q += " AND experiment_type=?"
            params.append(args.experiment_type)
        row = conn.execute(q, params).fetchone()
        exp_ids = [row[0]] if row and row[0] else []
    else:
        exp_ids = [args.exp_id]

    if not exp_ids or exp_ids[0] is None:
        print(fail("No experiments found"))
        sys.exit(1)

    gp = gw = gf = 0
    for exp_id in exp_ids:
        exp = conn.execute(
            "SELECT experiment_type, workflow_type, runs_completed, is_valid "
            "FROM experiments WHERE exp_id=?", (exp_id,)
        ).fetchone()
        if not exp:
            print(fail(f"exp_id={exp_id} not found"))
            continue

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

        p  = sum(1 for r in all_r if r.startswith(GREEN))
        w  = sum(1 for r in all_r if r.startswith(YELLOW))
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
