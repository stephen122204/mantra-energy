#!/usr/bin/env python3
"""
================================================================================
DUMMY CPU & THERMAL READERS — LIMITED Mode Stubs for Non-Linux Platforms
================================================================================

Purpose:
    Safe no-op implementations of CPUReaderABC and ThermalReaderABC for
    platforms where the existing PerfReader / SensorReader cannot run
    (macOS, Windows, WSL).

    These stubs ensure EnergyEngine always has a valid reader object to
    call — it receives zeros / empty dicts rather than exceptions.

Author: Deepak Panigrahy
================================================================================
"""

import logging
from typing import Dict

from core.readers.interfaces import CPUReaderABC, ThermalReaderABC

logger = logging.getLogger(__name__)


# ============================================================================
# DUMMY CPU READER
# ============================================================================

class DummyCPUReader(CPUReaderABC):
    """
    No-op CPU performance counter reader for unsupported platforms.

    Returns zeros for all counter reads. Used on macOS, Windows, and
    any platform where the PerfReader cannot be initialised.

    Attributes:
        _warned (bool): Throttle flag — log warning once at init only.
    """

    def __init__(self, config: dict = None):
        """
        Initialise dummy CPU reader.

        Args:
            config: hw_config dict (accepted for API consistency; ignored).
        """
        self._config = config or {}
        logger.warning(
            "DummyCPUReader initialised — CPU performance counters unavailable "
            "on this platform. All counter values will be ZERO."
        )

    def read_instructions(self) -> int:
        """Return 0 — perf counters unavailable on this platform."""
        return 0

    def read_cycles(self) -> int:
        """Return 0 — perf counters unavailable on this platform."""
        return 0

    def read_ipc(self) -> float:
        """Return 0.0 — IPC cannot be computed without instruction/cycle counts."""
        return 0.0

    def read_frequency_mhz(self) -> float:
        """Return 0.0 — frequency unavailable on this platform."""
        return 0.0

    def is_available(self) -> bool:
        """Return False — no real CPU counter access on this platform."""
        return False

    def get_name(self) -> str:
        """Return reader name for logging."""
        return "DummyCPUReader"


# ============================================================================
# DUMMY THERMAL READER
# ============================================================================

class DummyThermalReader(ThermalReaderABC):
    """
    No-op thermal sensor reader for unsupported platforms.

    Returns an empty dict for all temperature reads. Used on macOS,
    Windows, and ARM VMs without sysfs thermal zones.

    Attributes:
        _warned (bool): Throttle flag — log warning once at init only.
    """

    def __init__(self, config: dict = None):
        """
        Initialise dummy thermal reader.

        Args:
            config: hw_config dict (accepted for API consistency; ignored).
        """
        self._config = config or {}
        logger.warning(
            "DummyThermalReader initialised — thermal sensors unavailable "
            "on this platform. Temperature readings will be empty."
        )

    def read_all_thermal(self) -> Dict[str, float]:
        """
        Return empty dict — no thermal sensors accessible on this platform.

        Returns:
            Dict[str, float]: Always empty on this platform.
        """
        return {}   # empty → callers skip thermal logging gracefully

    def is_available(self) -> bool:
        """Return False — no thermal sensor access on this platform."""
        return False

    def get_name(self) -> str:
        """Return reader name for logging."""
        return "DummyThermalReader"
