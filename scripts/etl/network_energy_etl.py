"""
core/etl/network_energy_etl.py
ETL: Network wait energy attribution per run.

Reads: llm_interactions (blocking windows), energy_samples / energy_sample_domains
Writes: network_energy_attribution (one row per run)

Integration point: called from experiment_runner.py after v2 samples committed.
Same pattern as gpu_spbm_etl.py and spbm_telemetry_etl.py.

Call signature (matching existing ETL pattern):
    process_run(run_id, db_conn)

Also supports:
    backfill_all(db_path)  — CLI flag --backfill-all for historical runs
"""

import logging
import sqlite3
import sys
from typing import Optional

logger = logging.getLogger(__name__)

# ── SQL ──────────────────────────────────────────────────────────────────────

_INSERT_ATTRIBUTION = """
    INSERT OR REPLACE INTO network_energy_attribution
        (run_id, strategy_used, energy_uj, confidence,
         measurement_type, non_local_ms, window_count, coverage_fraction,
         nic_activity_validated, nic_adjusted_confidence, nic_coverage_fraction)
    VALUES
        (:run_id, :strategy_used, :energy_uj, :confidence,
         :measurement_type, :non_local_ms, :window_count, :coverage_fraction,
         :nic_activity_validated, :nic_adjusted_confidence, :nic_coverage_fraction)
"""

_GET_TOTAL_NON_LOCAL_MS = """
    SELECT COALESCE(SUM(non_local_ms), 0)
    FROM llm_interactions
    WHERE run_id = ?
      AND non_local_ms > 0
"""

_EXISTING_ROW = """
    SELECT id FROM network_energy_attribution WHERE run_id = ?
"""


def process_run(run_id: int, db_conn: sqlite3.Connection) -> None:
    """
    Compute and store network wait energy attribution for one run.

    Called synchronously from experiment_runner.py after each run completes.
    Idempotent — INSERT OR REPLACE handles re-runs.

    Args:
        run_id:  The run to process.
        db_conn: Open SQLite connection (same conn as run inserts — EEI pattern).
    """
    # Import factory here to avoid circular imports at module load time
    from core.network.network_estimator_factory import NetworkEstimatorFactory
    from core.network.overlap_utils import fetch_blocking_windows

    try:
        # Load blocking windows for this run
        windows = fetch_blocking_windows(db_conn, run_id)

        # Total non_local_ms for the attribution row
        cursor = db_conn.cursor()
        cursor.execute(_GET_TOTAL_NON_LOCAL_MS, (run_id,))
        row = cursor.fetchone()
        total_non_local_ms = float(row[0]) if row else 0.0

        # Select best available estimator for this platform
        estimator = NetworkEstimatorFactory.create(
            config={},
            db_conn=db_conn,
        )

        # Run estimation
        energy_uj, method_id, confidence, mtype, coverage = estimator.estimate(
            run_id=run_id,
            windows=windows,
            db_conn=db_conn,
        )

        # Write attribution row
        # SPEC_03A: NIC activity validation
        try:
            from core.network.nic_validator import validate_windows_with_nic
            nic_adj_conf, nic_validated, nic_cov = validate_windows_with_nic(
                run_id, windows, confidence, db_conn,
            )
        except Exception as _e:
            logger.debug("nic_validator skipped: %s", _e)
            nic_adj_conf  = confidence
            nic_validated = None
            nic_cov       = 0.0

        # Write attribution row
        cursor.execute(_INSERT_ATTRIBUTION, {
            "run_id":                  run_id,
            "strategy_used":           method_id,
            "energy_uj":               energy_uj,
            "confidence":              nic_adj_conf,
            "measurement_type":        mtype,
            "non_local_ms":            total_non_local_ms if total_non_local_ms > 0 else None,
            "window_count":            len(windows),
            "coverage_fraction":       coverage,
            "nic_activity_validated":  nic_validated if nic_cov > 0 else None,
            "nic_adjusted_confidence": nic_adj_conf  if nic_cov > 0 else None,
            "nic_coverage_fraction":   nic_cov       if nic_cov > 0 else None,
        })
        db_conn.commit()

        logger.info(
            "network_etl: run=%d strategy=%s energy=%s µJ windows=%d coverage=%.2f",
            run_id,
            method_id,
            str(energy_uj) if energy_uj is not None else "NULL",
            len(windows),
            coverage,
        )

    except Exception as exc:
        # Never crash experiment_runner — log and continue (PAC-4)
        logger.error("network_etl: run=%d failed: %s", run_id, exc, exc_info=True)


def backfill_all(db_path: str) -> None:
    """
    Backfill network_energy_attribution for all existing runs.

    Skips runs that already have a row (idempotent).
    Used for historical runs collected before this ETL existed.

    Args:
        db_path: Path to experiments.db
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        # Get all run_ids not yet in network_energy_attribution
        cursor.execute("""
            SELECT r.run_id
            FROM runs r
            LEFT JOIN network_energy_attribution nea ON nea.run_id = r.run_id
            WHERE nea.id IS NULL
            ORDER BY r.run_id
        """)
        run_ids = [row[0] for row in cursor.fetchall()]

        logger.info("network_etl: backfilling %d runs", len(run_ids))

        for i, run_id in enumerate(run_ids):
            process_run(run_id, conn)
            if (i + 1) % 50 == 0:
                logger.info("network_etl: backfill progress %d/%d", i + 1, len(run_ids))

        logger.info("network_etl: backfill complete")
    finally:
        conn.close()


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from scripts.tools.path_loader import get_alems_db_path

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Network energy ETL")
    parser.add_argument("--backfill-all", action="store_true",
                        help="Backfill all runs missing network attribution")
    args = parser.parse_args()

    if args.backfill_all:
        db_path = get_alems_db_path()
        if not db_path:
            logger.error("Cannot resolve DB path")
            sys.exit(1)
        backfill_all(db_path)
    else:
        parser.print_help()
        sys.exit(1)
