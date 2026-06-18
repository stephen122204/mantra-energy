"""
ARM PMU performance counter reader for A-LEMS on aarch64.
Uses Linux perf stat with ARM Neoverse V2 PMU events.
Implements CPUReaderABC — drop-in for PerfReader on ARM.

Same subprocess pattern as PerfReader. Generic event names used first
(instructions, cycles) for portability. ARM-specific events used for
cache metrics where generic equivalents unavailable.

Verified platform: NVIDIA Grace (Neoverse V2) on GN100.

cp to: core/readers/arm_pmu_reader.py
"""

import logging
import subprocess
import time
from typing import Dict, Optional

from core.readers.interfaces import CPUReaderABC

logger = logging.getLogger(__name__)

# ARM PMU event names — generic first, ARM-specific for cache hierarchy.
# Generic events (instructions, cycles) work on all ARMv8 PMUv3 platforms
# without needing the armv8_pmuv3/ prefix. Cache events require ARM-specific
# event names because Linux does not alias them as generic cache-misses on ARM.
ARM_PMU_EVENTS = {
    'instructions':     'instructions',
    'cycles':           'cycles',
    'cache_misses':     'armv8_pmuv3/l1d_cache_refill/',
    'cache_references': 'armv8_pmuv3/l1d_cache/',
    'l2_cache_misses':  'armv8_pmuv3/l2d_cache_refill/',
    'l3_cache_hits':    'armv8_pmuv3/l3d_cache/',
    'l3_cache_misses':  'armv8_pmuv3/l3d_cache_refill/',
}

# Must be longer than longest expected experiment window
PERF_TIMEOUT_SECONDS = 300


class ARMPMUReader(CPUReaderABC):
    """
    ARM Neoverse V2 performance counters via Linux perf stat.

    Attaches to process PID during measurement window. Falls back to
    system-wide (-a) if no PID provided. Implements CPUReaderABC for
    factory dispatch on aarch64 — identical interface to PerfReader.

    On GN100: perf works without root via /proc/sys/kernel/perf_event_paranoid
    set to 1 or lower. If paranoid=3, availability check will return False.
    """

    METHOD_PROVENANCE = 'arm_pmu_v1'

    def __init__(self, config):
        # type: (dict) -> None
        self._config = config
        self._pid = None
        self._perf_proc = None
        self._results = {}
        # Check once at construction — avoids repeated subprocess overhead
        self._available = self._check_available()

    def _check_available(self):
        # type: () -> bool
        """
        Verify perf works on this ARM platform.

        Runs a quick perf stat on /bin/true to confirm:
        - perf binary is on PATH
        - ARM PMU events are accessible (perf_event_paranoid allows it)
        - instructions event name is valid on this kernel

        Returns:
            True if perf stat produces output containing 'instructions'.
        """
        try:
            result = subprocess.run(
                ['perf', 'stat', '-e', 'instructions', '--', 'true'],
                capture_output=True,
                text=True,
                timeout=5
            )
            # perf stat output goes to stderr by convention
            return 'instructions' in result.stderr
        except Exception as e:
            logger.warning("ARMPMUReader: perf not available: %s", e)
            return False

    def is_available(self):
        # type: () -> bool
        """Return True if ARM PMU is accessible on this platform."""
        return self._available

    def get_name(self):
        # type: () -> str
        """Human-readable reader name for provenance logging."""
        return 'ARMPMUReader (Neoverse V2 PMUv3)'

    def start_process_measurement(self, pid=None):
        # type: (Optional[int]) -> None
        """
        Start perf stat attached to process PID.

        Mirrors PerfReader.start_process_measurement() interface exactly.
        Uses -x , (CSV mode) so output is machine-parseable regardless of
        terminal width or locale. JSON mode (--json) requires perf 5.13+
        and is not available on all GN100 kernel versions.

        Args:
            pid: Target process ID. None = system-wide (-a) measurement.
        """
        if not self._available:
            logger.debug("ARMPMUReader: skipping start — not available")
            return
        self._pid = pid
        self._results = {}

        # Join all ARM event names into one -e argument — one perf invocation
        # is more efficient than multiple separate perf stat calls
        events = ','.join(ARM_PMU_EVENTS.values())
        cmd = ['perf', 'stat', '-e', events, '-x', ',']

        if pid:
            # PID-attach mode: measure only this process
            cmd += ['-p', str(pid)]
        else:
            # System-wide: -a captures all CPUs when no PID target
            cmd += ['-a', '--', 'sleep', str(PERF_TIMEOUT_SECONDS)]

        try:
            self._perf_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            logger.debug("ARMPMUReader: started perf pid=%s cmd=%s", pid, cmd)
        except Exception as e:
            logger.warning("ARMPMUReader: failed to start perf: %s", e)
            self._perf_proc = None

    def stop_process_measurement(self):
        # type: () -> Dict
        """
        Stop perf stat and parse results.

        Sends SIGTERM to perf, which causes it to print its summary to stderr
        before exiting. communicate() waits for clean exit.

        Returns:
            Dict mapping A-LEMS metric names to integer counts.
            Empty dict if perf was not started or parsing failed.
        """
        if not self._perf_proc:
            return {}
        try:
            self._perf_proc.terminate()
            stdout, stderr = self._perf_proc.communicate(timeout=5)
            self._results = self._parse_perf_output(stderr)
            logger.debug("ARMPMUReader: results=%s", self._results)
        except Exception as e:
            logger.warning("ARMPMUReader: stop failed: %s", e)
            self._results = {}
        finally:
            self._perf_proc = None
        return self._results

    def _parse_perf_output(self, stderr_text):
        # type: (str) -> Dict
        """
        Parse perf stat CSV output (perf stat -x ,).

        CSV format (from perf stat -x ,):
            value,unit,event_name,run_time_ns,pct_running,...

        Handles both 'not supported' and numeric values. ARM cache events
        may return 'not supported' on kernels without PMU driver for that event.

        Args:
            stderr_text: Raw stderr from perf stat process.

        Returns:
            Dict of {alems_metric_name: int_count}.
        """
        results = {}
        for line in stderr_text.splitlines():
            line = line.strip()
            # Skip comments and blank lines
            if not line or line.startswith('#'):
                continue
            parts = line.split(',')
            if len(parts) < 3:
                continue
            try:
                raw_value = parts[0].strip()
                # perf outputs <not supported> or <not counted> for missing events
                if raw_value.startswith('<'):
                    continue
                value = float(raw_value.replace(',', ''))
                event_name = parts[2].strip()
                # Map ARM event string back to A-LEMS metric name
                for alems_name, arm_event in ARM_PMU_EVENTS.items():
                    if arm_event in event_name or event_name in arm_event:
                        results[alems_name] = int(value)
                        break
            except (ValueError, IndexError):
                # Non-numeric lines (headers, warnings) — skip silently
                continue
        return results

    # --- CPUReaderABC required methods ---

    def read_instructions(self):
        # type: () -> int
        """Return retired instruction count from ARM PMU."""
        return self._results.get('instructions', 0)

    def read_cycles(self):
        # type: () -> int
        """Return CPU cycle count from ARM PMU."""
        return self._results.get('cycles', 0)

    def read_ipc(self):
        # type: () -> float
        """
        Compute IPC (instructions per cycle) from PMU counters.

        Returns 0.0 if cycles == 0 to avoid division by zero.
        IPC > 4.0 on Neoverse V2 is theoretically possible (wide OOO core).
        """
        instr = self.read_instructions()
        cycles = self.read_cycles()
        if cycles > 0:
            return round(instr / cycles, 4)
        return 0.0

    def read_frequency_mhz(self):
        # type: () -> float
        """
        Frequency measurement delegated to ARMCPUFreqReader.

        ARMPMUReader does not read frequency — cpufreq sysfs is the
        ARM equivalent of turbostat and is handled separately per factory
        dispatch. Returning 0.0 here ensures no accidental use of this path.
        """
        return 0.0

    def read_cache_misses(self):
        # type: () -> int
        """Return L1D cache refill count (ARM equiv of cache-misses)."""
        return self._results.get('cache_misses', 0)

    def read_cache_references(self):
        # type: () -> int
        """Return L1D cache access count (ARM equiv of cache-references)."""
        return self._results.get('cache_references', 0)

    def get_l1d_cache_misses(self):
        # type: () -> int
        """Return L1D cache refill count — same as read_cache_misses()."""
        return self._results.get('cache_misses', 0)

    def get_l2_cache_misses(self):
        # type: () -> int
        """Return L2D cache refill count from ARM PMU."""
        return self._results.get('l2_cache_misses', 0)

    def get_l3_cache_hits(self):
        # type: () -> int
        """Return L3D cache hit count from ARM PMU."""
        return self._results.get('l3_cache_hits', 0)

    def get_l3_cache_misses(self):
        # type: () -> int
        """Return L3D cache refill count from ARM PMU."""
        return self._results.get('l3_cache_misses', 0)
