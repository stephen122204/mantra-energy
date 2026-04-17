#!/usr/bin/env python3
"""
================================================================================
READER FACTORY — Select Correct Hardware Reader Based on Platform
================================================================================

Purpose:
    Single entry point for obtaining energy, CPU, and thermal readers.
    Reads PlatformCapabilities (from platform.py) and returns the correct
    concrete reader so EnergyEngine never needs to know the platform.

    This is the only place in the codebase that contains platform-conditional
    import logic. All other modules import from here.

Reader dispatch table:
    Measurement Mode  │  OS      │  Energy Reader       │  Source
    ──────────────────┼──────────┼──────────────────────┼──────────────────
    MEASURED          │  Linux   │  RAPLReader           │  sysfs µJ counter
    MEASURED          │  macOS   │  IOKitPowerReader     │  IOKit W → µJ
    INFERRED          │  any     │  EnergyEstimator      │  ML model (stub)
    LIMITED           │  any     │  DummyEnergyReader    │  zeros + warning

CPU and Thermal readers follow the same pattern but always fall back
to the existing PerfReader / SensorReader on supported Linux platforms.

Author: Deepak Panigrahy
================================================================================
"""

import logging
from typing import Optional

from core.utils.platform import (
    INFERRED,
    LIMITED,
    MEASURED,
    PlatformCapabilities,
    get_platform_capabilities,
)
from core.readers.interfaces import EnergyReaderABC, CPUReaderABC, ThermalReaderABC

logger = logging.getLogger(__name__)


# ============================================================================
# READER FACTORY
# ============================================================================

class ReaderFactory:
    """
    Factory that maps PlatformCapabilities → concrete reader instances.

    All get_*_reader() methods are classmethods — no instance needed.
    They accept an optional caps argument for testing (inject a mock
    PlatformCapabilities without touching the real hw_config.json).

    Usage:
        energy_reader  = ReaderFactory.get_energy_reader()
        cpu_reader     = ReaderFactory.get_cpu_reader(config)
        thermal_reader = ReaderFactory.get_thermal_reader(config)
    """

    @classmethod
    def get_energy_reader(
        cls,
        config: dict = None,
        caps:   Optional[PlatformCapabilities] = None,
    ) -> EnergyReaderABC:
        """
        Return the correct energy reader for the current platform.

        Dispatch logic:
            MEASURED + Linux  → RAPLReader      (direct sysfs µJ counter)
            MEASURED + macOS  → IOKitPowerReader (real sensor, W→µJ conversion)
            INFERRED          → EnergyEstimator  (ML model stub)
            LIMITED           → DummyEnergyReader(zeros + warning)

        Args:
            config: hw_config dict passed through to the reader __init__.
                    If None, an empty dict is used (readers handle gracefully).
            caps:   Optional PlatformCapabilities override (for testing).
                    If None, uses the process-level cached capabilities.

        Returns:
            EnergyReaderABC: Concrete reader implementing the energy interface.
        """
        # Use injected caps (testing) or the process-level cached detection
        caps   = caps or get_platform_capabilities()
        config = config or {}
        mode   = caps.measurement_mode

        logger.info(
            "ReaderFactory: selecting energy reader for mode=%s os=%s arch=%s",
            mode, caps.os, caps.arch,
        )

        if mode == MEASURED:
            # macOS: IOKit provides real power sensor (watts); reader converts to µJ
            if caps.os == "Darwin":
                return cls._make_iokit_reader(config)

            # Linux x86_64: RAPL sysfs gives direct µJ counters
            return cls._make_rapl_reader(config)

        if mode == INFERRED:
            # ARM VM or x86 without RAPL: use ML estimation (stub for now)
            return cls._make_estimator(config)

        # LIMITED or any unknown mode: safe zeros fallback
        return cls._make_dummy(config)

    @classmethod
    def get_cpu_reader(
        cls,
        config: dict = None,
        caps:   Optional[PlatformCapabilities] = None,
    ) -> CPUReaderABC:
        """
        Return the correct CPU performance counter reader.

        Currently wraps the existing PerfReader on Linux (all modes)
        and falls back to DummyCPUReader on other platforms.

        Args:
            config: hw_config dict passed to the reader.
            caps:   Optional PlatformCapabilities override (for testing).

        Returns:
            CPUReaderABC: Concrete reader implementing the CPU interface.
        """
        caps   = caps or get_platform_capabilities()
        config = config or {}

        if caps.os == "Linux":
            # PerfReader works on Linux regardless of measurement mode
            # (perf_event_open is available even without RAPL)
            return cls._make_perf_reader(config)

        # macOS / Windows / unknown — stub
        return cls._make_dummy_cpu(config)

    @classmethod
    def get_thermal_reader(
        cls,
        config: dict = None,
        caps:   Optional[PlatformCapabilities] = None,
    ) -> ThermalReaderABC:
        """
        Return the correct thermal sensor reader.

        On Linux (all modes) the existing SensorReader reads sysfs thermal
        zones discovered by detect_hardware.py. Other platforms get a stub.

        Args:
            config: hw_config dict passed to the reader.
            caps:   Optional PlatformCapabilities override (for testing).

        Returns:
            ThermalReaderABC: Concrete reader implementing the thermal interface.
        """
        caps   = caps or get_platform_capabilities()
        config = config or {}

        if caps.os == "Linux" and caps.has_thermal:
            return cls._make_sensor_reader(config)

        # macOS / Windows / ARM without thermal zones — stub
        return cls._make_dummy_thermal(config)

    # ------------------------------------------------------------------
    # PRIVATE FACTORY HELPERS — one per concrete reader type
    # Each helper isolates the import so unneeded readers are never
    # imported on platforms where they would crash at import time.
    # ------------------------------------------------------------------

    @staticmethod
    def _make_rapl_reader(config: dict):
        """Import and instantiate RAPLReader (Linux x86_64 MEASURED)."""
        from core.readers.rapl_reader import RAPLReader
        logger.debug("ReaderFactory: instantiating RAPLReader")
        return RAPLReader(config)

    @staticmethod
    def _make_iokit_reader(config: dict):
        """Import and instantiate IOKitPowerReader (macOS MEASURED)."""
        from core.readers.darwin.iokit_power_reader import IOKitPowerReader
        logger.debug("ReaderFactory: instantiating IOKitPowerReader")
        return IOKitPowerReader(config)

    @staticmethod
    def _make_estimator(config: dict):
        """Import and instantiate EnergyEstimator (INFERRED mode)."""
        from core.readers.fallback.energy_estimator import EnergyEstimator
        logger.debug("ReaderFactory: instantiating EnergyEstimator (INFERRED)")
        return EnergyEstimator(config)

    @staticmethod
    def _make_dummy(config: dict):
        """Import and instantiate DummyEnergyReader (LIMITED mode)."""
        from core.readers.fallback.dummy_energy_reader import DummyEnergyReader
        logger.debug("ReaderFactory: instantiating DummyEnergyReader (LIMITED)")
        return DummyEnergyReader(config)

    @staticmethod
    def _make_perf_reader(config: dict):
        """Import and instantiate existing PerfReader (Linux CPU counters)."""
        from core.readers.perf_reader import PerfReader
        logger.debug("ReaderFactory: instantiating PerfReader")
        return PerfReader(config)

    @staticmethod
    def _make_dummy_cpu(config: dict):
        """Return a minimal CPU stub for non-Linux platforms."""
        from core.readers.fallback.dummy_cpu_reader import DummyCPUReader
        logger.debug("ReaderFactory: instantiating DummyCPUReader")
        return DummyCPUReader(config)

    @staticmethod
    def _make_sensor_reader(config: dict):
        """Import and instantiate existing SensorReader (Linux thermal)."""
        from core.readers.sensor_reader import SensorReader
        logger.debug("ReaderFactory: instantiating SensorReader")
        reader = SensorReader(config)
        reader.initialize()     # SensorReader requires explicit init call
        return reader

    @staticmethod
    def _make_dummy_thermal(config: dict):
        """Return a minimal thermal stub for non-Linux / no-thermal platforms."""
        from core.readers.fallback.dummy_thermal_reader import DummyThermalReader
        logger.debug("ReaderFactory: instantiating DummyThermalReader")
        return DummyThermalReader(config)
