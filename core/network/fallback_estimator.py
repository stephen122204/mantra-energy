"""
core/network/fallback_estimator.py
Strategy C: Time-fraction of dynamic energy — universal fallback.

Applies to: Apple M1 Pro, AMD (if no RAPL), VMs, unknown platforms.
Also used when RAPL/SPBM not accessible on otherwise supported platforms.

Method: (non_local_ms / task_duration_ms) × dynamic_energy_uj
Uses dynamic_energy_uj NOT attributed_energy_uj — attributed already
has alpha_cpu baked in which would double-suppress the estimate.

Known limitation: CPU-proportional proxy. Does not capture uncore/NIC
activity during CPU-idle wait. Returns conservative lower bound.

Method ID: network_wait_time_fraction_v1
Confidence: 0.50
Measurement type: INFERRED
"""

import logging
import sqlite3
from typing import List

from core.network.interfaces import NetworkEnergyEstimatorABC, NetworkEnergyResult

logger = logging.getLogger(__name__)

# Provenance constants — must match provenance.py METHOD_CONFIDENCE
_METHOD_ID = "network_wait_time_fraction_v1"
_CONFIDENCE = 0.50
_MEASUREMENT_TYPE = "INFERRED"

# Minimum task duration to avoid division by near-zero
_MIN_DURATION_MS = 1.0


class FallbackEstimator(NetworkEnergyEstimatorABC):
    """
    Strategy C: Time-fraction of dynamic_energy_uj.

    Always available — universal fallback when hardware counters
    cannot be read. Returns None if dynamic_energy_uj is NULL (MIC-3).
    """

    def is_available(self) -> bool:
        """Always available — no hardware dependency."""
        return True

    def get_method_id(self) -> str:
        return _METHOD_ID

    def estimate(
        self,
        run_id: int,
        windows: List[dict],
        db_conn: sqlite3.Connection,
    ) -> NetworkEnergyResult:
        """
        Estimate network wait energy as time fraction of dynamic energy.

        Uses dynamic_energy_uj (L1 baseline-subtracted) not attributed_energy_uj.
        attributed_energy_uj has alpha_cpu baked in and would double-suppress.

        Returns None if dynamic_energy_uj missing or no network windows (MIC-3).
        """
        # Guard: no remote windows means local inference
        if not windows:
            return (None, _METHOD_ID, _CONFIDENCE, _MEASUREMENT_TYPE, 0.0)

        # Fetch run-level energy and duration
        cursor = db_conn.cursor()
        cursor.execute("""
            SELECT task_duration_ns, dynamic_energy_uj
            FROM runs
            WHERE run_id = ?
        """, (run_id,))
        row = cursor.fetchone()

        if not row or not row[1]:
            # MIC-3: dynamic_energy_uj is NULL — cannot estimate
            logger.debug(
                "fallback: run=%d dynamic_energy_uj is NULL → None",
                run_id,
            )
            return (None, _METHOD_ID, _CONFIDENCE, _MEASUREMENT_TYPE, 0.0)

        task_duration_ns = row[0] or 0
        dynamic_energy_uj = int(row[1])

        duration_ms = task_duration_ns / 1e6
        if duration_ms < _MIN_DURATION_MS:
            # Too short to compute a meaningful fraction
            return (None, _METHOD_ID, _CONFIDENCE, _MEASUREMENT_TYPE, 0.0)

        # Sum total non_local_ms across all blocking windows
        total_non_local_ms = sum(w["non_local_ms"] for w in windows)
        if total_non_local_ms <= 0:
            return (None, _METHOD_ID, _CONFIDENCE, _MEASUREMENT_TYPE, 0.0)

        # Time fraction of dynamic energy — conservative lower bound
        fraction = total_non_local_ms / duration_ms
        # Clamp fraction to [0, 1] — guard against malformed duration data
        fraction = max(0.0, min(1.0, fraction))
        energy_uj = int(fraction * dynamic_energy_uj)

        # Coverage = 1.0 because time fraction covers all windows by definition
        coverage = 1.0

        logger.debug(
            "fallback: run=%d %.1fms/%.1fms → fraction=%.3f → %dµJ",
            run_id, total_non_local_ms, duration_ms, fraction, energy_uj,
        )
        return (energy_uj, _METHOD_ID, _CONFIDENCE, _MEASUREMENT_TYPE, coverage)
