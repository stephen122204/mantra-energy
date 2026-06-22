"""
core/network/rapl_slice_estimator.py
Strategy A: Raw RAPL pkg slice for PCH-integrated NICs.

Applies to: UBUNTU2505 (Intel i7-1165G7, AX201 WiFi at PCI 00:14.3)
AX201 is PCH-integrated — inside RAPL's uncore domain.
During network wait: CPU cores idle, but pkg non-zero due to
NIC DMA, PCH activity, DRAM refresh, uncore fabric.

KEY FIX: Does NOT multiply by cpu_fraction.
The old formula (RAPL * alpha_cpu) zeroed this out because alpha_cpu≈0
during blocking. This is the bug SPEC_03 fixes.

Method ID: network_wait_rapl_slice_v2
Confidence: 0.93
Measurement type: MEASURED
"""

import logging
import sqlite3
from typing import List, Optional

from core.network.interfaces import NetworkEnergyEstimatorABC, NetworkEnergyResult
from core.network.overlap_utils import fetch_blocking_windows, sum_pkg_energy_in_windows

logger = logging.getLogger(__name__)

# Provenance constants — must match provenance.py METHOD_CONFIDENCE
_METHOD_ID = "network_wait_rapl_slice_v2"
_CONFIDENCE = 0.93
_MEASUREMENT_TYPE = "MEASURED"

# RAPL uncore domain sysfs path — presence confirms Strategy A is valid
_RAPL_UNCORE_PATH = "/sys/class/powercap/intel-rapl/intel-rapl:0"


class RaplSliceEstimator(NetworkEnergyEstimatorABC):
    """
    Strategy A: Sum RAPL pkg energy during network blocking windows.

    No cpu_fraction multiplication. Captures uncore/PCH/NIC power
    directly from hardware counters during CPU-idle wait periods.
    """

    def is_available(self) -> bool:
        """
        Check RAPL pkg domain accessible via powercap sysfs.

        Presence of intel-rapl:0 confirms RAPL is readable.
        Never raises (PAC-4).
        """
        import os
        try:
            return os.path.isdir(_RAPL_UNCORE_PATH)
        except OSError:
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
        Sum RAPL pkg deltas within each blocking window.

        Returns 5-tuple. energy_uj is None if no samples in any window (MIC-3).
        coverage_fraction = windows_with_data / total_windows.
        """
        # Guard: no windows means local inference — nothing to measure
        if not windows:
            return (None, _METHOD_ID, _CONFIDENCE, _MEASUREMENT_TYPE, 0.0)

        total_uj, windows_with_data = sum_pkg_energy_in_windows(
            db_conn, run_id, windows,
        )

        coverage = windows_with_data / len(windows) if windows else 0.0

        if total_uj is None:
            # No RAPL samples found in any window — MIC-3: return None
            logger.debug(
                "rapl_slice: run=%d no samples in %d windows",
                run_id, len(windows),
            )
            return (None, _METHOD_ID, _CONFIDENCE, _MEASUREMENT_TYPE, coverage)

        logger.debug(
            "rapl_slice: run=%d %d/%d windows → %dµJ",
            run_id, windows_with_data, len(windows), total_uj,
        )
        return (total_uj, _METHOD_ID, _CONFIDENCE, _MEASUREMENT_TYPE, coverage)
