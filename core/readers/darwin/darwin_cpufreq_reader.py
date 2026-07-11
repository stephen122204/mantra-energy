"""
core/readers/darwin/darwin_cpufreq_reader.py

CPU frequency reader for Apple Silicon via IOKitPowerReader.
Implements TurbostatReaderABC minimal contract — same pattern as
ARMCPUFreqReader on GN100. Returns P-cluster HW active frequency
parsed from powermetrics output by the already-running IOKitPowerReader.

PAC-2: instantiated only via ReaderFactory.get_turbostat_reader().
PAC-4: graceful degradation — returns 0 if no sample yet received.
"""
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class DarwinCPUFreqReader:
    """
    Turbostat-equivalent frequency reader for Apple Silicon.
    Delegates to an IOKitPowerReader instance that is already running
    its powermetrics subprocess — no second process started.
    Returns frequency_mean in stop_monitoring() summary so energy_analyzer.py
    picks it up via the same path as TurbostatReader and ARMCPUFreqReader.
    """

    available         = True
    turbostat_version = None
    cpu_topology      = {}
    available_sensors = []
    perf_available    = False

    def __init__(self, iokit_power_reader):
        """
        Args:
            iokit_power_reader: live IOKitPowerReader instance from EnergyEngine.
                                Must already be started before start_monitoring().
        """
        self._reader   = iokit_power_reader
        self._samples  = []   # list of (freq_mhz,) tuples collected during run

    def is_available(self) -> bool:
        return self._reader is not None and self._reader.is_available()

    def get_name(self) -> str:
        return "DarwinCPUFreqReader(powermetrics P-cluster)"

    def start_monitoring(self, interval_ms: int = 100) -> None:
        # powermetrics is already running via IOKitPowerReader — nothing to start.
        # Reset sample buffer for this measurement window.
        self._samples = []
        logger.debug("DarwinCPUFreqReader: start_monitoring — delegating to IOKitPowerReader")

    def stop_monitoring(self) -> Dict:
        """
        Return summary dict matching TurbostatReader contract.
        frequency_mean consumed by energy_analyzer.py line 236.
        """
        freq = self._reader.get_frequency_mhz() if self._reader else 0
        summary = {
            "frequency_mean": float(freq),
            "frequency_min":  float(freq),
            "frequency_max":  float(freq),
        }
        return {
            "dataframe":        None,
            "num_samples":      1 if freq > 0 else 0,
            "duration_seconds": 0.0,
            "summary":          summary,
        }

    def get_latest_sample(self) -> Dict:
        freq = self._reader.get_frequency_mhz() if self._reader else 0
        return {"frequency_mhz": freq} if freq else {}

    def get_column_mapping(self) -> Dict:
        return {"frequency_mhz": "frequency_mean"}

    def read_temperatures(self) -> Dict:
        return {}

    def read_all_thermal(self) -> Dict:
        return {}

    def read_msr(self, msr_addr, cpu=0, pin=True):
        return None

    def read_cstate_counters(self, cpu=0, pin=True):
        return {}

    def snapshot_cstate_counters(self):
        return {}

    def read_context_switches(self):
        return {}

    def read_all(self):
        return {}

    def start_interrupt_sampling(self, pid=0):
        pass
