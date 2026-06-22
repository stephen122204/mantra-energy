"""
spbm_telemetry_etl.py — SPEC_SPBM_FULL_TELEMETRY implementation.
 
Three responsibilities per run, all idempotent:
  1. Write firmware power-limit snapshot to run_power_limits
     (delegates to gpu_spbm_etl.write_power_limits — kept in that file
     since it's a thin DB write, avoiding a third near-duplicate
     sqlite-connection-handling function).
  2. Compute and store spbm_sample_coverage_pct (count-based coverage,
     samples_observed_telemetry / samples_expected_telemetry from
     SPBMSampler — see patch 4's coverage counters).
  3. Compute spbm_conversion_loss_uj and spbm_conversion_efficiency
     from dc_input vs pkg domain sums.
 
dc_input semantic caution: this module computes the numeric values
only. No text in this module or its logs may claim dc_input represents
"board power" or "wall power" — see SPEC_SPBM_FULL_TELEMETRY Section 7b,
binding until vendor documentation is checked.
"""
import logging
import sqlite3
from typing import Optional
 
logger = logging.getLogger(__name__)
 
from scripts.tools.path_loader import get_alems_db_path
from scripts.etl.gpu_spbm_etl import write_power_limits
 
DOMAIN_PACKAGE  = 1   # confirmed real, energy_domains, name='PACKAGE'
DOMAIN_DC_INPUT = 28  # new, this spec, energy_domains migration v76
 
 
def _get_domain_total_uj(conn, run_id: int, domain_id: int) -> Optional[int]:
    row = conn.execute(
        "SELECT SUM(energy_uj) FROM energy_sample_domains "
        "WHERE run_id = ? AND domain_id = ?",
        (run_id, domain_id),
    ).fetchone()
    total = row[0] if row else None
    return int(total) if total is not None else None
 
 
def _compute_conversion_metrics(conn, run_id: int) -> tuple:
    """Returns (conversion_loss_uj, conversion_efficiency), either may be None."""
    dc_input_uj = _get_domain_total_uj(conn, run_id, DOMAIN_DC_INPUT)
    pkg_uj      = _get_domain_total_uj(conn, run_id, DOMAIN_PACKAGE)
 
    if dc_input_uj is None or pkg_uj is None or dc_input_uj <= 0:
        return None, None
 
    conversion_loss_uj = dc_input_uj - pkg_uj
    conversion_efficiency = pkg_uj / dc_input_uj
    return conversion_loss_uj, conversion_efficiency
 
 
def process_run(run_id: int, result: dict, conn=None) -> None:
    """
    Full SPBM telemetry post-processing for one run. Idempotent.
 
    Args:
        run_id: The runs.run_id to process.
        result: Full harness result dict — used to retrieve
                power_limits_snapshot (in-memory at measurement time,
                see patch 8 / harness.py wiring).
        conn:   Active DB connection. If None, opens/closes its own.
    """
    owns_conn = conn is None
    if owns_conn:
        conn = sqlite3.connect(get_alems_db_path())
 
    try:
        # 1. Firmware power limits
        ml = result.get("ml_features", {}) or {}
        limits = ml.get("power_limits_snapshot")
        write_power_limits(run_id, limits, conn)
 
        # 2. Coverage — from ml_features["spbm_telemetry_coverage"],
        #    computed in stop_measurement() from last_v2_samples.
        #    None on non-SPBM platforms or if no new telemetry channels
        #    were sampled (domain 25 never appeared in any v2 sample).
        coverage = ml.get("spbm_telemetry_coverage") or {}
        if coverage:
            conn.execute(
                """UPDATE runs SET
                       spbm_power_sampling_freq_hz = ?,
                       spbm_samples_expected        = ?,
                       spbm_samples_observed        = ?,
                       spbm_sample_coverage_pct     = ?,
                       spbm_integration_method      = ?
                   WHERE run_id = ?""",
                (
                    coverage.get("spbm_power_sampling_freq_hz"),
                    coverage.get("spbm_samples_expected"),
                    coverage.get("spbm_samples_observed"),
                    coverage.get("spbm_sample_coverage_pct"),
                    coverage.get("spbm_integration_method"),
                    run_id,
                ),
            )
            conn.commit()
            logger.info(
                "spbm_telemetry_etl: run_id=%d coverage=%.1f%% (%d/%d samples)",
                run_id,
                coverage.get("spbm_sample_coverage_pct") or 0,
                coverage.get("spbm_samples_observed") or 0,
                coverage.get("spbm_samples_expected") or 0,
            )
 
        # 3. Conversion metrics
        conversion_loss_uj, conversion_efficiency = _compute_conversion_metrics(conn, run_id)
        conn.execute(
            """UPDATE runs SET
                   spbm_conversion_loss_uj    = ?,
                   spbm_conversion_efficiency = ?
               WHERE run_id = ?""",
            (conversion_loss_uj, conversion_efficiency, run_id),
        )
        conn.commit()
 
        logger.info(
            "spbm_telemetry_etl.process_run: run_id=%d conversion_loss_uj=%s efficiency=%s",
            run_id, conversion_loss_uj, conversion_efficiency,
        )
    finally:
        if owns_conn:
            conn.close()
 
 
def backfill_all(db_path: str = None) -> None:
    """Reprocess every run for conversion metrics. Power limits cannot
    be backfilled retroactively — they were never captured for past
    runs (in-memory snapshot, not persisted before this spec)."""
    conn = sqlite3.connect(db_path or get_alems_db_path())
    try:
        run_ids = [r[0] for r in conn.execute("SELECT run_id FROM runs ORDER BY run_id").fetchall()]
        logger.info("spbm_telemetry_etl.backfill_all: %d runs (conversion metrics only)", len(run_ids))
        for rid in run_ids:
            try:
                conversion_loss_uj, conversion_efficiency = _compute_conversion_metrics(conn, rid)
                if conversion_loss_uj is not None:
                    conn.execute(
                        """UPDATE runs SET spbm_conversion_loss_uj = ?,
                               spbm_conversion_efficiency = ? WHERE run_id = ?""",
                        (conversion_loss_uj, conversion_efficiency, rid),
                    )
                    conn.commit()
            except Exception as e:
                logger.warning("spbm_telemetry_etl.backfill_all: run_id=%d failed: %s", rid, e)
    finally:
        conn.close()
 
 
if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill-all", action="store_true",
                         help="Conversion metrics only — power limits not retroactively recoverable")
    args = parser.parse_args()
    if args.backfill_all:
        backfill_all()
    else:
        parser.print_help()
