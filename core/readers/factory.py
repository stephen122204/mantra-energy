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
    def get_gpu_energy_uj(cls, energy_reader) -> Optional[int]:
        """
        Read GPU PP1 energy from any energy reader.
        Returns None on platforms where GPU MSR is unavailable.
        Callers must use this method — never call read_gpu_msr() directly.
        This preserves PAC-2: no platform-conditional logic outside factory.
        Args:
            energy_reader: Any EnergyReaderABC instance from get_energy_reader()
        Returns:
            GPU energy in µJ or None.
        """
        # read_gpu_msr() is defined on ABC as returning None by default
        # RAPLReader overrides it with real MSR read on Linux x86
        return energy_reader.read_gpu_msr()
    
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

            # GN100: SPBM spark_hwmon gives direct µJ counters for Grace CPU
            if caps.os == "Linux" and caps.is_grace_cpu and caps.has_spbm:
                return cls._make_spbm_reader(config, caps)
            
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
            # ARM (GN100): use ARM PMU reader when aarch64 + has_arm_pmu
            if caps.arch == "aarch64" and caps.has_arm_pmu:
                return cls._make_arm_pmu_reader(config)
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

        if caps.os == "Linux":
            # ARM (GN100): SensorReader reads hw_config thermal paths which are
            # x86-specific MSR/hwmon entries — returns {} on Grace.
            # ARMThermalReader discovers acpitz zones dynamically via sysfs.
            if caps.arch == "aarch64" and caps.has_thermal:
                return cls._make_arm_thermal_reader(config)
            # x86 Linux: SensorReader reads configured hwmon/sysfs paths
            if caps.has_thermal:
                return cls._make_sensor_reader(config)

        if caps.os == "Darwin":
            return cls._make_iokit_thermal_reader(config)

        # Windows / no thermal zones — stub
        return cls._make_dummy_thermal(config)

    @classmethod
    def _make_iokit_thermal_reader(cls, config: dict):
        from core.readers.darwin.iokit_thermal_reader import IOKitThermalReader
        logger.debug("ReaderFactory: instantiating IOKitThermalReader")
        return IOKitThermalReader(config)
        
    @classmethod
    def get_disk_reader(
        cls,
        config: dict = None,
        caps: Optional[PlatformCapabilities] = None,
    ):
        """
        Return correct disk I/O reader for current platform.
 
        Linux  → DiskReader (/proc/diskstats)
        macOS  → IOKitDiskReader (stub until Chunk 1.1)
        Other  → FallbackDiskReader (returns None)
 
        Args:
            config: hw_config dict — used for disk_device override.
            caps:   PlatformCapabilities override for testing.
        """
        caps   = caps or get_platform_capabilities()
        config = config or {}
 
        if caps.os == "Linux":
            from core.readers.disk_reader import DiskReader
            return DiskReader(config=config, pid=0)
 
        if caps.os == "Darwin":
            from core.readers.darwin.disk_reader import IOKitDiskReader
            return IOKitDiskReader(config=config, pid=0)
 
        from core.readers.fallback.disk_reader import FallbackDiskReader
        return FallbackDiskReader(config=config, pid=0)
    # ------------------------------------------------------------------
    # PRIVATE FACTORY HELPERS — one per concrete reader type
    # Each helper isolates the import so unneeded readers are never
    # imported on platforms where they would crash at import time.
    # ------------------------------------------------------------------
    @classmethod
    def get_turbostat_reader(
        cls,
        config=None,  # type: Optional[dict]
        caps=None,    # type: Optional[PlatformCapabilities]
    ):
        """
        Return correct turbostat reader for current platform.
 
        Linux x86  -> TurbostatReader (real turbostat via dynamic resolution)
        macOS      -> DummyTurbostatReader (LIMITED — no MSR access)
        Other      -> DummyTurbostatReader (LIMITED)
 
        PAC-2: only platform-conditional imports here — never in TurbostatReader.
        Binary path resolution via turbostat_resolver — never from hw_config.json.
 
        Args:
            config: hw_config dict.
            caps:   PlatformCapabilities override for testing.
        """
        caps   = caps or get_platform_capabilities()
        config = config or {}
 
        if caps.os == "Linux" and caps.arch == "x86_64":
            # Real turbostat — MSR access available, binary resolved at runtime
            from core.readers.turbostat_reader import TurbostatReader
            return TurbostatReader(config)
 
        # ARM Linux (GN100): cpufreq sysfs is the turbostat equivalent
        if caps.os == "Linux" and caps.arch == "aarch64":
            return cls._make_arm_cpufreq_reader(config)

        # macOS, ARM, Windows, unknown — no turbostat/MSR access
        from core.readers.fallback.dummy_turbostat_reader import DummyTurbostatReader
        logger.info(
            "get_turbostat_reader: platform=%s arch=%s -> DummyTurbostatReader (LIMITED)",
            caps.os, caps.arch,
        )
        return DummyTurbostatReader()
    @classmethod
    def get_msr_reader(
        cls,
        config=None,   # type: Optional[dict]
        caps=None,     # type: Optional[PlatformCapabilities]
    ):
        """
        Return correct MSR reader for current platform.
 
        Linux x86  -> MSRReader (msr_read C binary, setuid — compiled by fix_permissions.sh)
        Linux ARM  -> DummyMSRReader (LIMITED — no MSR binary for ARM)
        macOS      -> DummyMSRReader (LIMITED — IOKit deferred Chunk 1.2)
        Other      -> DummyMSRReader (LIMITED)
 
        PAC-2: only platform-conditional imports here.
        msr_read C binary path is fixed at core/msr_helper/msr_read — never configurable.
        """
        caps   = caps or get_platform_capabilities()
        config = config or {}
 
        if caps.os == "Linux" and caps.arch == "x86_64":
            from core.readers.msr_reader import MSRReader
            return MSRReader(config)
 
        # ARM, macOS, Windows, unknown — no MSR access
        from core.readers.fallback.dummy_msr_reader import DummyMSRReader
        logger.info(
            "get_msr_reader: platform=%s arch=%s -> DummyMSRReader (LIMITED)",
            caps.os, caps.arch,
        )
        return DummyMSRReader(config)
 
    @classmethod
    def get_scheduler_monitor(
        cls,
        config=None,   # type: Optional[dict]
        caps=None,     # type: Optional[PlatformCapabilities]
    ):
        """
        Return correct scheduler monitor for current platform.
 
        Linux      -> SchedulerMonitor (/proc/stat, /proc/interrupts)  MEASURED
        macOS      -> DummySchedulerMonitor (LIMITED — sysctl deferred Chunk 1.3)
        Other      -> DummySchedulerMonitor (LIMITED)
 
        PAC-2: only platform-conditional imports here.
        """
        caps   = caps or get_platform_capabilities()
        config = config or {}
 
        if caps.os == "Linux":
            from core.readers.scheduler_monitor import SchedulerMonitor
            return SchedulerMonitor(config)
 
        # macOS, Windows, unknown — no /proc
        from core.readers.fallback.dummy_scheduler_monitor import DummySchedulerMonitor
        logger.info(
            "get_scheduler_monitor: platform=%s -> DummySchedulerMonitor (LIMITED)",
            caps.os,
        )
        return DummySchedulerMonitor(config)   
     
    @staticmethod
    def _make_spbm_reader(config: dict, caps: "PlatformCapabilities"):
        """Import and instantiate SPBMEnergyReader (GN100 aarch64 MEASURED).
 
        PAC-2: import isolated here — never import SPBMEnergyReader elsewhere.
        hwmon_path injected from caps so reader never rediscovers at runtime.
        Falls back to DummyEnergyReader until 16-B delivers spbm_energy_reader.py.
        """
        try:
            from core.readers.spbm_energy_reader import SPBMEnergyReader  # type: ignore[import]
            return SPBMEnergyReader(config, hwmon_path=caps.spbm_hwmon_path)
        except ImportError:
            logger.warning(
                "_make_spbm_reader: spbm_energy_reader not yet available "
                "(16-B pending) — falling back to DummyEnergyReader"
            )
            from core.readers.fallback.dummy_energy_reader import DummyEnergyReader
            return DummyEnergyReader(config) 

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
    def _make_arm_pmu_reader(config: dict):
        """Instantiate ARMPMUReader — only reached on aarch64 with has_arm_pmu."""
        from core.readers.arm_pmu_reader import ARMPMUReader
        logger.debug("ReaderFactory: instantiating ARMPMUReader")
        return ARMPMUReader(config)

    @staticmethod
    def _make_arm_cpufreq_reader(config: dict):
        """Instantiate ARMCPUFreqReader — only reached on aarch64 Linux."""
        from core.readers.arm_cpufreq_reader import ARMCPUFreqReader
        logger.debug("ReaderFactory: instantiating ARMCPUFreqReader")
        return ARMCPUFreqReader(config)

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
    def _make_arm_thermal_reader(config: dict):
        """Import and instantiate ARMThermalReader (aarch64 sysfs thermal)."""
        from core.readers.arm_thermal_reader import ARMThermalReader
        logger.debug("ReaderFactory: instantiating ARMThermalReader")
        return ARMThermalReader(config)
 
    @staticmethod
    def _make_thermal_reader_v2(registered_zones: dict):
        """Import and instantiate ThermalReaderV2 (all Linux platforms, Thermal V2)."""
        from core.thermal.thermal_reader_v2 import ThermalReaderV2
        logger.debug("ReaderFactory: instantiating ThermalReaderV2 (%d zones)",
                     len(registered_zones))
        return ThermalReaderV2(registered_zones)
 
    @staticmethod
    def _make_cooling_reader(registered_devices: dict):
        """Import and instantiate CoolingReader (all Linux platforms)."""
        from core.thermal.cooling_reader import CoolingReader
        logger.debug("ReaderFactory: instantiating CoolingReader (%d devices)",
                     len(registered_devices))
        return CoolingReader(registered_devices)

    @staticmethod
    def _make_dummy_thermal(config: dict):
        """Return a minimal thermal stub for non-Linux / no-thermal platforms."""
        from core.readers.fallback.dummy_thermal_reader import DummyThermalReader
        logger.debug("ReaderFactory: instantiating DummyThermalReader")
        return DummyThermalReader(config)
