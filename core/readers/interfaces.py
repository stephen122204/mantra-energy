#!/usr/bin/env python3
"""
================================================================================
READER INTERFACES — Abstract Base Classes for All Hardware Readers
================================================================================

Purpose:
    Define the interface contract that every reader must implement.
    The rest of the codebase (EnergyEngine, ReaderFactory) talks only
    to these interfaces — never to concrete reader classes directly.

    This enables transparent swapping of:
        RAPLReader      ↔  EnergyEstimator  ↔  IOKitPowerReader  ↔  DummyEnergyReader

Interface Hierarchy:
    BaseReader          — common is_available() / get_name()
    ├── EnergyReaderABC — read_energy_uj(), get_domains()
    ├── CPUReaderABC    — read_instructions(), read_cycles(), read_ipc(), read_frequency_mhz()
    └── ThermalReaderABC— read_temperatures_dict()

Author: Deepak Panigrahy
================================================================================
"""

from abc import ABC, abstractmethod
from typing import Dict, List


# ============================================================================
# BASE — shared by all readers
# ============================================================================

class BaseReader(ABC):
    """
    Shared base for all hardware readers.

    Provides common methods that every reader must expose so that
    calling code can check availability without knowing the concrete type.
    """

    @abstractmethod
    def is_available(self) -> bool:
        """
        Return True if this reader can actually collect data on this platform.

        Used by EnergyEngine to decide whether to call a reader or skip it.
        Stub readers (Dummy, Estimator) should return False here so callers
        know the data is estimated/zero rather than real.

        Returns:
            bool: True if hardware access is confirmed; False otherwise.
        """
        ...

    @abstractmethod
    def get_name(self) -> str:
        """
        Return a short human-readable name for this reader.

        Used in logging and the platform summary display.

        Returns:
            str: e.g. 'RAPLReader', 'EnergyEstimator', 'DummyEnergyReader'
        """
        ...


# ============================================================================
# ENERGY READER INTERFACE
# ============================================================================

class EnergyReaderABC(BaseReader):
    """
    Interface for all energy measurement readers.

    Concrete implementations:
        RAPLReader       — Linux x86_64, reads /sys/class/powercap (MEASURED)
        IOKitPowerReader — macOS, reads power via IOKit then integrates (MEASURED)
        EnergyEstimator  — ARM VM, predicts via ML model (INFERRED)
        DummyEnergyReader— Unknown platform, returns zeros (LIMITED)

    All returned values are in microjoules (µJ) for consistency.
    Readers that measure power (watts) must perform the W×s→µJ conversion
    internally — callers always receive µJ.
    """

    @abstractmethod
    def read_energy_uj(self) -> Dict[str, int]:
        """
        Read current cumulative energy counters from all available domains.

        For RAPL readers this is a direct sysfs read (monotonically increasing).
        For power-based readers (IOKit) this returns integrated energy since
        the reader was initialised.

        Returns:
            Dict[str, int]: Domain name → energy in microjoules.
                            e.g. {'package-0': 12345678, 'core': 8765432}
                            Returns zeros dict on failure (never raises).
        """
        ...

    @abstractmethod
    def get_domains(self) -> List[str]:
        """
        Return the list of energy domains this reader can provide.

        Returns:
            List[str]: e.g. ['package-0', 'core', 'uncore']
                       Empty list for stub/dummy readers.
        """
        ...


# ============================================================================
# CPU READER INTERFACE
# ============================================================================

class CPUReaderABC(BaseReader):
    """
    Interface for CPU performance counter readers.

    Concrete implementations:
        PerfReader   — Linux, reads via `perf stat` or perf_event_open syscall
        DummyCPUReader — stub returning zeros for unsupported platforms

    Values represent totals since the last call (delta mode), not cumulative.
    """

    @abstractmethod
    def read_instructions(self) -> int:
        """
        Return retired instruction count since last call.

        Returns:
            int: Instruction count, or 0 if unavailable.
        """
        ...

    @abstractmethod
    def read_cycles(self) -> int:
        """
        Return CPU cycle count since last call.

        Returns:
            int: Cycle count, or 0 if unavailable.
        """
        ...

    @abstractmethod
    def read_ipc(self) -> float:
        """
        Return instructions-per-cycle ratio.

        Returns:
            float: IPC value, or 0.0 if unavailable.
        """
        ...

    @abstractmethod
    def read_frequency_mhz(self) -> float:
        """
        Return current CPU frequency in MHz.

        Returns:
            float: Frequency in MHz, or 0.0 if unavailable.
        """
        ...


# ============================================================================
# THERMAL READER INTERFACE
# ============================================================================

class ThermalReaderABC(BaseReader):
    """
    Interface for temperature sensor readers.

    Concrete implementations:
        SensorReader    — Linux, reads /sys/class/thermal/thermal_zoneN/temp
        DummyThermalReader — stub returning empty dict for unsupported platforms
    """

    @abstractmethod
    def read_all_thermal(self) -> Dict[str, float]:
        """
        Read current temperatures from all available thermal sensors.

        Returns:
            Dict[str, float]: Sensor name → temperature in Celsius.
                              e.g. {'cpu_package': 52.0, 'TCPU': 48.5}
                              Returns empty dict if no sensors available.
        """
        ...
