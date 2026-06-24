"""
SPBM Energy Reader for A-LEMS on GN100 (NVIDIA Grace + Blackwell).
Reads energy accumulators from spark_hwmon sysfs interface.

spark_hwmon driver: github.com/antheas/spark_hwmon
Device: NVDA8800:00 on GN100 (Acer Veriton GN100, kernel 6.17.0-1021-nvidia)

Energy accumulators (µJ, monotonically incrementing):
    pkg:   full SoC package (CPU + GPU + memory + NVLink)
    cpu_p: Performance core cluster (Cortex-X925)
    cpu_e: Efficiency core cluster (Cortex-A725)
    gpu:   GPU rail (includes GPU memory + NVLink-C2C)

Column mapping to A-LEMS runs table:
    pkg   → pkg_energy_uj    (full package, analogous to RAPL pkg)
    cpu_p → core_energy_uj   (P-cores, analogous to RAPL core)
    cpu_e → stored in energy_sample_domains only (no runs column equivalent)
    gpu   → NOT used for gpu_total_energy_uj (DCGM field 156 used instead)

PAC-2 compliant: SPBMEnergyReader is the only class that reads sysfs hwmon.
Never call sysfs paths directly outside this class.

cp to: core/readers/spbm_energy_reader.py
"""

import glob
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from core.readers.interfaces import EnergyReaderABC

logger = logging.getLogger(__name__)

# Sampling rate matches gpu_samples rate for alignment
SPBM_SAMPLING_HZ = 10

# Channel names as they appear in spark_hwmon label files
SPBM_ENERGY_CHANNELS = ['pkg', 'cpu_p', 'cpu_e', 'gpu']
SPBM_POWER_CHANNELS  = ['sys_total', 'cpu_p', 'cpu_e', 'gpu']
# SPEC_SPBM_FULL_TELEMETRY: 6 additional power-only channels (no hardware
# cumulative energy counter — must be integrated from instantaneous power).
# pl1/pl2/syspl1/syspl2 excluded — firmware limits, not telemetry.
SPBM_POWER_TELEMETRY_CHANNELS = ['soc_pkg', 'cpu_gpu', 'vcore', 'dc_input', 'prereg', 'dla']


class SPBMEnergyReader(EnergyReaderABC):
    """
    Reads SPBM spark_hwmon energy accumulators on GN100.
    Implements EnergyReaderABC — drop-in replacement for RAPLReader on ARM.

    Accumulators are monotonically incrementing µJ counters.
    Delta = end - start gives energy for the measurement window.
    64-bit counters: overflow not a concern at observed rates
    (~17 W pkg = ~17 mJ/s, would overflow in ~34 years).
    """

    METHOD_ID         = 'spbm_pkg_v1'
    METHOD_PROVENANCE = 'spbm_pkg_v1'

    def __init__(self, config, hwmon_path=None):
        # type: (dict, Optional[str]) -> None
        """
        Args:
            config:      hw_config dict (passed through from factory)
            hwmon_path:  hwmon path injected from PlatformCapabilities.
                         If None, auto-discovers — caps injection preferred
                         so path is never re-scanned at runtime.
        """
        self._config       = config
        self._hwmon_path   = hwmon_path or self._discover_hwmon_path()
        self._energy_paths = {}   # channel_name → sysfs path
        self._power_paths  = {}
        # EnergyReaderABC compat flag — no MSR/PP1 on ARM
        self.gpu_pp1_available = False

        if self._hwmon_path:
            self._energy_paths = self._discover_energy_paths()
            self._power_paths  = self._discover_power_paths()
            logger.info(
                "SPBMEnergyReader: hwmon=%s energy_channels=%s",
                self._hwmon_path, list(self._energy_paths.keys())
            )
        else:
            logger.warning(
                "SPBMEnergyReader: spark_hwmon not found — "
                "all reads return NULL (expected on non-GN100 systems)"
            )

    def _discover_hwmon_path(self):
        # type: () -> Optional[str]
        """
        Find spark_hwmon device under /sys/class/hwmon/.
        Identifies by name file containing 'spbm' or 'spark'.
        hwmon device number varies across reboots — never hardcode.
        """
        for hwmon_dir in sorted(glob.glob('/sys/class/hwmon/hwmon*/')):
            try:
                name = open(hwmon_dir + 'name').read().strip()
                if 'spbm' in name.lower() or 'spark' in name.lower():
                    logger.info(
                        "SPBMEnergyReader: discovered hwmon at %s (name=%s)",
                        hwmon_dir, name
                    )
                    return hwmon_dir
            except Exception:
                continue
        logger.warning("SPBMEnergyReader: no spark_hwmon found in /sys/class/hwmon/")
        return None

    def _discover_energy_paths(self):
        # type: () -> Dict[str, str]
        """
        Map channel names to sysfs energy input paths.
        Uses label files: energy1_label='pkg' → energy1_input is pkg path.
        """
        paths = {}
        for label_file in sorted(glob.glob(self._hwmon_path + 'energy*_label')):
            try:
                label      = open(label_file).read().strip()
                input_file = label_file.replace('_label', '_input')
                if os.path.exists(input_file):
                    paths[label] = input_file
                    logger.debug("SPBM energy channel: %s → %s", label, input_file)
            except Exception as e:
                logger.debug("SPBM label read failed %s: %s", label_file, e)
        return paths

    def _discover_power_paths(self):
        # type: () -> Dict[str, str]
        """Map power channel names to sysfs power input paths."""
        paths = {}
        for label_file in sorted(glob.glob(self._hwmon_path + 'power*_label')):
            try:
                label      = open(label_file).read().strip()
                input_file = label_file.replace('_label', '_input')
                if os.path.exists(input_file):
                    paths[label] = input_file
            except Exception:
                continue
        return paths

    def _read_uj(self, channel):
        # type: (str) -> Optional[int]
        """
        Read one energy accumulator in µJ.
        Returns None on failure — never raises (MIC-1 compliant).
        """
        path = self._energy_paths.get(channel)
        if not path:
            return None
        try:
            return int(open(path).read().strip())
        except Exception as e:
            logger.warning("SPBM energy read failed channel=%s: %s", channel, e)
            return None

    def _read_mw(self, channel):
        # type: (str) -> Optional[int]
        """
        Read one power channel in mW.
        hwmon power files are in µW — divide by 1000 for mW.
        Returns None on failure.
        """
        path = self._power_paths.get(channel)
        if not path:
            return None
        try:
            uw = int(open(path).read().strip())
            return uw // 1000
        except Exception as e:
            logger.debug("SPBM power read failed channel=%s: %s", channel, e)
            return None

    def read_energy(self):
        # type: () -> Dict[str, Optional[int]]
        """
        Read SPBM energy accumulators (µJ, cumulative) and power channels
        (mW, instantaneous). EnergyCollector reads all domains from this
        single method — ENERGY_COUNTER domains are delta'd, POWER_RAIL
        domains are stored as-is per EnergyCollector._loop() branch logic.
        SPEC_SPBM_FULL_TELEMETRY: 6 power channels added alongside the
        4 existing cumulative counters.
        """
        return {
            # Cumulative energy counters (µJ)
            'pkg':      self._read_uj('pkg'),
            'cpu_p':    self._read_uj('cpu_p'),
            'cpu_e':    self._read_uj('cpu_e'),
            'gpu':      self._read_uj('gpu'),
            # Instantaneous power channels (mW) — POWER_RAIL type in schema
            'soc_pkg':  self._read_mw('soc_pkg'),
            'cpu_gpu':  self._read_mw('cpu_gpu'),
            'vcore':    self._read_mw('vcore'),
            'dc_input': self._read_mw('dc_input'),
            'prereg':   self._read_mw('prereg'),
            'dla':      self._read_mw('dla'),
        }

    def get_measurement_schema(self):
        """Return SPBM ARM schema — 64-bit counters at 10 Hz, GN100 domains."""
        from core.readers.measurement_schema import SCHEMA_SPBM_ARM
        return SCHEMA_SPBM_ARM
    
    def read_energy_uj(self):
        # type: () -> Dict[str, Optional[int]]
        """
        EnergyReaderABC interface — maps SPBM channels to A-LEMS column keys.
        pkg   → 'package-0' → pkg_energy_uj in runs
        cpu_p → 'core'      → core_energy_uj in runs (P-cores only)
        cpu_e → None        → no runs column, stored in energy_sample_domains only
        gpu   → not mapped  → DCGM field 156 used for gpu_total_energy_uj
        """
        return {
            'package-0': self._read_uj('pkg'),    # maps to pkg_energy_uj
            'core':      self._read_uj('cpu_p'),  # maps to core_energy_uj
            'uncore':    None,                     # no equivalent on ARM Grace
            'dram':      None,                     # no RAPL DRAM domain on Grace
        }

    def read_energy_safe(self):
        # type: () -> Dict[str, Optional[int]]
        """
        Safe read for sampling loop — never raises (DC-3 compliant).
        Returns None values per channel on any failure.
        """
        try:
            return self.read_energy()
        except Exception as e:
            logger.warning("SPBMEnergyReader.read_energy_safe: %s", e)
            return {ch: None for ch in SPBM_ENERGY_CHANNELS}

    def read_power(self):
        # type: () -> Dict[str, Optional[int]]
        """
        Read instantaneous power channels in mW.
        Extended (SPEC_SPBM_FULL_TELEMETRY): 6 new channels added.
        _read_mw() resolves channel name via self._power_paths, built
        dynamically by _discover_power_paths() from hwmon power*_label
        files — all 14 channels auto-discovered, no hardcoding needed.
        dc_input: physical measurement point not yet vendor-verified —
        referred to only as "SPBM rail labeled dc_input" until confirmed
        (SPEC_SPBM_FULL_TELEMETRY Section 7b).
        """
        return {
            'sys_total': self._read_mw('sys_total'),
            'cpu_p':     self._read_mw('cpu_p'),
            'cpu_e':     self._read_mw('cpu_e'),
            'gpu':       self._read_mw('gpu'),
            'soc_pkg':   self._read_mw('soc_pkg'),
            'cpu_gpu':   self._read_mw('cpu_gpu'),
            'vcore':     self._read_mw('vcore'),
            'dc_input':  self._read_mw('dc_input'),
            'prereg':    self._read_mw('prereg'),
            'dla':       self._read_mw('dla'),
        }

    def read_power_limits(self):
        # type: () -> Dict[str, Optional[int]]
        """
        Read firmware power limit values (mW). Configuration/caps —
        NOT consumption telemetry. Call once per run, not in the
        continuous sampling loop (SPEC_SPBM_FULL_TELEMETRY Section 3/6b).
        """
        return {
            'pl1':    self._read_mw('pl1'),
            'pl2':    self._read_mw('pl2'),
            'syspl1': self._read_mw('syspl1'),
            'syspl2': self._read_mw('syspl2'),
        }
    
    def read_gpu_msr(self):
        # type: () -> None
        """No MSR on ARM Grace — returns None. EnergyReaderABC compat."""
        return None

    def get_domains(self):
        # type: () -> List[str]
        """EnergyReaderABC: return A-LEMS domain keys (not raw channel names)."""
        return ['package-0', 'core']

    def get_available_domains(self):
        # type: () -> List[str]
        """Return list of available raw SPBM channel names."""
        return list(self._energy_paths.keys())

    def is_available(self):
        # type: () -> bool
        """True if hwmon path found and pkg channel readable."""
        return bool(self._hwmon_path and 'pkg' in self._energy_paths)

    def get_name(self):
        # type: () -> str
        """Reader name for logging and provenance."""
        return 'SPBMEnergyReader'


# =============================================================================
# SPBMSample dataclass
# =============================================================================

@dataclass
class SPBMSample:
    """
    One SPBM energy sample at 10 Hz. Mirrors GpuSample pattern.
    Stores both raw start/end accumulator values and computed deltas
    so conservation checks can be run against energy_sample_domains table.
    """
    sample_start_ns: int
    sample_end_ns:   int
    interval_ns:     int
    pkg_start_uj:    Optional[int]
    pkg_end_uj:      Optional[int]
    pkg_energy_uj:   Optional[int]
    cpu_p_start_uj:  Optional[int]
    cpu_p_end_uj:    Optional[int]
    cpu_p_energy_uj: Optional[int]
    cpu_e_start_uj:  Optional[int]
    cpu_e_end_uj:    Optional[int]
    cpu_e_energy_uj: Optional[int]
    gpu_start_uj:    Optional[int]
    gpu_end_uj:      Optional[int]
    gpu_energy_uj:   Optional[int]
    sys_total_mw:    Optional[int]
    cpu_p_mw:        Optional[int]
    cpu_e_mw:        Optional[int]
    gpu_mw:          Optional[int]

    def to_dict(self):
        # type: () -> dict
        """Serialise to plain dict for JSON logging."""
        return self.__dict__.copy()


# =============================================================================
# SPBMSampler — background 10 Hz sampler
# =============================================================================

class SPBMSampler:
    """
    Background sampler for SPBM at 10 Hz.
    Mirrors GPUCollector pattern exactly for consistency with existing wiring.
    Lifecycle: start() before measurement, stop() returns List[EnergySampleV2].
    Thread-safe via daemon thread + bounded queue.
    """

    def __init__(self, reader, sampling_hz=SPBM_SAMPLING_HZ):
        # type: (SPBMEnergyReader, int) -> None
        self._reader       = reader
        self._hz           = sampling_hz
        self._interval     = 1.0 / sampling_hz
        # Bounded queue — if consumer (stop) is slow, oldest samples dropped
        self._queue        = queue.Queue(maxsize=2000)
        self._thread       = None   # type: Optional[threading.Thread]
        self._running      = False
        self._prev         = None   # previous channel readings for delta
        self._prev_ts_ns   = None   # type: Optional[int]
        self.samples_taken   = 0
        self.samples_dropped = 0

    def start(self):
        # type: () -> None
        """Start background sampling. No-op if reader unavailable."""
        if not self._reader.is_available():
            logger.debug("SPBMSampler: reader unavailable, not starting")
            return
        self._running      = True
        self._prev         = None
        self._prev_ts_ns   = None
        self.samples_taken   = 0
        self.samples_dropped = 0
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name='spbm-sampler'
        )
        self._thread.start()
        logger.debug("SPBMSampler: started at %d Hz", self._hz)

    def stop(self):
        # type: () -> list
        """Stop sampling and return all collected EnergySampleV2 objects."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        samples = []
        while not self._queue.empty():
            try:
                samples.append(self._queue.get_nowait())
            except queue.Empty:
                break
        logger.info(
            "SPBMSampler: stopped — %d samples collected, %d dropped",
            self.samples_taken, self.samples_dropped
        )
        return samples

    def _loop(self):
        # type: () -> None
        """Background sampling loop. Runs in daemon thread."""
        next_sample = time.time()
        while self._running:
            try:
                ts_ns    = time.time_ns()
                readings = self._reader.read_energy()
                power    = self._reader.read_power()

                if self._prev is not None and self._prev_ts_ns is not None:
                    interval_ns = ts_ns - self._prev_ts_ns
 
                    def _delta(ch):
                        # type: (str) -> Optional[int]
                        cur = readings.get(ch)
                        prv = self._prev.get(ch)
                        if cur is None or prv is None:
                            return None
                        d = cur - prv
                        # Negative delta means counter reset — skip sample
                        return d if d >= 0 else None
 
                    # Produce EnergySampleV2 for unified schema insert path.
                    # Domain IDs match energy_domains seed data exactly.
                    # Only non-None deltas inserted — absent domains not stored.
                    from core.readers.energy_sample_v2 import (
                        EnergySampleV2,
                        DOMAIN_PACKAGE, DOMAIN_CPU_P, DOMAIN_CPU_E, DOMAIN_GPU,
                        DOMAIN_SOC_PKG, DOMAIN_CPU_GPU, DOMAIN_VCORE,
                        DOMAIN_DC_INPUT, DOMAIN_PREREG, DOMAIN_DLA,
                        SOURCE_SPBM,
                    )
                    domains = {}
                    if _delta('pkg')   is not None: domains[DOMAIN_PACKAGE] = _delta('pkg')
                    if _delta('cpu_p') is not None: domains[DOMAIN_CPU_P]   = _delta('cpu_p')
                    if _delta('cpu_e') is not None: domains[DOMAIN_CPU_E]   = _delta('cpu_e')
                    if _delta('gpu')   is not None: domains[DOMAIN_GPU]     = _delta('gpu')
 
                    # SPEC_SPBM_FULL_TELEMETRY: integrate power-only channels.
                    # Rectangular integration: power_mw * interval_s * 1000 = uJ.
                    # No coverage counters here — SPBMSampler is retired (16B3);
                    # coverage is tracked from last_v2_samples in stop_measurement().
                    interval_s = interval_ns / 1_000_000_000
                    def _tick_uj(ch):
                        p = power.get(ch)
                        if p is None:
                            return None
                        # Clamp negative — SPBM noise on short runs, not real negative energy (MIC-3)
                        return max(0, int(p * interval_s * 1000))
 
                    if _tick_uj('soc_pkg')  is not None: domains[DOMAIN_SOC_PKG]  = _tick_uj('soc_pkg')
                    if _tick_uj('cpu_gpu')  is not None: domains[DOMAIN_CPU_GPU]  = _tick_uj('cpu_gpu')
                    if _tick_uj('vcore')    is not None: domains[DOMAIN_VCORE]    = _tick_uj('vcore')
                    if _tick_uj('dc_input') is not None: domains[DOMAIN_DC_INPUT] = _tick_uj('dc_input')
                    if _tick_uj('prereg')   is not None: domains[DOMAIN_PREREG]   = _tick_uj('prereg')
                    if _tick_uj('dla')      is not None: domains[DOMAIN_DLA]      = _tick_uj('dla')
 
                    sample = EnergySampleV2(
                        timestamp_ns = self._prev_ts_ns,
                        interval_ns  = interval_ns,
                        source_id    = SOURCE_SPBM,
                        domains      = domains,
                    )
                    try:
                        self._queue.put_nowait(sample)
                        self.samples_taken += 1
                    except queue.Full:
                        # Drop oldest to make room — bounded queue prevents memory growth
                        try:
                            self._queue.get_nowait()
                            self._queue.put_nowait(sample)
                            self.samples_dropped += 1
                        except queue.Empty:
                            pass

                self._prev       = readings
                self._prev_ts_ns = ts_ns

            except Exception as e:
                logger.warning("SPBMSampler._loop error: %s", e)

            next_sample += self._interval
            sleep_time   = next_sample - time.time()
            if sleep_time > 0:
                time.sleep(sleep_time)
