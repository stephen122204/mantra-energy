"""
core/readers/nic_collector.py
NIC byte counter collector — samples at 100Hz during each run.

SPEC_03A: Mirrors EnergyCollector pattern exactly.
Starts in energy_engine.start_measurement(), stops in stop_measurement().
Writes nic_samples rows via _flushed_nic_samples buffer.

PAC-2: Platform-conditional import of LinuxNICSysfsReader only here.
PAC-4: Never raises — degrades gracefully on unsupported platforms.
DC-1:  30% inline comment coverage.
"""

import logging
import platform
import threading
import time
from typing import List, Optional

logger = logging.getLogger(__name__)

# Sampling cadence — matches EnergyCollector 100Hz target
_HZ = 100
_INTERVAL_S = 1.0 / _HZ


class NICCollector:
    """
    Collects NIC byte/packet counter samples at 100Hz during a run.

    Follows EnergyCollector start/stop lifecycle pattern exactly.
    Samples are buffered in _flushed_nic_samples for insertion after
    insert_run() in experiment_runner.py — same pattern as v2 energy samples.

    On unsupported platforms (macOS, Windows, no sysfs) is_available()
    returns False and start() is a no-op — never raises.
    """

    def __init__(self, run_id: int):
        self._run_id = run_id
        self._thread: Optional[threading.Thread] = None
        self._running = False
        # Buffer for collected samples — flushed on stop()
        self._flushed_nic_samples: List[dict] = []
        # Lazy-init reader — PAC-2: conditional import only here
        self._reader = self._make_reader()

    def is_available(self) -> bool:
        """True if NIC reader available on this platform."""
        return self._reader is not None and self._reader.is_available()

    def start(self) -> None:
        """
        Start NIC sampling thread. No-op if not available (PAC-4).
        Mirrors EnergyCollector.start() pattern.
        """
        if not self.is_available():
            logger.debug("NICCollector: not available on this platform — no-op")
            return

        self._running = True
        self._flushed_nic_samples = []
        self._thread = threading.Thread(
            target=self._loop,
            name=f"NICCollector-{self._run_id}",
            daemon=True,   # daemon — does not block process exit
        )
        self._thread.start()
        logger.info("NICCollector started: run_id=%d hz=%d", self._run_id, _HZ)

    def stop(self) -> None:
        """
        Stop NIC sampling thread and flush collected samples.
        Mirrors EnergyCollector.stop() pattern.
        """
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info(
            "NICCollector stopped: run_id=%d samples=%d",
            self._run_id, len(self._flushed_nic_samples),
        )

    # ── Private ──────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        """
        Sampling loop — reads NIC counters at _HZ and buffers samples.
        Same structure as EnergyCollector._loop().
        """
        _prev_ns = None
        while self._running:
            t0 = time.monotonic()

            try:
                sample = self._reader.read_sample()
                if sample is not None:
                    # Add run_id and interval timestamps for phase join.
                    # sample_start_ns/sample_end_ns enable interval overlap
                    # joins identical to gpu_samples and interrupt_samples.
                    now_ns = time.time_ns()
                    sample["run_id"]          = self._run_id
                    sample["sample_ns"]       = now_ns
                    sample["sample_start_ns"] = _prev_ns if _prev_ns is not None else now_ns
                    sample["sample_end_ns"]   = now_ns
                    _prev_ns = now_ns
                    self._flushed_nic_samples.append(sample)
            except Exception as exc:
                # Never crash the loop — log and continue (PAC-4)
                logger.debug("NICCollector._loop error: %s", exc)

            # Sleep remainder of interval to maintain cadence
            elapsed = time.monotonic() - t0
            sleep_s = max(0.0, _INTERVAL_S - elapsed)
            time.sleep(sleep_s)

    def _make_reader(self):
        """
        PAC-2: Only place that imports platform-specific NIC reader.
        Returns None on unsupported platforms — never raises.
        """
        try:
            if platform.system() == "Linux":
                from core.readers.linux.nic_sysfs_reader import LinuxNICSysfsReader
                return LinuxNICSysfsReader({})
            # macOS: deferred to future darwin/nic_netstat_reader.py
            # Windows: no sysfs, no collector
            logger.debug("NICCollector: platform %s not supported", platform.system())
            return None
        except Exception as exc:
            logger.debug("NICCollector: reader init failed: %s", exc)
            return None
