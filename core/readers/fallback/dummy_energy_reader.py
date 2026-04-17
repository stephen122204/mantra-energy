#!/usr/bin/env python3
"""
================================================================================
DUMMY ENERGY READER — LIMITED Mode Fallback for Unsupported Platforms
================================================================================

Purpose:
    Safe fallback reader for platforms where no energy measurement is
    possible (Windows, WSL, unknown OS). Returns zeros for all domains
    and logs a clear warning so users know their data is not real.

Mode:        LIMITED
Platform:    Windows, WSL, or any unrecognised OS
Returns:     Zeros for all domains (never raises exceptions)

Design Principle:
    The system must never crash due to a missing reader. DummyEnergyReader
    ensures EnergyEngine always has a valid object to call — the caller
    gets zeros and can decide whether to discard or flag the run.

Author: Deepak Panigrahy
================================================================================
"""

import logging
from typing import Dict, List

from core.readers.interfaces import EnergyReaderABC

logger = logging.getLogger(__name__)


class DummyEnergyReader(EnergyReaderABC):
    """
    No-op energy reader for unsupported platforms (LIMITED mode).

    Returns zeros for every call. Logs a clear warning at init so
    users are not silently misled into thinking they have real data.

    Use this as the final fallback in ReaderFactory when no other
    reader is appropriate for the detected platform.

    Attributes:
        _warned (bool): Throttle flag — warn once at init only.
    """

    # Minimal domain list — same names as RAPL for schema consistency
    STUB_DOMAINS = ["package-0", "core"]

    def __init__(self, config: dict = None):
        """
        Initialise the dummy reader and log a platform warning.

        Args:
            config: hw_config dict (accepted for API consistency; ignored).
        """
        self._config = config or {}     # accepted but not used
        self._warned = False

        # Single prominent warning at initialisation — not every sample
        logger.warning(
            "DummyEnergyReader initialised (LIMITED mode). "
            "This platform has no supported energy measurement interface. "
            "All energy values will be ZERO. "
            "Supported platforms: Linux x86_64 (RAPL), macOS (IOKit), "
            "Linux aarch64 (INFERRED via ML model)."
        )

    # ------------------------------------------------------------------
    # EnergyReaderABC implementation
    # ------------------------------------------------------------------

    def read_energy_uj(self) -> Dict[str, int]:
        """
        Return zero energy for all domains.

        Never raises an exception — the system must remain stable
        even on unsupported platforms.

        Returns:
            Dict[str, int]: All domains mapped to 0 µJ.
        """
        # Warn once — suppress on subsequent calls to avoid log spam
        if not self._warned:
            logger.warning(
                "DummyEnergyReader.read_energy_uj() called — "
                "returning zeros. Platform is LIMITED (no hardware counter)."
            )
            self._warned = True

        return {domain: 0 for domain in self.STUB_DOMAINS}

    def get_domains(self) -> List[str]:
        """
        Return the list of stub domain names.

        Returns:
            List[str]: ['package-0', 'core']
        """
        return list(self.STUB_DOMAINS)

    def is_available(self) -> bool:
        """
        Return False — this platform has no supported energy measurement.

        Callers use this to flag runs as LIMITED quality in the database.

        Returns:
            bool: Always False.
        """
        return False    # no real hardware — caller should flag the run

    def get_name(self) -> str:
        """
        Return the reader name for logging and platform summaries.

        Returns:
            str: 'DummyEnergyReader'
        """
        return "DummyEnergyReader"
