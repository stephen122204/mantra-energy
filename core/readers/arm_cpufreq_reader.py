"""
ARM CPU frequency reader via cpufreq sysfs for GN100.
Implements TurbostatReaderABC — drop-in for TurbostatReader on ARM.

Populates: frequency_mhz, cpu_avg_mhz, cpu_busy_mhz
Does NOT populate: c2/c3/c6/c7 (ARM c-states differ from x86)
Does NOT populate: ring_bus_freq_mhz, voltage_vcore (not available on Grace)

Source: /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq
        Returns current frequency in kHz → convert to MHz.

cp to: core/readers/arm_cpufreq_reader.py
"""

import glob
import logging
import queue
import threading
import time
from typing import Dict, List, Optional

from core.readers.interfaces import TurbostatReaderABC

logger = logging.getLogger(__name__)

# Match turbostat's default 10 Hz sampling rate for consistency with x86 runs
CPUFREQ_SAMPLING_HZ = 10


class ARMCPUFreqReader(TurbostatReaderABC):
    """
    CPU frequency reader for ARM via cpufreq sysfs.

    A background sampling thread reads all CPU scaling_cur_freq files at
    CPUFREQ_SAMPLING_HZ. Returns average frequency across all online CPUs.

    On NVIDIA Grace (Neoverse V2):
    - 72 CPUs total (not confirmed per session — discover dynamically)
    - P-cores (X925) and E-cores (A725) have separate frequency governors
    - Both are averaged together into a single Avg_MHz value
    - No x86-equivalent C-states — c2/c3/c6/c7 return None (MIC-1 correct)

    Interface mirrors TurbostatReader.start_monitoring() / stop_monitoring()
    for transparent factory substitution on ARM.
    """

    def __init__(self, config):
        # type: (dict) -> None
        self._config = config
        # Discover all online CPUs with readable cpufreq at construction time.
        # If cpufreq sysfs is not mounted, _cpu_paths will be empty and
        # start_monitoring() will log a warning and return without crashing.
        self._cpu_paths = self._discover_cpu_paths()
        self._running = False
        self._thread = None
        # Queue bounded at 2000 entries — at 10 Hz over 200 seconds, enough
        # for longest expected experiment; put_nowait() silently drops if full
        self._queue = queue.Queue(maxsize=2000)
        logger.info("ARMCPUFreqReader: found %d CPU frequency paths",
                    len(self._cpu_paths))

    def _discover_cpu_paths(self):
        # type: () -> List[str]
        """
        Find all online CPUs with a readable cpufreq scaling_cur_freq file.

        Uses glob to enumerate cpu* entries rather than /sys/bus/cpu because
        glob is simpler and works on all Linux kernel versions we target.

        Returns:
            Sorted list of sysfs paths to scaling_cur_freq files.
        """
        paths = []
        pattern = '/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq'
        for path in sorted(glob.glob(pattern)):
            if self._is_readable(path):
                paths.append(path)
        return paths

    def _is_readable(self, path):
        # type: (str) -> bool
        """
        Return True if the path exists and can be read without error.

        Offline CPUs may have the cpufreq directory but return ENODEV on read.
        This check excludes those silently.
        """
        try:
            open(path).read()
            return True
        except Exception:
            return False

    def _read_freq_mhz(self, path):
        # type: (str) -> Optional[float]
        """
        Read one CPU's current frequency in MHz.

        sysfs scaling_cur_freq returns kHz as a plain integer. Divide by
        1000 to convert to MHz. Returns None on any read failure so the
        caller can skip this CPU without crashing the sampling loop.

        Args:
            path: Absolute path to scaling_cur_freq file.

        Returns:
            Frequency in MHz, or None on failure.
        """
        try:
            khz = int(open(path).read().strip())
            return khz / 1000.0
        except Exception:
            return None

    def _read_all_freqs(self):
        # type: () -> List[float]
        """
        Read all CPU frequencies in MHz in a single pass.

        Skips CPUs that return None (hotplug, offline, or transient error).
        Returns an empty list if all reads fail — caller handles gracefully.
        """
        freqs = []
        for path in self._cpu_paths:
            f = self._read_freq_mhz(path)
            if f is not None:
                freqs.append(f)
        return freqs

    def is_available(self):
        # type: () -> bool
        """Return True if at least one cpufreq path was discovered."""
        return len(self._cpu_paths) > 0

    def get_name(self):
        # type: () -> str
        """Human-readable reader name for provenance logging."""
        return 'ARMCPUFreqReader (cpufreq sysfs)'

    def start_monitoring(self, interval_ms=100):
        # type: (int) -> None
        """
        Start background frequency sampling thread.

        Mirrors TurbostatReader.start_monitoring() interface for transparent
        factory substitution. interval_ms ignored — uses CPUFREQ_SAMPLING_HZ
        constant to match turbostat default rate.

        Args:
            interval_ms: Ignored on ARM. Present for interface compatibility.
        """
        if not self._cpu_paths:
            logger.warning("ARMCPUFreqReader: no cpufreq paths found — "
                           "frequency_mhz will be NULL")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._sampling_loop,
            daemon=True,
            name='arm-cpufreq-sampler'
        )
        self._thread.start()
        logger.debug("ARMCPUFreqReader: monitoring started, %d CPUs",
                     len(self._cpu_paths))

    def stop_monitoring(self):
        # type: () -> dict
        """
        Stop monitoring and return aggregated frequency data.

        Drains the sample queue and computes a time-averaged frequency across
        all CPUs and all sample points. This matches turbostat's Avg_MHz
        semantics: mean frequency over the measurement window.

        Returns:
            Dict with keys matching TurbostatReader output:
                Avg_MHz:      float, mean frequency across all CPUs and time
                Bzy_MHz:      float, same as Avg_MHz (busy% not available on ARM)
                package_temp: None (use ARMThermalReader instead)
                C1%..C7%:     None (ARM WFI/WFE states not mapped to x86 c-states)
            Empty dict if no samples were collected.
        """
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

        # Drain queue — collect all frequency snapshots taken during window
        samples = []
        while not self._queue.empty():
            try:
                samples.append(self._queue.get_nowait())
            except queue.Empty:
                break

        if not samples:
            logger.warning("ARMCPUFreqReader: no frequency samples collected")
            return {}

        # Flatten all per-CPU per-sample frequencies and compute grand mean.
        # This is equivalent to turbostat Avg_MHz averaged across all cores
        # and all time intervals in the measurement window.
        all_freqs = [f for snapshot in samples for f in snapshot]
        avg_mhz = sum(all_freqs) / len(all_freqs) if all_freqs else 0.0

        logger.debug("ARMCPUFreqReader: %d snapshots, %.1f avg MHz",
                     len(samples), avg_mhz)

        summary = {
            'frequency_mean': avg_mhz,
            'frequency_max':  max(all_freqs) if all_freqs else avg_mhz,
            'frequency_min':  min(all_freqs) if all_freqs else avg_mhz,
        }
        return {
            'Avg_MHz':          avg_mhz,
            'Bzy_MHz':          avg_mhz,
            'package_temp':     None,
            'C1%': None, 'C2%': None, 'C3%': None,
            'C6%': None, 'C7%': None,
            'dataframe':        None,
            'num_samples':      len(samples),
            'duration_seconds': len(samples) / CPUFREQ_SAMPLING_HZ,
            'summary':          summary,
        }

    def get_column_mapping(self):
        # type: () -> dict
        """
        Return mapping of ARM cpufreq metric names to runs table columns.
        ARM does not produce turbostat columns — returns empty dict for
        columns that are NULL on aarch64 (ring_bus, voltage, c-states).
        """
        return {
            'frequency_mean': 'frequency_mhz',
            'frequency_max':  'cpu_avg_mhz',
        }
    
    def _sampling_loop(self):
        """
        Background thread: reads all CPU frequencies at CPUFREQ_SAMPLING_HZ.

        Uses a drift-free timer (next_sample advance) so accumulated scheduling
        jitter does not cause sample rate to drift over long measurements.
        Exits cleanly when _running is set to False by stop_monitoring().
        """
        interval = 1.0 / CPUFREQ_SAMPLING_HZ
        next_sample = time.time()

        while self._running:
            try:
                freqs = self._read_all_freqs()
                if freqs:
                    # put_nowait silently drops if queue is full (bounded queue)
                    self._queue.put_nowait(freqs)
            except queue.Full:
                # Queue full means experiment ran longer than expected — not fatal
                pass
            except Exception as e:
                logger.debug("ARMCPUFreqReader sample error: %s", e)

            # Advance next_sample by fixed interval to avoid drift
            next_sample += interval
            sleep_time = next_sample - time.time()
            if sleep_time > 0:
                time.sleep(sleep_time)
