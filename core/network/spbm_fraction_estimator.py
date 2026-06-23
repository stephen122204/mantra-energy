"""
core/network/spbm_fraction_estimator.py
Strategy B: SPBM DC_INPUT time-fraction for GN100 (aarch64, no RAPL).

Applies to: GN100 (NVIDIA Grace GB10, aarch64)
GN100 has no RAPL. Network energy estimated from DC_INPUT (domain_id=28)
which captures total board input power including NIC, GPU, CPU, DLA.

Method: sum DC_INPUT energy within blocking windows.
DC_INPUT during network wait includes GPU idle draw — known overestimate.
Documented in paper as conservative upper bound. v2 improvement:
subtract GPU_DCGM domain energy (deferred, not in this spec).

Method ID: network_wait_spbm_fraction_v1
Confidence: 0.70
Measurement type: INFERRED
"""

import logging
import sqlite3
from typing import List

from core.network.interfaces import NetworkEnergyEstimatorABC, NetworkEnergyResult
from core.network.overlap_utils import fetch_blocking_windows, sum_domain_energy_in_windows

logger = logging.getLogger(__name__)

# Provenance constants — must match provenance.py METHOD_CONFIDENCE
_METHOD_ID = "network_wait_spbm_fraction_v1"
_CONFIDENCE = 0.70
_MEASUREMENT_TYPE = "INFERRED"

# SPBM domain IDs — must match energy_domains table on GN100
# DC_INPUT (28) = total board input power rail
_DOMAIN_DC_INPUT = 28
_DOMAIN_GPU_SPBM = 7

# energy_sample_domains sysfs path to verify SPBM available
_SPBM_DOMAIN_CHECK_QUERY = """
    SELECT COUNT(*) FROM energy_sample_domains
    WHERE domain_id = ?
    LIMIT 1
"""


class SpbmFractionEstimator(NetworkEnergyEstimatorABC):
    """
    Strategy B: Sum SPBM DC_INPUT domain energy during blocking windows.

    Known limitation: DC_INPUT includes GPU power during blocking period.
    This overestimates pure network energy. Documented confidence 0.70.
    Future v2: subtract GPU_DCGM domain energy before attribution.
    """

    def __init__(self, db_conn: sqlite3.Connection):
        # Need db_conn at init to check domain availability
        self._db_conn = db_conn

    def is_available(self) -> bool:
        """
        Check SPBM DC_INPUT domain has data in energy_sample_domains.

        Never raises (PAC-4). Returns False if table or domain absent.
        """
        try:
            cursor = self._db_conn.cursor()
            cursor.execute(_SPBM_DOMAIN_CHECK_QUERY, (_DOMAIN_DC_INPUT,))
            row = cursor.fetchone()
            return bool(row and row[0] > 0)
        except Exception as exc:
            logger.debug("spbm_fraction: availability check failed: %s", exc)
            return False

    def get_method_id(self) -> str:
        return _METHOD_ID

    def estimate(
        self,
        run_id: int,
        windows: List[dict],
        db_conn: sqlite3.Connection,
    ) -> NetworkEnergyResult:
        """
        Sum DC_INPUT domain energy within each LLM blocking window.

        Returns 5-tuple. energy_uj is None if no SPBM samples in windows (MIC-3).
        coverage_fraction = windows_with_domain_data / total_windows.
        """
        # Guard: no remote windows means local inference — nothing to measure
        if not windows:
            return (None, _METHOD_ID, _CONFIDENCE, _MEASUREMENT_TYPE, 0.0)

        # Try DC_INPUT (28) first — available on v76+ runs
        # Fall back to GPU_SPBM (7) for older groq runs without DC_INPUT data
        total_uj, windows_with_data = sum_domain_energy_in_windows(
            db_conn, run_id, windows, _DOMAIN_DC_INPUT,
        )
        if total_uj is None:
            total_uj, windows_with_data = sum_domain_energy_in_windows(
                db_conn, run_id, windows, _DOMAIN_GPU_SPBM,
            )

        coverage = windows_with_data / len(windows) if windows else 0.0

        if total_uj is None:
            # No DC_INPUT samples found — MIC-3: return None
            logger.debug(
                "spbm_fraction: run=%d no DC_INPUT samples in %d windows",
                run_id, len(windows),
            )
            return (None, _METHOD_ID, _CONFIDENCE, _MEASUREMENT_TYPE, coverage)

        logger.debug(
            "spbm_fraction: run=%d %d/%d windows DC_INPUT → %dµJ",
            run_id, windows_with_data, len(windows), total_uj,
        )
        return (total_uj, _METHOD_ID, _CONFIDENCE, _MEASUREMENT_TYPE, coverage)
