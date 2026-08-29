"""
Apple Silicon PMU performance counter reader via kperf/kperfdata.

Reads CPU performance counters (instructions, cycles, L1D cache misses)
on macOS arm64 by calling a compiled C helper binary that accesses
Apple's private kperf.framework and kperfdata.framework.

The helper requires root (invoked via sudo with a passwordless sudoers
rule). If sudo is unavailable or the helper is not installed, all
counter fields return 0 (graceful degradation per PAC-4).

Method ID: kperf_pmu_v1
Confidence: 0.85 (private API, sudo required, system-wide not per-process)
Layer: silicon

Design decisions:
  - C helper binary instead of in-process ctypes because kpc_set_config()
    requires root and we do not want the Python process running as root.
  - Two snapshot pattern (start/stop): helper called at measurement
    start and stop, delta computed in Python. Same pattern as IOReport
    DVFS frequency reader.
  - System-wide counters (all CPUs, all processes) because per-process
    PMU sampling requires root + kperf_sample_thread. During LLM
    inference on a dedicated Mac, the workload dominates CPU usage,
    making system-wide counters a reasonable approximation.
"""

import json
import logging
import os
import platform
import subprocess
from typing import Dict, Optional

from core.readers.interfaces import CPUReaderABC
from core.models.performance_counters import PerformanceCounters

logger = logging.getLogger(__name__)

# Path to the compiled C helper (installed by fix_permissions.sh)
_HELPER_PATH = "/usr/local/bin/alems_kperf_reader"

# Timeout for helper subprocess (seconds). The helper should return
# in under 100ms; 5s is a generous safety margin.
_HELPER_TIMEOUT_S = 5


class KPerfPMUReader(CPUReaderABC):
    """
    Reads Apple Silicon PMU counters via a compiled C helper binary.

    The helper is called via sudo, reads system-wide counters from
    kperf/kperfdata, and prints JSON to stdout. This reader calls
    the helper at measurement start and stop, then computes deltas.

    Inherits CPUReaderABC (PAC-1 compliant).
    Imported only in factory.py (PAC-2 compliant).
    Returns 0/None on any failure (PAC-4 compliant).
    """

    # ===== Methodology metadata (for seed_methodology.py) =====
    METHOD_ID = "kperf_pmu_v1"
    METHOD_NAME = "Apple Silicon kperf PMU Counters"
    METHOD_PROVENANCE = "MEASURED"
    METHOD_LAYER = "silicon"
    METHOD_CONFIDENCE = 0.85
    METHOD_DOC = "07-energy-readers-methodology.md"
    METHOD_SECTION = "Apple Silicon PMU Counters (kperf_pmu_v1)"
    METHOD_PARAMS = {
        "C_start": "PMU counter snapshot at measurement start",
        "C_stop":  "PMU counter snapshot at measurement stop",
    }
    FALLBACK_METHOD_ID = "dummy_cpu_reader"
    METHOD_DESCRIPTION = (
        "Reads CPU performance counters (instructions, cycles, L1D cache "
        "misses) on Apple Silicon via kperf/kperfdata private frameworks. "
        "System-wide counters across all CPUs. Requires sudo for PMU "
        "configuration. Confidence 0.85 due to private API and system-wide "
        "(not per-process) scope."
    )

    def __init__(self, config=None):
        # type: (Optional[Dict]) -> None
        """
        Initialize the kperf PMU reader.

        Args:
            config: Hardware configuration dict (unused, kept for
                    interface compatibility with factory pattern).
        """
        self._config = config or {}
        # Snapshot buffers for two-snapshot delta pattern
        self._snapshot_start = None  # type: Optional[Dict]
        self._snapshot_stop = None   # type: Optional[Dict]
        # Last computed delta (populated after stop_process_measurement)
        self._last_delta = None      # type: Optional[Dict]
        # Availability cache (checked once at startup, then reused)
        self._available = None       # type: Optional[bool]

    # =================================================================
    # CPUReaderABC abstract method implementations
    # =================================================================

    def is_available(self):
        # type: () -> bool
        """
        Check if the kperf PMU reader can operate.

        Returns False gracefully when:
          - Not on macOS (PAC-4)
          - Helper binary not installed
          - sudo not available (no sudoers rule)
          - Running in a VM (kperf unavailable)

        Returns:
            bool: True if helper binary exists and can run with sudo.
        """
        # Return cached result to avoid repeated subprocess calls
        if self._available is not None:
            return self._available

        # Guard: macOS only - early return pattern (DC-4)
        if platform.system() != "Darwin":
            logger.debug("KPerfPMUReader: not Darwin, unavailable")
            self._available = False
            return False

        # Guard: helper binary must exist at the installed path
        if not os.path.isfile(_HELPER_PATH):
            logger.warning(
                "KPerfPMUReader: helper not found at %s. "
                "Run: cc -O2 -o kperf_reader scripts/helpers/kperf_reader.c "
                "&& sudo cp kperf_reader %s",
                _HELPER_PATH, _HELPER_PATH
            )
            self._available = False
            return False

        # Guard: sudo must work without password for the helper
        # (requires sudoers rule installed by fix_permissions.sh)
        try:
            result = subprocess.run(
                ["sudo", "-n", _HELPER_PATH],
                capture_output=True, text=True,
                timeout=_HELPER_TIMEOUT_S
            )
            if result.returncode != 0:
                logger.warning(
                    "KPerfPMUReader: helper returned exit code %d. "
                    "stderr: %s",
                    result.returncode,
                    result.stderr.strip()[:200]
                )
                self._available = False
                return False
            # Verify JSON output is parseable and contains required fields
            data = json.loads(result.stdout.strip())
            if "instructions" not in data or "cycles" not in data:
                logger.warning(
                    "KPerfPMUReader: helper output missing required fields"
                )
                self._available = False
                return False
        except (subprocess.TimeoutExpired, json.JSONDecodeError,
                FileNotFoundError, OSError) as e:
            logger.warning("KPerfPMUReader: availability check failed: %s", e)
            self._available = False
            return False

        logger.info("KPerfPMUReader: available and verified")
        self._available = True
        return True

    def get_name(self):
        # type: () -> str
        """Return reader identifier for logging and provenance."""
        return "KPerfPMUReader"

    def read_instructions(self):
        # type: () -> int
        """
        Return instructions from last delta measurement.

        This is a convenience method for the CPUReaderABC interface.
        For full counter data, use start/stop_process_measurement().

        Returns:
            int: Instruction count from last delta, or 0.
        """
        if self._last_delta:
            return self._last_delta.get("instructions", 0)
        return 0

    def read_cycles(self):
        # type: () -> int
        """
        Return CPU cycles from last delta measurement.

        Returns:
            int: Cycle count from last delta, or 0.
        """
        if self._last_delta:
            return self._last_delta.get("cycles", 0)
        return 0

    def read_ipc(self):
        # type: () -> float
        """
        Return instructions per cycle from last delta.

        Returns:
            float: IPC ratio, or 0.0 if cycles is zero.
        """
        if not self._last_delta:
            return 0.0
        cycles = self._last_delta.get("cycles", 0)
        instructions = self._last_delta.get("instructions", 0)
        # Guard against division by zero (DC-4 early return)
        if cycles <= 0:
            return 0.0
        return instructions / cycles

    def read_frequency_mhz(self):
        # type: () -> float
        """
        CPU frequency is NOT measured by the PMU reader.

        Frequency comes from IOReportCPUFreqReader (separate reader).
        Returns 0.0 per CPUReaderABC contract so the factory chain
        does not treat this as a frequency source.

        Returns:
            float: Always 0.0 (frequency measured elsewhere).
        """
        return 0.0

    # =================================================================
    # Two-snapshot measurement interface
    # =================================================================
    @property
    def perf_available(self):
        """Compatibility shim for energy_engine.py has_perf gate."""
        return self.is_available()
    
    def start_process_measurement(self):
        # type: () -> None
        """
        Take the start snapshot of PMU counters.

        Calls the C helper via sudo, stores JSON result as start snapshot.
        If the helper fails, start snapshot is None and stop will return
        zero counters (graceful degradation per PAC-4).
        """
        self._snapshot_start = self._read_helper()
        self._snapshot_stop = None
        self._last_delta = None
        if self._snapshot_start is None:
            logger.warning(
                "KPerfPMUReader: start snapshot failed, "
                "counters will be zero for this run"
            )

    def stop_process_measurement(self):
        # type: () -> PerformanceCounters
        """
        Take the stop snapshot and compute deltas.

        Returns a PerformanceCounters object with the same fields as
        PerfReader on Linux, so the harness needs zero changes.

        Returns:
            PerformanceCounters: Delta counters between start and stop.
                All fields 0 if either snapshot failed.
        """
        self._snapshot_stop = self._read_helper()
        counters = PerformanceCounters()

        # Both snapshots must succeed for a valid delta (DC-4 early return)
        if self._snapshot_start is None or self._snapshot_stop is None:
            logger.warning(
                "KPerfPMUReader: snapshot missing (start=%s, stop=%s), "
                "returning zero counters",
                "OK" if self._snapshot_start else "FAIL",
                "OK" if self._snapshot_stop else "FAIL"
            )
            self._last_delta = {}
            return counters

        # Compute deltas (stop minus start for each field)
        delta = {}
        for key in self._snapshot_stop:
            start_val = self._snapshot_start.get(key, 0)
            stop_val = self._snapshot_stop.get(key, 0)
            # Counter overflow protection: if stop < start, the counter
            # wrapped. On 64-bit counters this is astronomically unlikely
            # during a single run, but we handle it defensively.
            if stop_val >= start_val:
                delta[key] = stop_val - start_val
            else:
                logger.warning(
                    "KPerfPMUReader: counter %s wrapped "
                    "(start=%d, stop=%d), using stop value as-is",
                    key, start_val, stop_val
                )
                delta[key] = stop_val

        self._last_delta = delta

        # Map helper JSON fields to PerformanceCounters fields
        counters.instructions_retired = delta.get("instructions", 0)
        counters.cpu_cycles = delta.get("cycles", 0)

        # cache_misses = L1D load misses + store misses (combined metric)
        # matches semantics of Linux perf cache-misses on L1D
        counters.cache_misses = (
            delta.get("l1d_miss_ld", 0) + delta.get("l1d_miss_st", 0)
        )

        # cache_references = L1D TLB accesses (proxy for total accesses)
        # L1D_TLB_ACCESS is the closest available event on a14.plist
        counters.cache_references = delta.get("l1d_tlb_access", 0)

        # l1d_cache_misses: use NONSPEC variant (retired only, most accurate)
        counters.l1d_cache_misses = delta.get("l1d_miss_nonspec", 0)

        # L2 and L3: NOT available on M1 (a14.plist has no such events)
        # These remain 0 here and NULL in the DB (MIC-1: NULL not 0)
        counters.l2_cache_misses = 0
        counters.l3_cache_hits = 0
        counters.l3_cache_misses = 0

        logger.info(
            "KPerfPMUReader: delta counters: %d instructions, %d cycles, "
            "%.2f IPC, %d L1D misses",
            counters.instructions_retired,
            counters.cpu_cycles,
            counters.instructions_per_cycle(),
            counters.l1d_cache_misses
        )

        return counters

    # =================================================================
    # Internal helper
    # =================================================================

    def _read_helper(self):
        # type: () -> Optional[Dict]
        """
        Call the C helper binary and parse its JSON output.

        The helper prints a single JSON line to stdout with fields:
        instructions, cycles, l1d_miss_ld, l1d_miss_st,
        l1d_miss_nonspec, l1d_tlb_access.

        Returns:
            dict: Parsed JSON with integer counter values, or None on failure.
        """
        try:
            result = subprocess.run(
                ["sudo", "-n", _HELPER_PATH],
                capture_output=True, text=True,
                timeout=_HELPER_TIMEOUT_S
            )
            if result.returncode != 0:
                logger.warning(
                    "KPerfPMUReader: helper exit code %d, stderr: %s",
                    result.returncode,
                    result.stderr.strip()[:200]
                )
                return None

            # Parse JSON output from C helper
            data = json.loads(result.stdout.strip())
            return data

        except subprocess.TimeoutExpired:
            logger.warning(
                "KPerfPMUReader: helper timed out after %ds",
                _HELPER_TIMEOUT_S
            )
            return None
        except json.JSONDecodeError as e:
            logger.warning(
                "KPerfPMUReader: helper output not valid JSON: %s", e
            )
            return None
        except FileNotFoundError:
            # sudo or helper binary missing - treat as unavailable
            logger.warning(
                "KPerfPMUReader: sudo or helper binary not found"
            )
            return None
        except OSError as e:
            logger.warning(
                "KPerfPMUReader: OS error calling helper: %s", e
            )
            return None
