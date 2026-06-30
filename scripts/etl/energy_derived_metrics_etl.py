"""
energy_derived_metrics_etl.py — Seven-Domain Energy Decomposition ETL.

Implements the Paper A measurement DAG from paper_a_data_spec.md.

THREE CONSERVATION INVARIANTS:
  C1: Domain Conservation (intra-source, ML1 SoC)
      pkg >= cpu_p + cpu_e + gpu_spbm + dla
      Residual = pkg - sum(named children) = unmetered fabric (CMN-700 mesh,
      L3 cache slices, memory controllers). Expected ~30% on Grace Blackwell.
      Intra-source: same SPBM clock domain, exact accumulator.

  C2: Wall Conservation (cross-source, ML0 Board -> ML1 SoC)
      integrated(dc_input) >= pkg
      Difference = off-die power (LPDDR5X DIMMs, NVMe, USB/DP, Ethernet,
      fans, VRM losses, AC-DC adapter losses).
      Cross-source: INA shunt monitor vs SoC internal counter.
      ~93% off-die is expected on GB10 developer kit.

  C3: Cross-Interface Conservation (cross-source, ML1 -> ML2)
      gpu_spbm >= gpu_dcgm
      Difference = NVLink-C2C fabric + GPU memory interface + GPU VRM overhead.
      Cross-source: SPBM 10Hz vs DCGM field 156 1Hz.
      ~2-3x ratio expected for inference workloads.

SEVEN DOMAINS (Paper A Table 2):
  1. gpu_compute    = gpu_dcgm energy (DCGM field 156)
  2. nvlink_c2c     = gpu_spbm - gpu_dcgm
  3. cpu_p          = performance core energy (SPBM accumulator)
  4. cpu_e          = efficiency core energy (SPBM accumulator)
  5. dla            = integrated(dla_mw x interval_ns) (power rail)
  6. soc_residual   = pkg - cpu_p - cpu_e - gpu_spbm - dla
  7. board_overhead = integrated(dc_input) - pkg (off-die power)

Platform: GN100 (ARM/SPBM) only. On x86, energy_sample_domains has no
SPBM domains and power_rail_samples has no dc_input rail — both return
empty, ETL skips silently. PAC-4 compliant.

Run modes:
  python scripts/etl/energy_derived_metrics_etl.py --run-id <id>
  python scripts/etl/energy_derived_metrics_etl.py --backfill-all
  python scripts/etl/energy_derived_metrics_etl.py --exp-id <id>
"""

import argparse
import logging
import sqlite3
from typing import Optional, Dict

logger = logging.getLogger(__name__)

from scripts.tools.path_loader import get_alems_db_path
DB_PATH = get_alems_db_path()

# Domain names in energy_domains table (confirmed on GN100 2026-06-28)
DOMAIN_PKG   = "PACKAGE"
DOMAIN_CPU_P = "CPU_P"
DOMAIN_CPU_E = "CPU_E"
DOMAIN_GPU   = "GPU"

# Rail names in power_rails table (confirmed on GN100 2026-06-28)
RAIL_DC_INPUT = "dc_input"
RAIL_DLA      = "dla"

# DCGM source string in gpu_samples.source
DCGM_SOURCE = "DCGM"


def _get_domain_energy_uj(conn, run_id, domain_name):
    # type: (sqlite3.Connection, int, str) -> Optional[float]
    """
    Sum energy_uj for a named domain from energy_sample_domains.
    Joins energy_domains to resolve domain_id by name.
    Returns None if domain not found or no samples.
    Platform-independent: returns None on non-SPBM platforms.
    """
    row = conn.execute("""
        SELECT COALESCE(SUM(esd.energy_uj), 0) as total_uj, COUNT(*) as n
        FROM energy_sample_domains esd
        JOIN energy_domains ed ON ed.domain_id = esd.domain_id
        WHERE esd.run_id = ? AND ed.name = ?
    """, (run_id, domain_name)).fetchone()

    if not row or row[1] == 0:
        return None
    return float(row[0])


def _get_rail_energy_uj(conn, run_id, rail_name):
    # type: (sqlite3.Connection, int, str) -> Optional[float]
    """
    Integrate power_mw x interval_ns for a named power rail.
    power_mw x (interval_ns / 1e9) / 1e3 = energy_mJ -> x 1000 = energy_uJ
    Formula: SUM(power_mw * interval_ns / 1e9 * 1000) = SUM(power_mw * interval_ns / 1e6)

    Returns None if rail not found or no samples.
    Platform-independent: returns None on non-SPBM platforms.
    """
    row = conn.execute("""
        SELECT COALESCE(SUM(ps.power_mw * ps.interval_ns / 1000000.0), 0) as energy_uj,
               COUNT(*) as n
        FROM power_rail_samples ps
        JOIN power_rails pr ON pr.rail_id = ps.rail_id
        WHERE ps.run_id = ? AND pr.rail_name = ?
    """, (run_id, rail_name)).fetchone()

    if not row or row[1] == 0:
        return None
    return float(row[0])


def _get_gpu_dcgm_energy_uj(conn, run_id):
    # type: (sqlite3.Connection, int) -> Optional[float]
    """
    Sum GPU energy from gpu_samples (DCGM field 156).
    energy_uj column is the per-interval delta in µJ.
    Returns None if no DCGM samples for this run.
    """
    row = conn.execute("""
        SELECT COALESCE(SUM(energy_uj), 0) as total_uj, COUNT(*) as n
        FROM gpu_samples
        WHERE run_id = ? AND energy_uj IS NOT NULL AND energy_uj > 0
    """, (run_id,)).fetchone()

    if not row or row[1] == 0:
        return None
    return float(row[0])


def _write_metric(conn, run_id, metric_name, value_uj,
                  derivation_formula, source_ids_used):
    # type: (sqlite3.Connection, int, str, float, str, str) -> None
    """
    Write one derived metric row. Idempotent: INSERT OR REPLACE.
    """
    conn.execute("""
        INSERT OR REPLACE INTO energy_derived_metrics
            (run_id, metric_name, value_uj, derivation_formula, source_ids_used)
        VALUES (?, ?, ?, ?, ?)
    """, (run_id, metric_name, value_uj, derivation_formula, source_ids_used))


def compute_derived_metrics(run_id, db_path=DB_PATH):
    # type: (int, str) -> dict
    """
    Compute seven-domain decomposition and three conservation invariants
    for one run. Writes results to energy_derived_metrics table.

    Returns dict with all computed values and invariant statuses.
    Returns {"error": reason} if platform has no SPBM data.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        # ── ML1: SoC domain energy accumulators ───────────────────────────
        pkg_uj   = _get_domain_energy_uj(conn, run_id, DOMAIN_PKG)
        cpu_p_uj = _get_domain_energy_uj(conn, run_id, DOMAIN_CPU_P)
        cpu_e_uj = _get_domain_energy_uj(conn, run_id, DOMAIN_CPU_E)
        gpu_spbm_uj = _get_domain_energy_uj(conn, run_id, DOMAIN_GPU)

        if pkg_uj is None:
            conn.close()
            return {"error": "no SPBM PACKAGE data — non-SPBM platform or no samples"}

        # ── ML0: Board power rail integration ────────────────────────────
        dc_input_uj = _get_rail_energy_uj(conn, run_id, RAIL_DC_INPUT)
        dla_uj      = _get_rail_energy_uj(conn, run_id, RAIL_DLA)

        # ── ML2: DCGM GPU compute energy ─────────────────────────────────
        gpu_dcgm_uj = _get_gpu_dcgm_energy_uj(conn, run_id)

        # ── Derived quantities ────────────────────────────────────────────
        # C2C fabric = GPU broad rail - GPU compute only
        nvlink_c2c_uj = None
        if gpu_spbm_uj is not None and gpu_dcgm_uj is not None:
            nvlink_c2c_uj = max(0.0, gpu_spbm_uj - gpu_dcgm_uj)

        # SoC residual = unmetered fabric (CMN-700 mesh, L3, mem controllers)
        soc_residual_uj = None
        if all(v is not None for v in [pkg_uj, cpu_p_uj, cpu_e_uj, gpu_spbm_uj]):
            dla_for_residual = dla_uj or 0.0
            soc_residual_uj = max(0.0,
                pkg_uj - cpu_p_uj - cpu_e_uj - gpu_spbm_uj - dla_for_residual)

        # Off-die power = dc_input - pkg (LPDDR5X, NVMe, USB, fans, VRM losses)
        board_overhead_uj = None
        if dc_input_uj is not None and pkg_uj is not None:
            board_overhead_uj = max(0.0, dc_input_uj - pkg_uj)

        # ── Conservation invariants ───────────────────────────────────────
        # C1: pkg >= cpu_p + cpu_e + gpu_spbm + dla (intra-source, exact)
        c1_status = "SKIP"
        c1_residual_uj = None
        c1_residual_pct = None
        if all(v is not None for v in [pkg_uj, cpu_p_uj, cpu_e_uj, gpu_spbm_uj]):
            children_sum = cpu_p_uj + cpu_e_uj + gpu_spbm_uj + (dla_uj or 0.0)
            c1_residual_uj = pkg_uj - children_sum
            c1_residual_pct = 100.0 * c1_residual_uj / pkg_uj if pkg_uj > 0 else 0.0
            # Hard invariant: children must not exceed parent
            if c1_residual_uj < -1000:  # 1mJ tolerance for floating point
                c1_status = "FAIL"
            elif c1_residual_pct > 50:
                c1_status = "WARN"  # >50% residual is anomalous
            else:
                c1_status = "PASS"

        # C2: dc_input >= pkg (cross-source, board vs SoC)
        c2_status = "SKIP"
        c2_board_pct = None
        if dc_input_uj is not None and pkg_uj is not None:
            c2_board_pct = 100.0 * board_overhead_uj / dc_input_uj if dc_input_uj > 0 else 0.0
            if dc_input_uj < pkg_uj:
                c2_status = "FAIL"
            elif c2_board_pct > 98:
                c2_status = "WARN"  # >98% off-die is implausible
            else:
                c2_status = "PASS"

        # C3: gpu_spbm >= gpu_dcgm (cross-source, 10Hz vs 1Hz)
        c3_status = "SKIP"
        c3_ratio = None
        if gpu_spbm_uj is not None and gpu_dcgm_uj is not None and gpu_dcgm_uj > 0:
            c3_ratio = gpu_spbm_uj / gpu_dcgm_uj
            if gpu_spbm_uj < gpu_dcgm_uj:
                c3_status = "FAIL"
            elif c3_ratio > 10:
                c3_status = "WARN"  # >10x ratio is anomalous
            else:
                c3_status = "PASS"

        # ── Write to energy_derived_metrics ──────────────────────────────
        metrics = [
            # Seven domains
            ("gpu_compute_uj",    gpu_dcgm_uj,
             "SUM(gpu_samples.energy_uj) WHERE source=DCGM",
             "gpu_samples"),
            ("nvlink_c2c_uj",     nvlink_c2c_uj,
             "gpu_spbm_uj - gpu_dcgm_uj",
             "energy_sample_domains,gpu_samples"),
            ("cpu_p_uj",          cpu_p_uj,
             "SUM(energy_sample_domains.energy_uj) WHERE domain=CPU_P",
             "energy_sample_domains"),
            ("cpu_e_uj",          cpu_e_uj,
             "SUM(energy_sample_domains.energy_uj) WHERE domain=CPU_E",
             "energy_sample_domains"),
            ("dla_uj",            dla_uj,
             "SUM(power_rail_samples.power_mw * interval_ns / 1e6) WHERE rail=dla",
             "power_rail_samples"),
            ("soc_residual_uj",   soc_residual_uj,
             "pkg_uj - cpu_p_uj - cpu_e_uj - gpu_spbm_uj - dla_uj",
             "energy_sample_domains"),
            ("board_overhead_uj", board_overhead_uj,
             "integrated(dc_input_mw) - pkg_uj",
             "power_rail_samples,energy_sample_domains"),
            # Primary domain totals
            ("pkg_uj",            pkg_uj,
             "SUM(energy_sample_domains.energy_uj) WHERE domain=PACKAGE",
             "energy_sample_domains"),
            ("gpu_spbm_uj",       gpu_spbm_uj,
             "SUM(energy_sample_domains.energy_uj) WHERE domain=GPU",
             "energy_sample_domains"),
            ("dc_input_uj",       dc_input_uj,
             "SUM(power_rail_samples.power_mw * interval_ns / 1e6) WHERE rail=dc_input",
             "power_rail_samples"),
            # Conservation invariants
            ("c1_residual_uj",    c1_residual_uj,
             "pkg_uj - (cpu_p + cpu_e + gpu_spbm + dla)",
             "energy_sample_domains"),
            ("c2_board_pct",      c2_board_pct,
             "(dc_input_uj - pkg_uj) / dc_input_uj * 100",
             "power_rail_samples,energy_sample_domains"),
            ("c3_ratio",          c3_ratio,
             "gpu_spbm_uj / gpu_dcgm_uj",
             "energy_sample_domains,gpu_samples"),
        ]

        for metric_name, value, formula, sources in metrics:
            if value is not None:
                _write_metric(conn, run_id, metric_name, value, formula, sources)

        conn.commit()

        result = {
            "run_id":          run_id,
            "pkg_uj":          pkg_uj,
            "cpu_p_uj":        cpu_p_uj,
            "cpu_e_uj":        cpu_e_uj,
            "gpu_spbm_uj":     gpu_spbm_uj,
            "gpu_dcgm_uj":     gpu_dcgm_uj,
            "nvlink_c2c_uj":   nvlink_c2c_uj,
            "dla_uj":          dla_uj,
            "soc_residual_uj": soc_residual_uj,
            "dc_input_uj":     dc_input_uj,
            "board_overhead_uj": board_overhead_uj,
            "C1": c1_status,
            "C1_residual_pct": c1_residual_pct,
            "C2": c2_status,
            "C2_board_pct":    c2_board_pct,
            "C3": c3_status,
            "C3_ratio":        c3_ratio,
        }

        logger.info(
            "energy_derived_metrics: run=%d pkg=%.1fJ gpu_spbm=%.1fJ "
            "gpu_dcgm=%.1fJ c2c=%.1fJ C1=%s C2=%s C3=%s",
            run_id,
            (pkg_uj or 0) / 1e6,
            (gpu_spbm_uj or 0) / 1e6,
            (gpu_dcgm_uj or 0) / 1e6,
            (nvlink_c2c_uj or 0) / 1e6,
            c1_status, c2_status, c3_status,
        )

        return result

    finally:
        conn.close()


def backfill_all(db_path=DB_PATH):
    # type: (str) -> None
    """
    Backfill all runs with energy_derived_metrics.
    Skips non-SPBM runs silently. Idempotent.
    """
    conn = sqlite3.connect(db_path)
    run_ids = [r[0] for r in conn.execute(
        "SELECT run_id FROM runs WHERE attributed_energy_uj > 0 ORDER BY run_id"
    ).fetchall()]
    conn.close()

    print("Backfilling energy_derived_metrics for %d runs..." % len(run_ids))
    ok = skip = err = 0
    for rid in run_ids:
        result = compute_derived_metrics(rid, db_path)
        if "error" in result:
            skip += 1
        else:
            print(
                "  run %d: pkg=%.1fJ gpu_spbm=%.1fJ gpu_dcgm=%.1fJ "
                "c2c=%.1fJ C1=%s C2=%s C3=%s" % (
                    rid,
                    (result.get("pkg_uj") or 0) / 1e6,
                    (result.get("gpu_spbm_uj") or 0) / 1e6,
                    (result.get("gpu_dcgm_uj") or 0) / 1e6,
                    (result.get("nvlink_c2c_uj") or 0) / 1e6,
                    result.get("C1", "?"),
                    result.get("C2", "?"),
                    result.get("C3", "?"),
                )
            )
            ok += 1

    print("Done: %d ok, %d skipped (non-SPBM), %d errors." % (ok, skip, err))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(
        description="Seven-domain energy decomposition ETL"
    )
    parser.add_argument("--run-id",       type=int)
    parser.add_argument("--exp-id",       type=int)
    parser.add_argument("--backfill-all", action="store_true")
    parser.add_argument("--db",           default=DB_PATH)
    args = parser.parse_args()

    if args.backfill_all:
        backfill_all(args.db)
    elif args.run_id:
        result = compute_derived_metrics(args.run_id, args.db)
        print(result)
    elif args.exp_id:
        conn = sqlite3.connect(args.db)
        run_ids = [r[0] for r in conn.execute(
            "SELECT run_id FROM runs WHERE exp_id=? ORDER BY run_id",
            (args.exp_id,)
        ).fetchall()]
        conn.close()
        for rid in run_ids:
            result = compute_derived_metrics(rid, args.db)
            print(result)
    else:
        parser.print_help()
