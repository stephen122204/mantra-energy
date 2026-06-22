
"""
gpu_spbm_etl.py — SPEC_GPU_DUAL_CHANNEL implementation.

Computes gpu_spbm_total_uj, gpu_spbm_dynamic_uj, gpu_residual_dynamic_uj
for one run, after the run row and its samples already exist.

Source of truth for gpu_spbm_total_uj: SUM(energy_sample_domains.energy_uj)
WHERE run_id = ? AND domain_id = 7 (GPU/SPBM domain). Verified real and
populated on GN100 (2026-06-21, run_id=90: 231040000 uj, vs DCGM
174166000 uj for the same run — SPBM > DCGM as expected, broad rail
includes memory + NVLink-C2C on top of compute).

gpu_spbm_baseline_uj sourced from idle_baseline_domains, domain_id 7,
using the same rate-times-duration pattern already used for
gpu_baseline_energy_uj (confirmed via schema.py comment:
"baseline_rate_gpu_uj_per_ns * run_duration_ns").

NOT clamped to zero for residual — negative residual is a valid
diagnostic signal per SPEC_GPU_DUAL_CHANNEL Section 7a, indicating
baseline drift or measurement window misalignment, not an error.

On platforms with no SPBM (UBUNTU2505, x86), domain_id 7 will have zero
rows for any run_id, SUM returns NULL, all three fields stay NULL —
correct, honest per MIC-3, not a bug.
"""
import logging
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)

from scripts.tools.path_loader import get_alems_db_path

DOMAIN_GPU_SPBM = 7   # confirmed real, energy_domains table, name='GPU'
DOMAIN_GPU_DCGM = 24  # confirmed real, energy_domains table, name='GPU_DCGM'


def _get_gpu_spbm_total_uj(conn, run_id: int) -> Optional[int]:
    """
    SUM(energy_uj) for domain_id=7, this run. None if zero rows
    (non-SPBM platform, or no GPU activity sampled — both legitimate).
    """
    row = conn.execute(
        "SELECT SUM(energy_uj) FROM energy_sample_domains "
        "WHERE run_id = ? AND domain_id = ?",
        (run_id, DOMAIN_GPU_SPBM),
    ).fetchone()
    total = row[0] if row else None
    return int(total) if total is not None else None


def _get_gpu_spbm_baseline_uj(conn, run_id: int, duration_ns: Optional[int]) -> Optional[int]:
    """
    GPU/SPBM idle baseline energy for this run's duration, domain_id 7.
    Mirrors the existing gpu_baseline_energy_uj pattern: most recent
    idle_baseline_domains row for this domain, power_watts * duration.

    idle_baseline_domains.power_watts is a RATE (W), not energy — must
    multiply by duration_ns / 1e9 to get joules, then * 1e6 for uJ.
    """
    if not duration_ns or duration_ns <= 0:
        return None
    row = conn.execute(
        """SELECT power_watts FROM idle_baseline_domains
           WHERE domain_id = ?
           ORDER BY id DESC LIMIT 1""",
        (DOMAIN_GPU_SPBM,),
    ).fetchone()
    if row is None or row[0] is None:
        logger.warning(
            "_get_gpu_spbm_baseline_uj: no idle baseline for domain_id=%d run_id=%d",
            DOMAIN_GPU_SPBM, run_id,
        )
        return None
    power_watts = row[0]
    duration_s = duration_ns / 1_000_000_000
    baseline_uj = power_watts * duration_s * 1_000_000
    return int(baseline_uj)


def process_one(run_id: int, conn=None) -> None:
    """
    Compute and store gpu_spbm_total_uj, gpu_spbm_dynamic_uj,
    gpu_residual_dynamic_uj for one run. Idempotent — safe to rerun.

    Args:
        run_id: The runs.run_id to process.
        conn:   Active DB connection. If None, opens one against the
                resolved db path and closes it before returning
                (matches goal_execution_etl.py's standalone-CLI pattern).
    """
    owns_conn = conn is None
    if owns_conn:
        conn = sqlite3.connect(get_alems_db_path())

    try:
        row = conn.execute(
            "SELECT duration_ns, gpu_dynamic_energy_uj FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            logger.warning("gpu_spbm_etl.process_one: run_id=%d not found — skipping", run_id)
            return

        duration_ns, gpu_dcgm_dynamic_uj = row

        gpu_spbm_total_uj = _get_gpu_spbm_total_uj(conn, run_id)
        if gpu_spbm_total_uj is None:
            # No SPBM domain-7 samples for this run — non-SPBM platform
            # or genuinely no GPU activity. Honest NULL, not an error.
            logger.debug(
                "gpu_spbm_etl.process_one: run_id=%d no SPBM gpu samples — "
                "leaving gpu_spbm_* fields NULL", run_id,
            )
            return

        gpu_spbm_baseline_uj = _get_gpu_spbm_baseline_uj(conn, run_id, duration_ns)

        if gpu_spbm_baseline_uj is not None:
            gpu_spbm_dynamic_uj = max(0, gpu_spbm_total_uj - gpu_spbm_baseline_uj)
        else:
            gpu_spbm_dynamic_uj = None

        if gpu_spbm_dynamic_uj is not None and gpu_dcgm_dynamic_uj is not None:
            # NOT clamped to zero — negative residual is a valid
            # diagnostic signal per spec Section 7a.
            gpu_residual_dynamic_uj = gpu_spbm_dynamic_uj - gpu_dcgm_dynamic_uj
        else:
            gpu_residual_dynamic_uj = None

        conn.execute(
            """UPDATE runs SET
                   gpu_spbm_total_uj      = ?,
                   gpu_spbm_dynamic_uj    = ?,
                   gpu_residual_dynamic_uj = ?
               WHERE run_id = ?""",
            (gpu_spbm_total_uj, gpu_spbm_dynamic_uj, gpu_residual_dynamic_uj, run_id),
        )
        conn.commit()

        logger.info(
            "gpu_spbm_etl.process_one: run_id=%d spbm_total=%s dynamic=%s residual=%s",
            run_id, gpu_spbm_total_uj, gpu_spbm_dynamic_uj, gpu_residual_dynamic_uj,
        )
    finally:
        if owns_conn:
            conn.close()
            
def write_power_limits(run_id: int, limits: dict, conn=None) -> None:
    """
    SPEC_SPBM_FULL_TELEMETRY: persist firmware power-limit snapshot
    (pl1/pl2/syspl1/syspl2) for one run. Called once after insert_run()
    returns a real run_id — limits dict comes from
    energy_engine.start_measurement()'s self.power_limits_snapshot,
    captured once per run, not sampled continuously (see patch 6 / spec
    Section 3/6b for the telemetry-vs-configuration distinction).
 
    Stored in run_power_limits, NOT energy_sample_domains — these are
    configuration values, not consumption telemetry.
 
    Args:
        run_id: The runs.run_id these limits belong to.
        limits: dict from SPBMEnergyReader.read_power_limits(), keys
                'pl1'/'pl2'/'syspl1'/'syspl2', values in mW or None.
        conn:   Active DB connection. If None, opens/closes its own
                (matches process_one's standalone-CLI pattern).
    """
    if not limits:
        logger.debug(
            "write_power_limits: run_id=%d no limits snapshot (non-SPBM "
            "platform or capture failed) — skipping", run_id,
        )
        return
 
    owns_conn = conn is None
    if owns_conn:
        conn = sqlite3.connect(get_alems_db_path())
 
    try:
        for limit_key, limit_value_mw in limits.items():
            if limit_value_mw is None:
                continue  # honest skip, not a fake zero, per MIC-3
            conn.execute(
                """INSERT INTO run_power_limits (run_id, limit_key, limit_value_mw)
                   VALUES (?, ?, ?)""",
                (run_id, limit_key, limit_value_mw),
            )
        conn.commit()
        logger.info(
            "write_power_limits: run_id=%d wrote %d limit values",
            run_id, sum(1 for v in limits.values() if v is not None),
        )
    finally:
        if owns_conn:
            conn.close()

def backfill_all(db_path: str = None) -> None:
    """Reprocess every run. Safe to rerun — idempotent."""
    conn = sqlite3.connect(db_path or get_alems_db_path())
    try:
        run_ids = [r[0] for r in conn.execute("SELECT run_id FROM runs ORDER BY run_id").fetchall()]
        logger.info("gpu_spbm_etl.backfill_all: %d runs to process", len(run_ids))
        for rid in run_ids:
            try:
                process_one(rid, conn)
            except Exception as e:
                logger.warning("gpu_spbm_etl.backfill_all: run_id=%d failed: %s", rid, e)
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--backfill-all", action="store_true")
    args = parser.parse_args()
    if args.run_id:
        process_one(args.run_id)
    elif args.backfill_all:
        backfill_all()
    else:
        parser.print_help()
