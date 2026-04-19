#!/usr/bin/env python3
"""
================================================================================
IOKIT POWER READER — macOS Power Measurement via IOKit
================================================================================

Purpose:
    Reads real hardware power sensor values on macOS via the IOKit framework.
    Converts instantaneous power (watts) to cumulative energy (µJ) by
    integrating over time (energy = power × elapsed_seconds × 1_000_000).

Mode:        MEASURED  (real hardware sensor, not estimated)
Platform:    macOS (Darwin), any architecture (Intel or Apple Silicon)
Source:      IOKit HID power sensors (SMC on Intel, PMGR on Apple Silicon)

Why MEASURED and not DERIVED:
    IOKit reads a real hardware power sensor. The watts→µJ conversion is
    just unit arithmetic — the underlying measurement is still hardware.
    RAPLReader also does arithmetic (delta of two counter reads).

Current status:
    STUB — returns zeros. Full IOKit integration via ctypes/subprocess
    (powermetrics) is planned. The interface and mode assignment are correct.

Author: Deepak Panigrahy
================================================================================
"""

import logging
import time
from typing import Dict, List
from core.utils.formula import formula

from core.readers.interfaces import EnergyReaderABC

logger = logging.getLogger(__name__)


class IOKitPowerReader(EnergyReaderABC):
    """
    macOS hardware power reader using IOKit (stub implementation).

    Implements EnergyReaderABC with the same interface as RAPLReader
    so EnergyEngine works identically on macOS and Linux.

    Energy calculation (when fully implemented):
        At each read_energy_uj() call:
            1. Read current power from IOKit sensor (watts)
            2. Compute elapsed seconds since last read
            3. energy_uj += power_w × elapsed_s × 1_000_000

    Attributes:
        _last_read_time (float): timestamp of last read, for Δt calculation
        _cumulative_uj  (dict):  accumulated energy per domain since init
        _warned         (bool):  throttle flag for stub warning log
    """
    # ------------------------------------------------------------------
    # Methodology attributes — read by scripts/seed_methodology.py
    # ------------------------------------------------------------------
    METHOD_ID          = "iokit_power_reader"
    METHOD_NAME        = "IOKit Power Reader (macOS)"
    METHOD_LAYER       = "silicon"
    METHOD_CONFIDENCE  = 0.5
    METHOD_PROVENANCE  = "MEASURED"
    METHOD_PARAMS      = {"source": "IOKit HID", "conversion": "W_to_uJ", "stub": True}
    FALLBACK_METHOD_ID = "ml_energy_estimator"
    # Domain names to match the energy model expected by the rest of the system
    DOMAINS = ["package-0", "core"]

    def __init__(self, config: dict = None):
        """
        Initialise the IOKit power reader.

        Args:
            config: hw_config dict (accepted for API consistency;
                    macOS section not yet defined in hw_config schema).
        """
        self._config         = config or {}
        self._last_read_time = time.monotonic()     # start integration clock
        self._cumulative_uj  = {d: 0 for d in self.DOMAINS}  # energy accumulators
        self._warned         = False                # warn once per process

        logger.warning(
            "IOKitPowerReader initialised (MEASURED mode, macOS stub). "
            "Full IOKit integration not yet implemented — returning zeros."
        )

    # ------------------------------------------------------------------
    # EnergyReaderABC implementation
    # ------------------------------------------------------------------
    @formula(
        latex=r"E_{pkg} = \sum_{i} P_i \cdot \Delta t_i \times 10^6",
        variables={
            "E_pkg":    "Cumulative package energy µJ",
            "P_i":      "Instantaneous power in watts from IOKit",
            "Delta_t_i":"Elapsed seconds since last read",
        }
    )
    def read_energy_uj(self) -> Dict[str, int]:
        """
        Return cumulative energy in microjoules since initialisation.

        Current stub behaviour:
            Advances the integration clock but returns zeros.

        Future behaviour:
            1. Query IOKit HID service for package power (watts)
            2. Compute Δt since last call
            3. Accumulate energy_uj += power_w × Δt × 1_000_000
            4. Return accumulated totals per domain

        Returns:
            Dict[str, int]: Domain → cumulative µJ (zeros in stub).
        """
        # Update integration timestamp even in stub mode
        # so real implementation can drop in without clock reset issues
        now   = time.monotonic()
        _dt   = now - self._last_read_time          # elapsed seconds (unused in stub)
        self._last_read_time = now

        # Warn once — not on every 100Hz sample tick
        if not self._warned:
            logger.warning(
                "IOKitPowerReader.read_energy_uj() returning zeros — "
                "stub implementation. Mode is MEASURED (IOKit is real hardware)."
            )
            self._warned = True

        # Return current accumulated values (zeros in stub)
        return dict(self._cumulative_uj)

    def get_domains(self) -> List[str]:
        """
        Return the list of energy domains this reader provides.

        Returns:
            List[str]: ['package-0', 'core']
        """
        return list(self.DOMAINS)

    def is_available(self) -> bool:
        """
        Return True — IOKit is always present on macOS.

        Even though this is a stub, the hardware sensor exists.
        Returns True to indicate MEASURED quality, not INFERRED zeros.

        Returns:
            bool: True (IOKit is always available on macOS).
        """
        return True     # IOKit always present; stub status ≠ unavailable

    def get_name(self) -> str:
        """
        Return reader name for logging and platform summaries.

        Returns:
            str: 'IOKitPowerReader'
        """
        return "IOKitPowerReader"
