"""
ThermalAggregator — computes runs table thermal columns from thermal_samples_v2.

Replaces the cpu_samples-based temperature aggregation in:
  - core/execution/run_persistence.py _aggregate_run_stats()
  - core/execution/experiment_runner.py aggregate_run_stats()

Both had the same bug: reading package_temp from cpu_samples (turbostat)
which is empty on ARM and unreliable on x86 when turbostat version changes.

New source: v_thermal_cpu view (thermal_samples_v2 JOIN thermal_zones)
  - Intel/AMD: CPU_PACKAGE role, direct package temp
  - GN100 ARM: SOC role, MAX() across all 7 acpitz zones per timestamp

Also computes throttle stats from cooling_samples.

cp to: core/thermal/thermal_aggregator.py
"""

import logging
import statistics
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ThermalAggregator:
    """
    Computes thermal summary statistics for a completed run.

    Uses v_thermal_cpu view (backed by thermal_samples_v2) as the primary
    temperature source. Falls back to None (MIC-1 compliant) if no data.

    Called from _aggregate_run_stats() in run_persistence.py and
    aggregate_run_stats() in experiment_runner.py after thermal_samples_v2
    have been written by ThermalWriterV2.
    """

    def __init__(self, db_conn):
        """
        Args:
            db_conn: Raw sqlite3 connection (db.conn from SQLiteAdapter).
                     Short-lived — aggregator does not hold it long-term.
        """
        self._conn = db_conn

    def compute_thermal_stats(
        self,
        run_id: int,
        machine_id: str,
    ) -> Dict[str, Optional[float]]:
        """
        Compute package_temp_celsius, start/max/min/delta temp for a run.

        Platform logic:
          CPU_PACKAGE (Intel, AMD): one zone per tick, direct reading.
          SOC (GN100): multiple zones per tick, MAX() per timestamp gives
                       peak SoC temperature at each sample point.

        Args:
            run_id:     Experiment run_id.
            machine_id: Hostname string (from get_machine_id()).

        Returns:
            Dict with keys: package_temp_celsius, start_temp_c, max_temp_c,
            min_temp_c, thermal_delta_c, baseline_temp_celsius.
            All values None (MIC-1) if no VALID samples found.
        """
        null_result = {
            "package_temp_celsius": None,
            "start_temp_c":         None,
            "max_temp_c":           None,
            "min_temp_c":           None,
            "thermal_delta_c":      None,
            "baseline_temp_celsius": None,
        }

        # Determine which role this machine has for CPU temperature
        role_row = self._conn.execute(
            """SELECT canonical_role FROM thermal_zones
               WHERE machine_id = ? AND active = 1
                 AND canonical_role IN ('CPU_PACKAGE', 'SOC', 'CPU_DIE')
               ORDER BY CASE canonical_role
                   WHEN 'CPU_PACKAGE' THEN 1
                   WHEN 'SOC'         THEN 2
                   WHEN 'CPU_DIE'     THEN 3
               END
               LIMIT 1""",
            (machine_id,)
        ).fetchone()

        if not role_row:
            logger.warning(
                "ThermalAggregator: no CPU thermal zone for machine_id=%s run_id=%d",
                machine_id, run_id
            )
            return null_result

        role = role_row[0]

        if role == "CPU_PACKAGE":
            # One zone is the package sensor — direct per-sample values
            rows = self._conn.execute(
                """SELECT cpu_temp FROM v_thermal_cpu
                   WHERE run_id = ? AND canonical_role = 'CPU_PACKAGE'
                   ORDER BY timestamp_ns""",
                (run_id,)
            ).fetchall()
            temps = [r[0] for r in rows if r[0] is not None]

        elif role == "SOC":
            # GN100: multiple acpitz zones per tick — take MAX per timestamp
            # to get peak SoC temperature at each sample point
            rows = self._conn.execute(
                """SELECT MAX(cpu_temp) FROM v_thermal_cpu
                   WHERE run_id = ? AND canonical_role = 'SOC'
                   GROUP BY timestamp_ns
                   ORDER BY timestamp_ns""",
                (run_id,)
            ).fetchall()
            temps = [r[0] for r in rows if r[0] is not None]

        else:
            # CPU_DIE: use directly but flag low confidence
            rows = self._conn.execute(
                """SELECT cpu_temp FROM v_thermal_cpu
                   WHERE run_id = ? AND canonical_role = 'CPU_DIE'
                   ORDER BY timestamp_ns""",
                (run_id,)
            ).fetchall()
            temps = [r[0] for r in rows if r[0] is not None]
            if temps:
                logger.warning(
                    "ThermalAggregator: using CPU_DIE zone for run_id=%d "
                    "(low confidence — check THERMAL_ROLE_MAP)", run_id
                )

        if not temps:
            logger.warning(
                "ThermalAggregator: no VALID temperature samples in v_thermal_cpu "
                "for run_id=%d machine_id=%s", run_id, machine_id
            )
            return null_result

        pkg_temp = round(statistics.mean(temps), 2)
        return {
            "package_temp_celsius":  pkg_temp,
            "start_temp_c":          round(temps[0], 2),
            "max_temp_c":            round(max(temps), 2),
            "min_temp_c":            round(min(temps), 2),
            "thermal_delta_c":       round(temps[-1] - temps[0], 2),
            "baseline_temp_celsius": round(temps[0], 2),
        }

    def compute_throttle_stats(self, run_id: int) -> Dict:
        """
        Compute throttle-related columns from cooling_samples.

        Checks if any CPU_FREQ_THROTTLE, POWER_CLAMP, or TCC_OFFSET device
        had cur_state > 0 during the experiment (VALID readings only).

        Args:
            run_id: Experiment run_id.

        Returns:
            Dict with keys: thermal_during_experiment (bool),
            thermal_throttle_flag (int 0/1).
        """
        try:
            throttle_count = self._conn.execute(
                """SELECT COUNT(*) FROM cooling_samples cs
                   JOIN cooling_devices cd ON cs.device_id = cd.device_id
                   WHERE cs.run_id = ?
                     AND cd.canonical_role IN ('CPU_FREQ_THROTTLE', 'POWER_CLAMP', 'TCC_OFFSET')
                     AND cs.quality_flag = 'VALID'
                     AND cs.cur_state > 0""",
                (run_id,)
            ).fetchone()[0]
        except Exception as exc:
            # cooling_samples may not exist on old DBs during transition
            logger.debug("ThermalAggregator.compute_throttle_stats: %s", exc)
            throttle_count = 0

        throttled = throttle_count > 0
        return {
            "thermal_during_experiment": throttled,
            "thermal_throttle_flag":     1 if throttled else 0,
        }
