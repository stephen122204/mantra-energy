"""
GPU energy collector for A-LEMS platform — Chunk 15-A.

Mirrors HighFrequencySampler pattern from core/utils/sampling.py exactly.
Runs in background thread at 10 Hz alongside existing energy_engine sampling.

Backend detection order (15-A implements MSR + None; 15-B adds the rest):
    DCGM     → GN100 / DGX systems (15-B)
    NVML     → NVIDIA discrete GPUs (15-B)
    MSR PP1  → Intel integrated GPU, UBUNTU2505 Iris Xe (THIS CHUNK)
    ROCm     → AMD GPUs (15-B stub)
    IOKit    → Apple Silicon (15-B stub)
    None     → graceful fallback, no samples collected

PAC-2 compliant: GPUCollector is the ONLY place that imports GPU backends.
Never import backends directly in energy_engine.py or harness.py.

cp to: core/energy/gpu_collector.py
"""

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 10 Hz matches cpu_samples and interrupt_samples rate.
# NVML caps at ~50 Hz; 10 Hz balances detail vs collector overhead.
DEFAULT_SAMPLING_HZ = 10

# 2000 samples = ~3.3 min at 10 Hz before oldest-drop kicks in.
MAX_QUEUE_SIZE = 2000


@dataclass
class GpuSample:
    """
    One GPU energy sample. Mirrors EnergySample shape from sampling.py.
    source column identifies backend — critical for paper methodology section.
    Reviewer will ask: how did you measure GPU energy on each platform?
    """
    gpu_index: int
    sample_start_ns: int
    sample_end_ns: int
    interval_ns: int
    energy_start_uj: Optional[int]
    energy_end_uj: Optional[int]
    energy_uj: Optional[int]       # denorm delta for query speed
    power_mw: Optional[int]
    util_gpu_pct: Optional[float]
    util_mem_pct: Optional[float]
    sm_clock_mhz: Optional[int]
    mem_clock_mhz: Optional[int]
    mem_used_mb: Optional[int]
    temperature_c: Optional[int]
    source: str

    def to_dict(self):
        # type: () -> Dict[str, Any]
        """Convert to dict for DB INSERT via samples repository."""
        return {
            'gpu_index':       self.gpu_index,
            'sample_start_ns': self.sample_start_ns,
            'sample_end_ns':   self.sample_end_ns,
            'interval_ns':     self.interval_ns,
            'energy_start_uj': self.energy_start_uj,
            'energy_end_uj':   self.energy_end_uj,
            'energy_uj':       self.energy_uj,
            'power_mw':        self.power_mw,
            'util_gpu_pct':    self.util_gpu_pct,
            'util_mem_pct':    self.util_mem_pct,
            'sm_clock_mhz':    self.sm_clock_mhz,
            'mem_clock_mhz':   self.mem_clock_mhz,
            'mem_used_mb':     self.mem_used_mb,
            'temperature_c':   self.temperature_c,
            'source':          self.source,
        }


class NoneBackend:
    """
    Fallback backend. Returns None for all reads.
    Used when no GPU energy backend is available on this platform.
    PAC-4 compliant: never raises, always returns None gracefully.
    """
    SOURCE = 'none'

    def is_available(self):
        # type: () -> bool
        return False

    def read_energy_uj(self, gpu_index=0):
        # type: (int) -> Optional[int]
        """No backend available — always None."""
        return None

    def read_signals(self, gpu_index=0):
        # type: (int) -> Dict[str, Any]
        """No signals available."""
        return {}

    def get_gpu_info(self):
        # type: () -> List[Dict[str, Any]]
        """No GPU info available."""
        return []


class MSRPP1Backend:
    """
    Intel integrated GPU backend via MSR 0x641 (MSR_PP1_ENERGY_STATUS).
    Verified on UBUNTU2505: Intel i7-1165G7 + Iris Xe Graphics.

    Energy unit: 61.0352 µJ/LSB (MSR 0x606 bits[12:8]=14, verified).
    No sudo required on UBUNTU2505 (msr module loaded, group permissions set).

    GPU is in PKG remainder bucket: PKG = core + uncore + remainder.
    GPU is sub-component of remainder, NOT inside uncore.
    intel-rapl:0:1 sysfs = uncore domain (L3/ring bus), NOT GPU.

    No util/clock/memory signals via this backend — those columns NULL.
    """
    SOURCE = 'msr_pp1'
    # 2^(-14) J = 61.0352 µJ per LSB — from MSR 0x606 bits[12:8]=14
    ENERGY_UNIT_UJ = 61.0352

    def __init__(self, rapl_reader):
        """
        Args:
            rapl_reader: RAPLReader instance with gpu_pp1_available flag
                         and read_gpu_msr() method. Injected for PAC-2 compliance.
        """
        self._rapl = rapl_reader
        # Cache model/driver from rapl_reader if available
        self._gpu_model = getattr(rapl_reader, '_gpu_model', 'Intel Iris Xe')
        self._gpu_driver = getattr(rapl_reader, '_gpu_driver', 'i915')

    def is_available(self):
        # type: () -> bool
        """Returns True only if MSR 0x641 was successfully probed at init."""
        return bool(getattr(self._rapl, 'gpu_pp1_available', False))

    def read_energy_uj(self, gpu_index=0):
        # type: (int) -> Optional[int]
        """
        Read current MSR 0x641 counter and convert to µJ.
        gpu_index ignored: only one integrated GPU on supported platforms.
        Returns None on read failure — never raises (PAC-4 compliant).
        """
        raw = self._rapl.read_gpu_msr()
        if raw is None:
            return None
        # Convert raw LSB count to µJ using verified energy unit
        return int(raw * self.ENERGY_UNIT_UJ)

    def read_signals(self, gpu_index=0):
        # type: (int) -> Dict[str, Any]
        """MSR PP1 exposes energy only — no util/clock/memory signals."""
        return {}

    def get_gpu_info(self):
        # type: () -> List[Dict[str, Any]]
        """
        Returns metadata dict for gpu_config INSERT.
        Model and driver sourced from hw_config.json gpu block via rapl_reader.
        """
        return [{
            'gpu_index':        0,
            'vendor':           'intel',
            'model':            self._gpu_model,
            'driver_version':   self._gpu_driver,
            'cuda_version':     None,
            'rocm_version':     None,
            'vbios_version':    None,
            'pci_id':           None,
            'memory_total_mb':  None,
            'energy_supported': 1,
            'backend':          self.SOURCE,
        }]


class GPUCollector:
    """
    GPU energy sampler. Runs in background thread at 10 Hz.
    Mirrors HighFrequencySampler from core/utils/sampling.py exactly.

    Lifecycle mirrors energy_engine._start_sampling / _stop_sampling:
        collector = GPUCollector(rapl_reader=rapl)
        collector.start()                    # before energy_engine.start_measurement()
        # ... workload runs ...
        samples = collector.stop()           # after energy_engine.stop_measurement()
        # persist via db.insert_gpu_samples(run_id, samples)

    Backend detection is automatic. NoneBackend used when no GPU energy
    source available — stop() returns empty list, no DB rows written.
    15-B adds NVML/DCGM/IOKit/ROCm backends to _detect_backend().
    """

    def __init__(self, rapl_reader=None, sampling_hz=DEFAULT_SAMPLING_HZ):
        """
        Args:
            rapl_reader: RAPLReader instance. Used for MSRPP1Backend detection.
                         Pass None on platforms without RAPL (e.g. GN100).
            sampling_hz: Sample rate. Default 10 Hz.
        """
        self.sampling_hz = sampling_hz
        self.interval = 1.0 / sampling_hz

        # Detect backend — 15-B will expand this
        self.backend = self._detect_backend(rapl_reader)
        self.source = self.backend.SOURCE

        self._queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
        self._thread = None
        self._running = False
        self._samples_taken = 0
        self._samples_dropped = 0

        # Previous sample state for delta computation
        self._prev_energy_uj = None
        self._prev_ts_ns = None

        logger.info("GPUCollector: backend=%s available=%s",
                    self.source, self.backend.is_available())

    def _detect_backend(self, rapl_reader):
        # type: (Any) -> Any
        """
        Backend detection. First available wins.
        15-B will uncomment DCGM/NVML/ROCm/IOKit blocks.
        NoneBackend returned if nothing available — never raises.
        """
        # DCGM — GN100/DGX systems (15-B implements)
        # try:
        #     from core.energy.gpu_collector import DCGMBackend
        #     b = DCGMBackend()
        #     if b.is_available():
        #         logger.info("GPUCollector: using DCGMBackend")
        #         return b
        # except Exception as e:
        #     logger.debug("DCGMBackend probe: %s", e)

        # NVML — NVIDIA discrete GPUs (15-B implements)
        # try:
        #     from core.energy.gpu_collector import NVMLBackend
        #     b = NVMLBackend()
        #     if b.is_available():
        #         logger.info("GPUCollector: using NVMLBackend")
        #         return b
        # except Exception as e:
        #     logger.debug("NVMLBackend probe: %s", e)

        # MSR PP1 — Intel integrated GPU, available now on UBUNTU2505
        if rapl_reader is not None:
            try:
                b = MSRPP1Backend(rapl_reader)
                if b.is_available():
                    logger.info("GPUCollector: using MSRPP1Backend")
                    return b
            except Exception as e:
                logger.debug("MSRPP1Backend probe: %s", e)

        # ROCm — AMD GPU (15-B stub)
        # try:
        #     from core.energy.gpu_collector import ROCmBackend
        #     b = ROCmBackend()
        #     if b.is_available():
        #         logger.info("GPUCollector: using ROCmBackend")
        #         return b
        # except Exception as e:
        #     logger.debug("ROCmBackend probe: %s", e)

        # IOKit — Apple Silicon (15-B stub)
        # try:
        #     from core.energy.gpu_collector import IOKitBackend
        #     b = IOKitBackend()
        #     if b.is_available():
        #         logger.info("GPUCollector: using IOKitBackend")
        #         return b
        # except Exception as e:
        #     logger.debug("IOKitBackend probe: %s", e)

        logger.debug("GPUCollector: no backend available, using NoneBackend")
        return NoneBackend()

    def start(self):
        """
        Start background sampling thread.
        No-op if backend unavailable — stop() returns empty list.
        """
        if not self.backend.is_available():
            logger.debug("GPUCollector.start: no backend, skipping thread")
            return

        self._running = True
        self._samples_taken = 0
        self._samples_dropped = 0
        self._prev_energy_uj = None
        self._prev_ts_ns = None

        self._thread = threading.Thread(
            target=self._sampling_loop,
            daemon=True,
            name="gpu-sampler",
        )
        self._thread.start()
        logger.debug("GPUCollector started at %d Hz", self.sampling_hz)

    def stop(self):
        # type: () -> List[GpuSample]
        """
        Stop sampling thread and return all collected samples.
        Safe to call even if start() was skipped (returns empty list).
        """
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

        samples = []
        while not self._queue.empty():
            try:
                samples.append(self._queue.get_nowait())
            except queue.Empty:
                break

        logger.info("GPUCollector stopped: %d samples taken, %d dropped",
                    self._samples_taken, self._samples_dropped)
        return samples

    def get_sample_count(self):
        # type: () -> int
        """Current sample count — for coverage checks during run."""
        return self._samples_taken

    def _sampling_loop(self):
        """
        Background sampling loop at configured Hz.
        Delta computed between consecutive samples — mirrors energy_samples
        pkg_start_uj / pkg_end_uj pattern exactly.
        MSR counter wraparound (32-bit) handled with warning + skip.
        Queue full → oldest dropped (same policy as HighFrequencySampler).
        """
        logger.debug("GPUCollector._sampling_loop started")
        next_sample = time.time()

        while self._running:
            try:
                ts_ns = time.time_ns()
                energy_uj = self.backend.read_energy_uj(gpu_index=0)
                signals = self.backend.read_signals(gpu_index=0)

                # Skip first sample — no previous reading for delta
                if (self._prev_ts_ns is not None
                        and energy_uj is not None
                        and self._prev_energy_uj is not None):

                    interval_ns = ts_ns - self._prev_ts_ns
                    delta_uj = energy_uj - self._prev_energy_uj

                    if delta_uj < 0:
                        # Counter wrapped — skip sample, update prev, continue
                        logger.warning(
                            "GPUCollector: counter wraparound detected "
                            "(prev=%d cur=%d), skipping sample",
                            self._prev_energy_uj, energy_uj)
                    else:
                        sample = GpuSample(
                            gpu_index=0,
                            sample_start_ns=self._prev_ts_ns,
                            sample_end_ns=ts_ns,
                            interval_ns=interval_ns,
                            energy_start_uj=self._prev_energy_uj,
                            energy_end_uj=energy_uj,
                            energy_uj=delta_uj,
                            power_mw=signals.get('power_mw'),
                            util_gpu_pct=signals.get('util_gpu_pct'),
                            util_mem_pct=signals.get('util_mem_pct'),
                            sm_clock_mhz=signals.get('sm_clock_mhz'),
                            mem_clock_mhz=signals.get('mem_clock_mhz'),
                            mem_used_mb=signals.get('mem_used_mb'),
                            temperature_c=signals.get('temperature_c'),
                            source=self.source,
                        )
                        # Oldest-drop policy — same as HighFrequencySampler
                        try:
                            self._queue.put_nowait(sample)
                            self._samples_taken += 1
                        except queue.Full:
                            try:
                                self._queue.get_nowait()
                                self._queue.put_nowait(sample)
                                self._samples_dropped += 1
                            except queue.Empty:
                                pass

                self._prev_energy_uj = energy_uj
                self._prev_ts_ns = ts_ns

            except Exception as e:
                # Never crash the sampling thread — log and continue
                logger.warning("GPUCollector sample error: %s", e)

            # Precise sleep to maintain configured Hz
            next_sample += self.interval
            sleep_time = next_sample - time.time()
            if sleep_time > 0:
                time.sleep(sleep_time)

        logger.debug("GPUCollector._sampling_loop exited")
