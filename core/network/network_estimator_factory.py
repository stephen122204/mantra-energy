"""
core/network/factory.py
PAC-2: ONLY file with platform-conditional imports in core/network/.

Selects the correct NetworkEnergyEstimator at runtime based on:
1. NIC topology detection (sysfs)
2. RAPL availability (powercap sysfs)
3. SPBM availability (energy_sample_domains table)

All other files in core/network/ import only from interfaces.py.
No platform-conditional imports anywhere else (PAC-2 compliance).
"""

import logging
import sqlite3
from typing import Optional

from core.network.interfaces import NetworkEnergyEstimatorABC
from core.network.nic_topology import detect_nic_topology, select_strategy_key

logger = logging.getLogger(__name__)

# RAPL availability check path — presence means RAPL is readable
_RAPL_ROOT = "/sys/class/powercap/intel-rapl/intel-rapl:0"

# SPBM DC_INPUT domain ID — must match energy_domains table
_DOMAIN_DC_INPUT = 28


class NetworkEstimatorFactory:
    """
    Factory for NetworkEnergyEstimatorABC subclasses.

    All platform-conditional logic lives here (PAC-2).
    Callers receive an estimator instance without knowing the platform.
    """

    @staticmethod
    def create(
        config: dict,
        db_conn: Optional[sqlite3.Connection],
        has_rapl: Optional[bool] = None,
        has_spbm: Optional[bool] = None,
    ) -> NetworkEnergyEstimatorABC:
        """
        Create the best available network energy estimator for this platform.

        Auto-detects RAPL and SPBM availability if not provided.
        Always returns a valid estimator — worst case is FallbackEstimator (PAC-4).

        Args:
            config:   Platform config dict (passed through, not used in v1).
            db_conn:  Open SQLite connection for SPBM availability check.
            has_rapl: Override RAPL detection (for testing without hardware).
            has_spbm: Override SPBM detection (for testing without hardware).

        Returns:
            Concrete NetworkEnergyEstimatorABC instance.
        """
        # Detect NIC topology via sysfs (no subprocess)
        nic_topology = detect_nic_topology()

        # Auto-detect RAPL if not overridden (test injection point)
        if has_rapl is None:
            has_rapl = _check_rapl_available()

        # Auto-detect SPBM if not overridden
        if has_spbm is None:
            has_spbm = _check_spbm_available(db_conn)

        # Pure function maps capabilities to strategy key
        strategy_key = select_strategy_key(nic_topology, has_rapl, has_spbm)

        logger.info(
            "network_factory: nic=%s rapl=%s spbm=%s → strategy=%s",
            nic_topology, has_rapl, has_spbm, strategy_key,
        )

        # PAC-2: conditional imports only here
        if strategy_key == "rapl_slice":
            from core.network.rapl_slice_estimator import RaplSliceEstimator
            return RaplSliceEstimator()

        if strategy_key == "spbm_fraction":
            from core.network.spbm_fraction_estimator import SpbmFractionEstimator
            return SpbmFractionEstimator(db_conn)

        # Strategy C: universal fallback — always importable
        from core.network.fallback_estimator import FallbackEstimator
        return FallbackEstimator()


def _check_rapl_available() -> bool:
    """
    Check if RAPL powercap sysfs is accessible on this platform.

    Returns True on Intel x86 Linux with RAPL exposed.
    Returns False on aarch64 (GN100), macOS, VMs without RAPL.
    Never raises (PAC-4).
    """
    import os
    try:
        return os.path.isdir(_RAPL_ROOT)
    except OSError:
        return False


def _check_spbm_available(db_conn: Optional[sqlite3.Connection]) -> bool:
    """
    Check if SPBM DC_INPUT domain has data in energy_sample_domains.

    Returns False if db_conn is None or table/domain not present.
    Never raises (PAC-4).
    """
    if db_conn is None:
        return False
    try:
        cursor = db_conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM energy_sample_domains
            WHERE domain_id = ?
            LIMIT 1
        """, (_DOMAIN_DC_INPUT,))
        row = cursor.fetchone()
        return bool(row and row[0] > 0)
    except Exception as exc:
        logger.debug("network_factory: SPBM check failed: %s", exc)
        return False
