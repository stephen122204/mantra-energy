#!/usr/bin/env python3
"""
================================================================================
IOKIT POWER READER — macOS Power Measurement via IOKit/powermetrics
================================================================================

Apple Silicon CPU/GPU power reader via powermetrics.
Implements EnergyReaderABC for Darwin, any architecture with powermetrics
cpu_power/gpu_power/ane_power samplers.

Mode: MEASURED (real hardware power sensor, power-integrated to energy)
Domains: cpu, gpu (per SCHEMA_APPLE_IOKIT, matches Apple's unified memory
architecture, no separate package or DRAM rail exists to measure)

Energy calculation: powermetrics reports instantaneous power (mW) at a
fixed sampling interval. Energy is the trapezoidal integral of power over
time: for each new sample, energy_uj += power_mw * dt_s * 1000, where
dt_s is the elapsed time since the previous sample (capped to avoid
outliers from any single delayed sample).

read_energy_uj() is a counter-style call, matches RAPLReader's contract.
Callers compute deltas between two calls. Never call stop() or reset(),
sampling runs continuously for the life of the process.

Confirmed real data (session 2026-07-01, macOS 26.3.1, Apple M1 Pro):
  CPU Power: 205 mW
  GPU Power: 112 mW  (from CPU Power Stats block, used here)
  ANE Power: 0 mW    (parsed, not currently written to any column)
  Combined Power (CPU + GPU + ANE): 317 mW  (not used, no domain fits it)
  No Package Power line. No DRAM Power line. No numeric temperature.

Author: Deepak Panigrahy
================================================================================
"""

import logging
import re
import subprocess
import threading
import time
from typing import Dict, List, Optional

from core.readers.interfaces import EnergyReaderABC
from core.models.normalized_energy_reading import NormalizedEnergyReading

logger = logging.getLogger(__name__)

POWERMETRICS_INTERVAL_MS = 500
POWERMETRICS_SAMPLERS = "cpu_power,gpu_power,ane_power"


class IOKitPowerReader(EnergyReaderABC):
    """
    Apple Silicon power reader via powermetrics, continuous background
    sampling with trapezoidal power integration to cumulative energy.
    """

    METHOD_ID          = "iokit_power_reader"
    METHOD_NAME        = "IOKit Power Reader (macOS, powermetrics)"
    METHOD_LAYER       = "silicon"
    METHOD_CONFIDENCE  = 0.85   # cpu domain; gpu domain is 0.80, see SPEC_16F2
    METHOD_PROVENANCE  = "MEASURED"
    METHOD_PARAMS      = {
        "source": "powermetrics cpu_power,gpu_power,ane_power",
        "conversion": "trapezoidal_power_integration",
        "sampling_interval_ms": POWERMETRICS_INTERVAL_MS,
    }
    FALLBACK_METHOD_ID = "ml_energy_estimator"
    DOMAINS = ["cpu", "gpu"]   # matches SCHEMA_APPLE_IOKIT native_keys exactly

    def __init__(self, config: dict = None):
        self._config = config or {}
        self._lock = threading.Lock()
        self._samples: List[Dict] = []
        self._cumulative_uj = {d: 0 for d in self.DOMAINS}
        self._latest_freq_mhz = 0  # latest P-cluster frequency from powermetrics
        self._proc = None
        self._reader_thread = None
        self._available = self._check_available()
        if self._available:
            self._start_sampling()
        else:
            logger.warning(
                "IOKitPowerReader: powermetrics unavailable or sudo "
                "required, energy will remain zero. Check sudo access."
            )

    def _check_available(self) -> bool:
        try:
            result = subprocess.run(
                ["sudo", "powermetrics", "--samplers", "cpu_power",
                 "-n", "1", "-i", "100"],
                capture_output=True, timeout=5,
            )
            return result.returncode == 0
        except Exception as e:
            logger.warning("IOKitPowerReader: availability check failed: %s", e)
            return False

    def _start_sampling(self):
        cmd = [
            "sudo", "powermetrics",
            "--samplers", POWERMETRICS_SAMPLERS,
            "-i", str(POWERMETRICS_INTERVAL_MS),
            "-n", "-1",   # -1 means infinite per powermetrics --help,
                          # 0 means zero samples and exit immediately
            "--format", "text",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            self._reader_thread = threading.Thread(
                target=self._read_loop, daemon=True, name="iokit-power-reader",
            )
            self._reader_thread.start()
        except Exception as e:
            logger.warning("IOKitPowerReader: failed to start sampling: %s", e)
            self._proc = None

    def _read_loop(self):
        if not self._proc:
            return
        buffer = []
        last_timestamp = None
        for line in self._proc.stdout:
            line = line.strip()
            if line.startswith("*** Sampled"):
                if buffer:
                    self._process_sample(buffer, last_timestamp)
                    last_timestamp = time.time()
                buffer = [line]
                if last_timestamp is None:
                    last_timestamp = time.time()
            else:
                buffer.append(line)

    def _process_sample(self, lines: List[str], prev_timestamp: Optional[float]):
        now = time.time()
        dt_s = min(now - prev_timestamp, 2.0) if prev_timestamp else 0.0

        cpu_mw = gpu_mw = None
        p_cluster_mhz = None
        # Only the CPU Power Stats block's GPU Power line is used, not the
        # later GPU usage block's duplicate value, keeps domains time
        # aligned to the same sample.
        in_gpu_usage_block = False
        for line in lines:
            if line.startswith("**** GPU usage"):
                in_gpu_usage_block = True
                continue
            if in_gpu_usage_block:
                continue
            m = re.search(r"CPU Power:\s+(\d+)\s+mW", line)
            if m:
                cpu_mw = int(m.group(1))
            m = re.search(r"GPU Power:\s+(\d+)\s+mW", line)
            if m and gpu_mw is None:
                gpu_mw = int(m.group(1))

            m = re.search(r"P\d+-Cluster HW active frequency:\s+(\d+)\s+MHz", line)
            if m and p_cluster_mhz is None:
                p_cluster_mhz = int(m.group(1))
        if dt_s <= 0:
            return  # first sample, no interval to integrate yet
        with self._lock:
            if cpu_mw is not None:
                self._cumulative_uj["cpu"] += int(cpu_mw * dt_s * 1000)
            if gpu_mw is not None:
                self._cumulative_uj["gpu"] += int(gpu_mw * dt_s * 1000)
            if p_cluster_mhz is not None:
                self._latest_freq_mhz = p_cluster_mhz
            self._samples.append({
                "timestamp": now,
                "cpu_mw": cpu_mw,
                "gpu_mw": gpu_mw,
                "dt_s": dt_s,
            })

    def get_samples_since(self, start_time: float) -> List[Dict]:
        """
        Return retained power samples with timestamp >= start_time, for
        run-local idle-baseline classification (mirrors GPU's per-sample
        gpu_samples table on other platforms, which this reader has no
        equivalent of — samples are kept in-memory here instead).
        Does not clear the buffer; caller filters by run window.
        """
        with self._lock:
            return [s for s in self._samples if s["timestamp"] >= start_time]

    def trim_samples_before(self, cutoff_time: float):
        """
        Drop retained samples older than cutoff_time to bound memory growth
        across a long-running process instrumenting many runs.
        """
        with self._lock:
            self._samples = [s for s in self._samples if s["timestamp"] >= cutoff_time]

    def read_energy_uj(self) -> Dict[str, int]:
        """
        Return cumulative energy in microjoules since process start.
        Counter-style, matches RAPLReader. Callers compute deltas.
        """
        with self._lock:
            return dict(self._cumulative_uj)

    def read_energy(self) -> Dict[str, int]:
        """
        Alias for read_energy_uj(), matching RAPLReader's real method
        name used by energy_engine.py (self.rapl.read_energy(), lines
        709/1086). Discovered by constructing a real EnergyEngine and
        calling start_measurement() for the first time this session.
        """
        return self.read_energy_uj()

    def read_energy_safe(self) -> Dict[str, int]:
        return self.read_energy_uj()

    def read_gpu_msr(self):
        # Return cumulative GPU energy in µJ from the powermetrics sampler.
        # Called by ReaderFactory.get_gpu_energy_uj() at measurement start/end.
        # Delta is computed by _resolve_gpu_total_uj() in energy_engine.py.
        with self._lock:
            return self._cumulative_uj.get("gpu", 0)
        
    def read_normalized(self) -> "NormalizedEnergyReading":
        """Map IOKit/powermetrics keys to canonical NormalizedEnergyReading.

        Apple Silicon key mapping (M1 Pro / M-series unified memory):
            cpu -> pkg_uj   (CPU_APPLE unified rail = full package envelope)
            cpu -> cpu_uj   (same rail; no cores-only subdomain on Apple)
            gpu -> gpu_uj   (Apple integrated GPU domain)
            N/A -> dram_uj  (unified memory architecture, no DRAM domain)

        Both pkg_uj and cpu_uj use the same value because Apple Silicon
        does not expose a cores-only subdomain. This is correct: on Apple,
        CPU energy IS the package energy as reported by powermetrics.
        """
        import time

        raw = self.read_energy_uj()
        cpu_val = raw.get("cpu")
        return NormalizedEnergyReading(
            pkg_uj  = cpu_val,
            cpu_uj  = cpu_val,
            gpu_uj  = raw.get("gpu"),
            dram_uj = None,
            ts_ns   = time.monotonic_ns(),
        )

    def get_frequency_mhz(self) -> int:
        """Return latest P-cluster HW active frequency in MHz.
        P-cluster = performance cores where LLM inference runs on Apple Silicon.
        Returns 0 until first powermetrics sample arrives.
        """
        with self._lock:
            return self._latest_freq_mhz

    def get_domains(self) -> List[str]:
        return list(self.DOMAINS)

    def get_measurement_schema(self):
        from core.readers.measurement_schema import SCHEMA_APPLE_IOKIT
        return SCHEMA_APPLE_IOKIT

    def is_available(self) -> bool:
        return self._available

    def get_name(self) -> str:
        return "IOKitPowerReader"
