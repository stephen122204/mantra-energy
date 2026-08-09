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
    ├── EnergyReaderABC — read_energy_uj(), get_domains(),
    │                     get_method_id(), get_confidence()
    ├── CPUReaderABC    — read_instructions(), read_cycles(),
    │                     read_ipc(), read_frequency_mhz()
    └── ThermalReaderABC— read_temperatures_dict()

Methodology Attributes (Chunk 9):
    Every EnergyReaderABC subclass MUST declare these class-level attributes.
    The seed script (scripts/seed_methodology.py) reads them automatically
    to populate measurement_method_registry — no manual config needed.

    METHOD_ID           str   — unique key in measurement_method_registry
    METHOD_NAME         str   — human-readable display name
    METHOD_LAYER        str   — 'silicon' | 'os' | 'application'
    METHOD_CONFIDENCE   float — 0.0 (stub/zeros) → 1.0 (real hardware)
    METHOD_PARAMS       dict  — default parameters for this method
    FALLBACK_METHOD_ID  str   — method_id to use if this reader fails
    FORMULA_LATEX       str   — KaTeX formula for energy calculation
    METHOD_REFERENCES   list  — paper/standard references (list of dicts)

Author: Deepak Panigrahy
================================================================================
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
from core.models.normalized_energy_reading import NormalizedEnergyReading
from core.readers.measurement_schema import MeasurementSchema
 


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
        Return True if this reader can collect data on this platform.

        Used by EnergyEngine to decide whether to call a reader or skip it.
        Stub readers (Dummy, Estimator) return False so callers know
        the data is estimated/zero rather than real.

        Returns:
            bool: True if hardware access confirmed; False otherwise.
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

    Methodology Class Attributes (REQUIRED on every subclass):
        Seed script reads these to auto-populate measurement_method_registry.
        Declare them at class level — not in __init__.
    """

    # -------------------------------------------------------------------------
    # Methodology class attributes — REQUIRED on every subclass.
    # Defaults here are sentinel values; subclass must override all of them.
    # -------------------------------------------------------------------------

    # Unique key matching measurement_method_registry.id
    METHOD_ID: str = "unknown_reader"

    # Human-readable display name for UI and reports
    METHOD_NAME: str = "Unknown Reader"

    # Architectural layer: 'silicon' | 'os' | 'orchestration' | 'application'
    METHOD_LAYER: str = "silicon"

    # Confidence: 1.0 = real hardware, 0.5 = partial/stub, 0.0 = zeros
    METHOD_CONFIDENCE: float = 0.0

    # Default parameters for this method (JSON-serialisable dict)
    METHOD_PARAMS: dict = {}

    # method_id of fallback reader if this one fails or is unavailable
    FALLBACK_METHOD_ID: Optional[str] = None

    # KaTeX formula — updated here when formula changes, seed picks it up
    FORMULA_LATEX: str = ""

    # Paper / standard references — human written, lives with the code
    # Each entry: {ref_type, title, authors, year, venue, doi, url,
    #              relevance, cited_text, page_or_section}
    METHOD_REFERENCES: List[dict] = []

    # -------------------------------------------------------------------------
    # Abstract interface — subclass must implement these
    # -------------------------------------------------------------------------

    def get_measurement_schema(self):
        # type: () -> MeasurementSchema
        """
        Declare this reader's measurement capabilities.
 
        Returns a frozen MeasurementSchema describing:
        - Which domains this platform measures (native keys + canonical names)
        - Maximum safe sampling rate
        - Counter bit width for wraparound handling
        - Domain hierarchy for conservation invariant checks
 
        Called ONCE at EnergyCollector startup and cached.
        MUST NOT perform I/O or read hardware state.
        Subclasses that do not override this return SCHEMA_DUMMY (safe default).
        """
        from core.readers.measurement_schema import SCHEMA_DUMMY
        return SCHEMA_DUMMY   # safe default — subclasses override
    
    @abstractmethod
    @abstractmethod
    def read_normalized(self) -> NormalizedEnergyReading:
        """Return a canonical energy snapshot.

        Each reader maps its platform-specific keys to canonical fields here.
        This is the ONLY place platform key names appear in the codebase.
        Downstream consumers access typed attributes, never raw dict keys.

        Returns:
            NormalizedEnergyReading: Immutable frozen dataclass.
            Fields are None when the platform lacks that domain (PAC-3).
        """
        ...

    def read_energy_uj(self) -> Dict[str, int]:
        """
        Read current cumulative energy counters from all available domains.

        For RAPL readers this is a direct sysfs read (monotonically increasing).
        For power-based readers (IOKit) returns integrated energy since init.

        Returns:
            Dict[str, int]: Domain → energy in microjoules.
                e.g. {'package-0': 12345678, 'core': 8765432}
                Returns zeros dict on failure (never raises).
        """
        ...


    @abstractmethod
    def get_domains(self) -> List[str]:
        """
        Return list of energy domains this reader can provide.

        Returns:
            List[str]: e.g. ['package-0', 'core', 'uncore']
                       Empty list for stub/dummy readers.
        """
        ...

    def read_gpu_msr(self) -> Optional[int]:
            """
            Read GPU PP1 energy via MSR 0x641 (Intel Tiger Lake only).
            Default returns None — only RAPLReader overrides with real read.
            Never raises. NULL-safe: callers must handle None.
            Returns:
                Energy in µJ as int, or None if unavailable on this platform.
            """
            return None
    
    # -------------------------------------------------------------------------
    # Methodology helpers — concrete, no override needed
    # -------------------------------------------------------------------------

    def get_method_id(self) -> str:
        """
        Return the method registry ID for this reader.

        Used by capture_pending() to tag provenance buffer entries.
        Reads from class attribute — no instance state needed.

        Returns:
            str: e.g. 'rapl_msr_pkg_energy'
        """
        return self.__class__.METHOD_ID

    def get_confidence(self) -> float:
        """
        Return confidence score for this reader's measurements.

        1.0 = real hardware counter (RAPL, IOKit fully implemented)
        0.5 = partial implementation or stub with known limitations
        0.0 = zeros / stub not yet implemented

        Returns:
            float: Confidence in [0.0, 1.0]
        """
        return self.__class__.METHOD_CONFIDENCE


# ============================================================================
# CPU READER INTERFACE
# ============================================================================

class CPUReaderABC(BaseReader):
    """
    Interface for CPU performance counter readers.

    Concrete implementations:
        PerfReader     — Linux, reads via perf_event_open syscall
        DummyCPUReader — stub returning zeros for unsupported platforms

    Values represent totals since last call (delta mode), not cumulative.
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
    @abstractmethod
    def start_process_measurement(self, pid: int = 0) -> None:
        """
        Start continuous counter collection attached to task process.
 
        Args:
            pid: OS pid of the task process. If 0, fall back to
                 system-wide timed snapshot at stop().
        """
        ...
 
    @abstractmethod
    def stop_process_measurement(self):
        """
        Stop collection and return accumulated counters.
 
        Returns:
            PerformanceCounters with values measured during task window.
        """
        ...

# ============================================================================
# THERMAL READER INTERFACE
# ============================================================================

class ThermalReaderABC(BaseReader):
    """
    Interface for temperature sensor readers.

    Concrete implementations:
        SensorReader       — Linux, reads /sys/class/thermal/thermal_zoneN/temp
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
class ThermalReaderV2ABC(BaseReader):
    """
    Interface for normalized per-zone thermal readers (Thermal V2).
 
    Concrete implementations:
        ThermalReaderV2   — Linux sysfs, all platforms (x86_64 + aarch64)
        DummyThermalReaderV2 — stub for Darwin / unsupported platforms
 
    Unlike ThermalReaderABC which returns a flat dict, ThermalReaderV2ABC
    returns a list of per-zone dicts with quality_flag and invalid_reason.
    """
 
    @abstractmethod
    def read_all_zones(self) -> List[Dict]:
        """
        Read temperature from every registered thermal zone.
 
        Returns:
            List of dicts, one per zone:
                zone_id:        int   — FK to thermal_zones table
                timestamp_ns:   int   — epoch nanoseconds
                temp_celsius:   float — raw reading (may be invalid)
                quality_flag:   str   — VALID|OUT_OF_RANGE|READ_FAILED|MISSING
                invalid_reason: str|None
        """
        ...
 
    @abstractmethod
    def read_all_thermal(self) -> Dict:
        """Legacy interface: {zone_type: celsius}. VALID readings only."""
        ...
 
    @abstractmethod
    def is_available(self) -> bool:
        """Return True if at least one zone has a readable temp file."""
        ...
 
 
class CoolingReaderABC(BaseReader):
    """
    Interface for cooling device state readers.
 
    Concrete implementations:
        CoolingReader     — Linux sysfs /sys/class/thermal/cooling_device*
        DummyCoolingReader — stub for Darwin / unsupported platforms
    """
 
    @abstractmethod
    def read_all_devices(self) -> List[Dict]:
        """
        Read cur_state from every registered cooling device.
 
        Returns:
            List of dicts, one per device:
                device_id:      int   — FK to cooling_devices table
                timestamp_ns:   int   — epoch nanoseconds
                cur_state:      int   — raw kernel state value
                quality_flag:   str   — VALID|OUT_OF_RANGE|READ_FAILED|MISSING
                invalid_reason: str|None
        """
        ...
 
    @abstractmethod
    def detect_throttle(self, readings: List[Dict]) -> bool:
        """Return True if any throttle-role device has cur_state > 0 (VALID)."""
        ...
 
    @abstractmethod
    def is_available(self) -> bool:
        """Return True if at least one device is readable."""
        ...

class TurbostatReaderABC(BaseReader):
    """
    ABC for turbostat-based CPU C-state and power metrics reader.
 
    Implementations:
      Linux x86  → TurbostatReader (real turbostat binary via factory)
      macOS      → DummyTurbostatReader (returns empty DataFrame, never raises)
      Other      → DummyTurbostatReader
 
    C-state residency (C1/C3/C6/C10) is the primary ALEOE training signal.
    These metrics are only accessible via turbostat/MSR — not via /proc or /sys.
    """
 
    @abstractmethod
    def start_monitoring(self, interval_ms: int = 100) -> None:
        """Start continuous turbostat monitoring in background."""
        ...
 
    @abstractmethod
    def stop_monitoring(self) -> dict:
        """
        Stop monitoring and return results dict.
 
        Returns:
            {
                'dataframe': pd.DataFrame | None,
                'num_samples': int,
                'duration_seconds': float,
                'summary': dict,
            }
        """
        ...
 
    @abstractmethod
    def get_column_mapping(self) -> dict:
        """Return mapping of internal metric names to turbostat column names."""
        ...
class MSRReaderABC(BaseReader):
    """
    ABC for MSR (Model Specific Register) reader.
 
    Implementations:
      Linux x86  -> MSRReader (msr_read C binary, setuid root)   MEASURED
      Linux ARM  -> DummyMSRReader                               LIMITED
      macOS      -> DummyMSRReader (IOKit impl deferred Chunk 1.2) LIMITED
      Other      -> DummyMSRReader                               LIMITED
 
    MSR provides C-state counters and thermal data directly from hardware.
    C-state counters are ALEOE's primary optimization signal.
    msr_read C binary compiled and setuid by fix_permissions.sh — once only.
    """
 
    @abstractmethod
    def read_msr(self, msr_addr, cpu=0, pin=True):
        # type: (int, int, bool) -> Optional[int]
        """Read a single MSR register. Returns None if unavailable."""
        ...
 
    @abstractmethod
    def read_cstate_counters(self, cpu=0, pin=True):
        # type: (int, bool) -> Dict[str, Any]
        """Read C-state residency counters. Returns empty dict if unavailable."""
        ...
 
    @abstractmethod
    def snapshot_cstate_counters(self):
        # type: () -> Optional[Dict]
        """Snapshot current C-state counters for delta computation."""
        ...
 
 
class SchedulerMonitorABC(BaseReader):
    """
    ABC for OS scheduler and interrupt monitor.
 
    Implementations:
      Linux      -> SchedulerMonitor (/proc/stat, /proc/interrupts)  MEASURED
      macOS      -> DummySchedulerMonitor                            LIMITED
      Other      -> DummySchedulerMonitor                            LIMITED
 
    Reads context switches, CPU times, interrupt rates via /proc.
    /proc is Linux-only — macOS uses sysctl (deferred Chunk 1.3).
    """
 
    @abstractmethod
    def read_context_switches(self):
        # type: () -> Tuple[int, int]
        """Return (voluntary, involuntary) context switches."""
        ...
 
    @abstractmethod
    def read_all(self):
        # type: () -> Dict[str, Any]
        """Return all scheduler metrics as dict."""
        ...
 
    @abstractmethod
    def start_interrupt_sampling(self, pid=0):
        # type: (int) -> None
        """Start interrupt sampling for given pid."""
        ...
 
    @abstractmethod
    def stop_interrupt_sampling(self):
        # type: () -> list
        """Stop sampling and return collected interrupt samples."""
        ...
 
    @abstractmethod
    def sample_interrupts(self):
        # type: () -> None
        """Record one interrupt sample."""
        ...
class DiskReaderABC(ABC):
    """ABC for disk I/O readers — Linux/macOS implementations."""
    @abstractmethod
    def is_available(self) -> bool: ...
    @abstractmethod
    def sample(self) -> Optional[dict]: ...
    @abstractmethod
    def _detect_device(self) -> str: ...
class NICReaderABC(ABC):
    """ABC for NIC byte counter readers — Linux/macOS/fallback implementations."""
    @abstractmethod
    def is_available(self) -> bool: ...
    @abstractmethod
    def get_name(self) -> str: ...
    @abstractmethod
    def detect_interface(self) -> Optional[str]: ...
    @abstractmethod
    def get_pci_address(self) -> Optional[str]: ...
    @abstractmethod
    def read_sample(self) -> Optional[dict]: ...
