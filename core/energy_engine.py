#!/usr/bin/env python3
"""
================================================================================
ENERGY ENGINE – Main Orchestrator for Module 1
================================================================================

This module ties together all hardware readers and provides a clean interface
for measuring energy consumption during AI workloads. It is designed to be used
as a context manager or directly via start/stop methods.

The EnergyEngine handles:
- Initializing all readers (RAPL, perf, turbostat, sensors, MSR)
- Core pinning for consistent measurements (Req 1.15)
- Idle baseline measurement using research‑grade utility (Req 1.45)
- High‑frequency sampling (Req 1.46)
- Coordinated start/stop of all readers
- Assembling a complete RawEnergyMeasurement object
- Validation of measurement quality

IMPORTANT: This engine returns RAW measurements only.
Baseline correction happens in the analysis layer (EnergyAnalyzer).

All paths and settings come from Module 0’s configuration (hw_config.json,
app_settings.yaml). No hardcoding.

Author: Deepak Panigrahy
================================================================================
"""

import json
import logging
import os
import platform
import queue
import statistics
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from core.readers.factory import ReaderFactory
from core.readers.gpu_collector import GPUCollector
from core.readers.energy_collector import EnergyCollector
from core.readers.normalized_writer import NormalizedWriter
from core.readers.legacy_writer import LegacyWriter
from core.utils.platform import get_platform_capabilities

import requests


from core.models.baseline_measurement import BaselineMeasurement
# Import the new raw measurement model (Layer 1)
from core.models.raw_energy_measurement import RawEnergyMeasurement
from core.utils.core_pinner import CorePinner
# Import utilities
from core.utils.debug import dprint, init_debug_from_env
from core.utils.validators import MeasurementValidator

# ====================================================================


# ============================================================================
# Fix Python path – ensure core modules are importable
# ============================================================================
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Import the new raw measurement model (Layer 1)
from core.models.raw_energy_measurement import RawEnergyMeasurement
# MSRReader and SchedulerMonitor now via factory — PAC-2 compliant
# PerfReader via factory (self.cpu_reader) — direct import removed (PAC-2)
# ============================================================================
# Import all readers and models
# ============================================================================
from core.readers.rapl_reader import RAPLReader
# MSRReader and SchedulerMonitor now via factory — PAC-2 compliant
from core.readers.factory import ReaderFactory as _ReaderFactory
from core.readers.sensor_reader import SensorReader
# TurbostatReader now via ReaderFactory.get_turbostat_reader() — PAC-2 compliant
from core.utils.core_pinner import CorePinner
# Import utilities
from core.utils.debug import dprint, init_debug_from_env
# Import baseline utilities (will be used by analysis layer, not here)
from core.utils.idle_baseline import measure_idle_baseline as measure_baseline
from core.utils.validators import MeasurementValidator

# Initialize debug system
init_debug_from_env()

logger = logging.getLogger(__name__)


class EnergyEngine:
    """
    Main energy measurement engine orchestrating all readers.

    This is the primary interface for Modules 2 and 3. It provides:
    1. Context manager for easy measurement (`with engine as m:`)
    2. High‑frequency sampling (Req 1.46)
    3. Idle baseline measurement (Req 1.45) – stored separately, NOT applied
    4. Core pinning (Req 1.15)
    5. Measurement validation
    6. Multiple‑run statistics

    All readers are initialized from the configuration passed in.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the energy engine with configuration from Module 0.

        Args:
            config: The complete configuration dictionary, usually loaded from
                    `hw_config.json` and merged with `app_settings.yaml`.
                    Expected to contain sections for each reader and settings.

        The constructor instantiates all readers and sets up logging.
        """
        dprint("Initializing EnergyEngine")
        dprint("\n" + "=" * 60)
        dprint("🔍 ENERGY ENGINE CONFIG DEBUG")
        dprint("=" * 60)
        dprint(f"Config type: {type(config)}")
        dprint(f"Config keys: {list(config.keys())}")
        dprint(f"'rapl' in config: {'rapl' in config}")
        if "rapl" in config:
            dprint(f"rapl paths: {config['rapl'].get('paths', {})}")
        dprint(f"'settings' in config: {'settings' in config}")
        if "settings" in config:
            dprint(f"settings keys: {list(config['settings'].keys())}")
        dprint("=" * 60 + "\n")

        # interrupt initializations
        self.collect_interrupt_samples = True
        self._workload_pid = 0
        self._interrupt_sample_counter = 0
        self.last_interrupt_samples = []

        # Store configuration
        self.config = config
        self.settings = config.get("settings", {})  # app_settings.yaml content
        

        # --------------------------------------------------------------------
        # Initialize all hardware readers
        # --------------------------------------------------------------------
        # ------------------------------------------------------------------
        # Chunk 1: Platform-aware reader initialisation via ReaderFactory.
        # The factory reads platform.json (written by PlatformDetector) and
        # returns the correct concrete reader for this machine:
        #   MEASURED → RAPLReader / IOKitPowerReader
        #   INFERRED → EnergyEstimator (stub; ML model in Chunk 7)
        #   LIMITED  → DummyEnergyReader (zeros + warning)
        # ------------------------------------------------------------------
 
        # Detect platform once and cache for the process lifetime
        self._platform_caps = get_platform_capabilities()
 
        # Energy reader — primary measurement source
        self.energy_reader = ReaderFactory.get_energy_reader(config, self._platform_caps)
 
        # CPU reader — instruction/cycle counters (PerfReader on Linux)
        self.cpu_reader    = ReaderFactory.get_cpu_reader(config, self._platform_caps)
 
        # Thermal reader — temperature sensors (SensorReader on Linux)
        self.thermal_reader = ReaderFactory.get_thermal_reader(config, self._platform_caps)
 
        # ------------------------------------------------------------------
        # Keep existing readers that are not yet factorised (Chunks 2-7)
        # These are still directly instantiated until their chunk arrives.
        # ------------------------------------------------------------------
        self.rapl      = self.energy_reader          # alias: existing code uses self.rapl
        self.perf      = self.cpu_reader             # alias: existing code uses self.perf
        self.sensor    = self.thermal_reader         # alias: existing code uses self.sensor
        self.gpu_collector = GPUCollector(rapl_reader=self.rapl)
        self.last_gpu_samples = []
        self.last_v2_samples = []          # NormalizedWriter samples, inserted post run_id
        self.last_legacy_samples = []      # LegacyWriter samples, inserted post run_id
        # EnergyCollector replaces SPBMSampler and _sampling_loop (16B3).
        # Platform differences declared in reader.get_measurement_schema().
        # Zero platform-specific branching here — collector is generic.
        self._energy_collector = None      # initialized in start_measurement per run
        self.last_spbm_samples = []        # kept for backward compat, always empty now

        # PowerRailSampler: reads all 10 SPBM power rails at 10 Hz — GN100 only
        try:
            from core.readers.power_rail_sampler import PowerRailSampler
            _power_paths = _get_power_paths() if hasattr(self, '_get_power_paths') else {}
            if not _power_paths:
                import json, pathlib
                _cfg = pathlib.Path(__file__).parent.parent / "config" / "hw_config.json"
                try:
                    _power_paths = json.loads(_cfg.read_text()).get("spbm", {}).get("power_paths", {})
                except Exception:
                    _power_paths = {}
            if _power_paths:
                self.power_rail_sampler = PowerRailSampler(_power_paths, hz=10)
            else:
                self.power_rail_sampler = None
        except Exception as e:
            logger.warning("PowerRailSampler init failed (PAC-2): %s", e)
            self.power_rail_sampler = None
        self.last_rail_result = None

        # PAC-2 compliant: TurbostatReader now via factory (Chunk 7 factorisation)
        # Linux x86 -> TurbostatReader, macOS/other -> DummyTurbostatReader
        self.turbostat = ReaderFactory.get_turbostat_reader(config, self._platform_caps)
        # PAC-2 compliant: MSRReader and SchedulerMonitor via factory (Chunk 7)
        # Linux x86 -> MSRReader, macOS/other -> DummyMSRReader
        # Linux     -> SchedulerMonitor, macOS/other -> DummySchedulerMonitor
        self.msr       = _ReaderFactory.get_msr_reader(config)
        self.scheduler = _ReaderFactory.get_scheduler_monitor(config)
        self.disk_reader = _ReaderFactory.get_disk_reader(config)         # pid set later via set_workload_pid
        self._io_samples: list = []
 
        # Log which readers were selected (visible in --verbose mode)
        logger.info(
            "EnergyEngine readers: energy=%s cpu=%s thermal=%s mode=%s",
            self.energy_reader.get_name(),
            self.cpu_reader.get_name(),
            self.thermal_reader.get_name(),
            self._platform_caps.measurement_mode,
        )

        self.sensor.initialize()
        # --------------------------------------------------------------------
        # Load settings from config – handle both dict and object formats
        # --------------------------------------------------------------------
        experiment_settings = self.settings.get("experiment", {})
        measurement_settings = self.settings.get("measurement", {})

        # Convert to dictionary if they are objects
        if hasattr(experiment_settings, "__dict__"):
            experiment_settings = experiment_settings.__dict__
        if hasattr(measurement_settings, "__dict__"):
            measurement_settings = measurement_settings.__dict__

        # Core pinning (Req 1.15)
        self.pinned_cores = experiment_settings.get("pinned_cores", [0, 1])

        # Sampling rate (Req 1.46)
        self.sampling_rate_hz = measurement_settings.get("sampling_rate_hz", 100)

        # Idle baseline duration (Req 1.45) – used as default for the utility
        self.idle_baseline_seconds = measurement_settings.get("baseline_seconds", 5)

        # Cool‑down between runs (Req 3.5)
        self.cool_down_seconds = experiment_settings.get("cool_down_seconds", 30)

        # Create core pinner instance
        self.core_pinner = CorePinner(default_cores=self.pinned_cores)

        # Idle baseline storage (joules per second per domain)
        # This is stored as metadata only – NEVER applied to raw data
        self.idle_baseline: Optional[Dict[str, float]] = None

        # Measurement state
        self.measurement_id: Optional[str] = None
        self.start_time: Optional[float] = None
        self.start_readings: Dict[str, Any] = {}
        self.end_readings: Dict[str, Any] = {}
        self.measurement: Optional[RawEnergyMeasurement] = None

        # Sampling thread for high‑frequency data
        self._sampling_thread: Optional[threading.Thread] = None
        self._sampling_queue: queue.Queue = queue.Queue()
        self._sampling_active = False
        self._side_sampling_active = False       # IO + interrupt side-sampler (10Hz)
        self._side_sampling_thread = None
        msr_available = (
            hasattr(self.msr, "helper_available") and self.msr.helper_available
        ) or self.msr.rdmsr_available
        # ====================================================================
        # Thermal sampling (1Hz)
        # ====================================================================
        self.thermal_queue = queue.Queue()
        self.thermal_sampling_active = False
        self.thermal_sampling_thread = None
        self.thermal_config = config.get("thermal", {})
        self.thermal_rate_hz = self.thermal_config.get("sampling_rate_hz", 1)

        # Web UI settings - multiple servers support
        webui_config = self.settings.get("webui", {})
        self.webui_enabled = webui_config.get("enabled", False)
        self.webui_servers = []

        if self.webui_enabled:
            for server in webui_config.get("servers", []):
                if server.get("active", False):
                    self.webui_servers.append(
                        {
                            "url": server["url"]
                            + server.get("api_endpoint", "/api/update"),
                            "name": server.get("name", "unknown"),
                            "timeout": webui_config.get("timeout_ms", 1) / 1000.0,
                        }
                    )

        self.current_run_id = None

        dprint(
            "EnergyEngine initialized",
            readers={
                "rapl": self.rapl is not None,
                "perf": getattr(self.perf, 'perf_available', getattr(self.perf, '_available', False)),
                "turbostat": self._platform_caps.has_turbostat,
                "sensor": len(self.sensor.available_sensors) > 0,
                "msr": msr_available,
            },
        )

        
    def _start_thermal_sampling(self):
        """Start thermal sampling thread"""
        self.thermal_sampling_active = True
        self.thermal_sampling_thread = threading.Thread(
            target=self._thermal_sampling_loop
        )
        self.thermal_sampling_thread.daemon = True
        self.thermal_sampling_thread.start()

    def _thermal_sampling_loop(self):
        """
        Thermal sampling thread (1Hz default).
 
        Chunk 2 final:
            - Stores sample_start_ns + sample_end_ns explicitly
            - timestamp_ns = sample_end_ns (backward compat)
            - interval_ns stored for verification
            - 4-tuple in queue: (now, readings, throttle_detected,
              sample_start_ns, sample_end_ns, interval_ns)
        """
        interval    = 1.0 / self.thermal_rate_hz
        next_sample = time.time()
 
        while self.thermal_sampling_active:
            now = time.time()
            if now >= next_sample:
                # Capture start timestamp before sensor read
                sample_start_ns = time.time_ns()
 
                # Read all thermal sensors
                readings          = self.sensor.read_all_thermal()
                throttle_detected = False
 
                # Check throttling against per-sensor thresholds
                for role, temp in readings.items():
                    if temp and hasattr(self.sensor, "throttle_thresholds"):
                        threshold = self.sensor.throttle_thresholds.get(role)
                        if threshold and temp > threshold:
                            throttle_detected = True
 
                # Capture end timestamp + compute interval
                sample_end_ns = time.time_ns()
                interval_ns   = sample_end_ns - sample_start_ns
 
                # Store 6-tuple: consumer unpacks all fields
                self.thermal_queue.put((
                    now,
                    readings,
                    throttle_detected,
                    sample_start_ns,
                    sample_end_ns,
                    interval_ns,
                ))
 
                next_sample = now + interval    # prevent drift
            else:
                time.sleep(min(0.1, next_sample - now))

    def _stop_thermal_sampling(self):
        """Stop thermal sampling and collect remaining samples"""
        self.thermal_sampling_active = False
        if self.thermal_sampling_thread:
            self.thermal_sampling_thread.join(timeout=2)

        # Collect any remaining samples
        thermal_samples = []
        while not self.thermal_queue.empty():
            thermal_samples.append(self.thermal_queue.get())
        return thermal_samples

    # ------------------------------------------------------------------------
    # Core pinning (Req 1.15)
    # ------------------------------------------------------------------------
    def pin_cores(self, cores: Optional[List[int]] = None) -> None:
        """
        Pin the current process to specific CPU cores.

        Args:
            cores: List of core indices. If None, uses the configured default.

        Req 1.15: Physical Core Affinity – eliminates noise from thread migration.
        """
        if cores is None:
            cores = self.pinned_cores
        self.core_pinner.pin_to_cores(cores)
        dprint(f"Pinned to cores {cores}")

    # ------------------------------------------------------------------------
    # Idle baseline measurement (Req 1.45) – uses research‑grade utility
    # ------------------------------------------------------------------------
    def measure_idle_baseline(
        self,
        duration_seconds: int = 10,
        num_samples: int = 10,
        pre_wait_seconds: int = 10,
        force_remeasure: bool = False,
        measure_gpu: bool = True,
    ) -> BaselineMeasurement:
        """
        Measure system idle energy baseline.
        """
        # Measure baseline using utility (returns BaselineMeasurement object)
        dprint(f"🔍 DEBUG - force_remeasure value: {force_remeasure}")
        baseline = measure_baseline(
            energy_reader=self.rapl,      # self.rapl IS SPBMEnergyReader on GN100 — factory set this
            core_pinner=self.core_pinner,
            duration_seconds=duration_seconds,
            num_samples=num_samples,
            pre_wait_seconds=pre_wait_seconds,
            pin_cores=self.pinned_cores,
            force_remeasure=force_remeasure,
            measure_gpu=measure_gpu,
            # cache_file not passed — uses DEFAULT_CACHE_FILE from get_baseline_cache_path()
            # which resolves ALEMS_DATA_ROOT + hostname on GN100 (Layer 1)
            # yaml cache_file is Layer 2 fallback — already consumed by get_baseline_cache_path()
        )


        # DEBUG: Object ID after measure_baseline
        print(f"🔍 DEBUG1 - baseline object ID after measure_baseline: {id(baseline)}")
        print(
            f"🔍 DEBUG1 - baseline metadata after measure_baseline: {baseline.metadata}"
        )

        # Update baseline_id with PID to ensure uniqueness
        baseline.baseline_id = f"baseline_{int(time.time())}_{os.getpid()}"
        baseline.timestamp = time.time()

        # DEBUG: Object ID after updates
        print(f"🔍 DEBUG1 - baseline object ID after updates: {id(baseline)}")
        print(f"🔍 DEBUG1 - baseline metadata after updates: {baseline.metadata}")
        print(f"🔍 DEBUG1 - baseline.__dict__: {baseline.__dict__}")

        self.idle_baseline = baseline
        return baseline

    # ------------------------------------------------------------------------
    # High‑frequency sampling (Req 1.46)
    # ------------------------------------------------------------------------
    def _sampling_loop(self) -> None:
        """
        Background thread: sample RAPL energy at configured rate (default 100Hz).
 
        Chunk 2 final:
            - Stores sample_start_ns + sample_end_ns explicitly (raw layer)
            - timestamp_ns = sample_end_ns for backward compatibility
            - interval_ns stored for verification (= end - start)
            - Uses self.energy_reader (Chunk 1 factory reader)
            - Fixes duplicate sample_counter increment bug
            - Keeps old delta fields (pkg_energy_uj etc) for backward compat
        """
        interval       = 1.0 / self.sampling_rate_hz   # seconds between samples
        next_sample    = time.time()
        sample_counter = 0
 
        while self._sampling_active:
            try:
                # --------------------------------------------------------
                # Read START — raw cumulative RAPL counters + timestamp
                # --------------------------------------------------------
                sample_start_ns = time.time_ns()
                start_readings  = self.energy_reader.read_energy_uj()
 
                # Sleep until next scheduled sample time
                next_sample += interval
                sleep_time   = next_sample - time.time()
                if sleep_time > 0:
                    time.sleep(sleep_time)
 
                # --------------------------------------------------------
                # Read END — raw cumulative RAPL counters + timestamp
                # --------------------------------------------------------
                sample_end_ns = time.time_ns()
                end_readings  = self.energy_reader.read_energy_uj()
                interval_ns   = sample_end_ns - sample_start_ns
 
                # --------------------------------------------------------
                # Extract per-domain values
                # Domain names from hw_config: 'package-0', 'core', 'uncore'
                # --------------------------------------------------------
                pkg_start    = start_readings.get("package-0", 0)
                pkg_end      = end_readings.get("package-0",   0)
                core_start   = start_readings.get("core",      0)
                core_end     = end_readings.get("core",        0)
                dram_start   = start_readings.get("dram",      0)
                dram_end     = end_readings.get("dram",        0)
                uncore_start = start_readings.get("uncore",    0)
                uncore_end   = end_readings.get("uncore",      0)
 
                # --------------------------------------------------------
                # Build sample dict
                # timestamp_ns = sample_end_ns (backward compat alias)
                # --------------------------------------------------------
                sample = {
                    # Backward compat — timestamp_ns = end time
                    "timestamp_ns":    sample_end_ns,
                    # Explicit start/end (Option 2 — raw layer)
                    "sample_start_ns": sample_start_ns,
                    "sample_end_ns":   sample_end_ns,
                    "interval_ns":     interval_ns,
                    # Raw RAPL counter values per domain
                    "pkg_start_uj":    pkg_start,
                    "pkg_end_uj":      pkg_end,
                    "core_start_uj":   core_start,
                    "core_end_uj":     core_end,
                    "dram_start_uj":   dram_start,
                    "dram_end_uj":     dram_end,
                    "uncore_start_uj": uncore_start,
                    "uncore_end_uj":   uncore_end,
                    # Old delta fields — backward compatibility
                    "pkg_energy_uj":    max(0, pkg_end    - pkg_start),
                    "core_energy_uj":   max(0, core_end   - core_start),
                    "dram_energy_uj":   max(0, dram_end   - dram_start),
                    "uncore_energy_uj": max(0, uncore_end - uncore_start),
                }
 
                # --------------------------------------------------------
                # Put into queue — drop oldest if full (non-blocking)
                # --------------------------------------------------------
                try:
                    self._sampling_queue.put_nowait(sample)
                except queue.Full:
                    try:
                        self._sampling_queue.get_nowait()   # drop oldest
                        self._sampling_queue.put_nowait(sample)
                    except queue.Empty:
                        pass
 
                # --------------------------------------------------------
                # Sample interrupts every 10th iteration (10Hz)
                # Single increment — fixes old double-increment bug
                # --------------------------------------------------------
                sample_counter += 1
 
                if self.collect_interrupt_samples and sample_counter % 10 == 0:
                    self.scheduler.sample_interrupts()
                    # Chunk 12: disk I/O sample at same 10Hz cadence
                    io_s = self.disk_reader.sample()
                    if io_s:
                        self._io_samples.append(io_s)
 
                # --------------------------------------------------------
                # Web UI telemetry — best-effort, never crashes loop
                # --------------------------------------------------------
                if self.webui_enabled and self.current_run_id and self.webui_servers:
                    for server in self.webui_servers:
                        try:
                            cpu_data = {}
                            if hasattr(self, "turbostat") and self.turbostat:
                                if hasattr(self.turbostat, "get_latest_sample"):
                                    cpu_data = self.turbostat.get_latest_sample() or {}
 
                            irq_rate = 0
                            if hasattr(self, "scheduler") and self.scheduler:
                                irq_rate = getattr(
                                    self.scheduler,
                                    "get_current_interrupt_rate",
                                    lambda: 0,
                                )()
                        except Exception:
                            pass    # web UI errors never crash sampling loop
 
            except Exception as e:
                logger.error("Sampling loop error: %s", e)
                time.sleep(0.01)    # brief pause to avoid tight error loop


        
    def _start_sampling(self) -> None:
        """Start the high‑frequency sampling thread."""
        self._start_thermal_sampling()
        if self._sampling_thread and self._sampling_thread.is_alive():
            logger.warning("Sampling already active")
            return

        self._sampling_active = True
        self._sampling_thread = threading.Thread(
            target=self._sampling_loop, name="EnergyEngine-Sampler", daemon=True
        )
        self._sampling_thread.start()
        dprint("Started high‑frequency sampling")

    def _stop_sampling(self) -> List[tuple]:
        """Stop sampling and retrieve all collected samples."""
        self._sampling_active = False

        if self._sampling_thread:
            self._sampling_thread.join(timeout=2.0)

        samples = []
        while not self._sampling_queue.empty():
            try:
                samples.append(self._sampling_queue.get_nowait())
            except queue.Empty:
                break

        dprint(f"Stopped sampling, collected {len(samples)} samples")
        return samples

    def set_workload_pid(self, pid: int) -> None:
        """Set PID for per-process tick tracking in interrupt sampler."""
        self._workload_pid = pid
        self.disk_reader.pid = pid


    def _resolve_domain_id_cache(self, schema) -> dict:
        """
        Build canonical_name -> domain_id from energy_domains table.
        Opens short-lived read-only connection — closed immediately after query.
        Called once per run at start_measurement, never during sampling loop.
        """
        import sqlite3
        try:
            from scripts.tools.path_loader import get_alems_db_path
            db_path = get_alems_db_path()   # resolves via ~/.alemsrc + socket.gethostname()
            conn = sqlite3.connect(db_path, timeout=5)
            cur = conn.execute("SELECT name, domain_id FROM energy_domains")
            result = {row[0]: row[1] for row in cur.fetchall()}
            conn.close()                   # closed immediately — no lock held
            return result
        except Exception as e:
            logger.warning("_resolve_domain_id_cache failed: %s", e)
            return {}

    def _resolve_source_id(self, schema) -> int:
        """
        Look up source_id for this reader's source name in energy_sources table.
        Opens short-lived read-only connection — closed immediately after query.
        Returns 1 (RAPL) as safe fallback — never crashes.
        """
        import sqlite3
        try:
            from scripts.tools.path_loader import get_alems_db_path
            db_path = get_alems_db_path()   # resolves via ~/.alemsrc + socket.gethostname()
            conn = sqlite3.connect(db_path, timeout=5)
            cur = conn.execute(
                "SELECT source_id FROM energy_sources WHERE name = ?",
                (schema.source,),
            )
            row = cur.fetchone()
            conn.close()                   # closed immediately — no lock held
            return row[0] if row else 1
        except Exception as e:
            logger.warning("_resolve_source_id failed: %s", e)
            return 1
    # ------------------------------------------------------------------------
    # Measurement session management
    # ------------------------------------------------------------------------

    def _side_sampling_loop(self) -> None:
        """
        10Hz side-sampler for IO and interrupt sampling.
        Runs alongside EnergyCollector — replaces piggy-backed sampling
        that was inside _sampling_loop before 16B3 deleted it.
        PAC-2: never crashes — logs and continues on any error.
        """
        interval = 0.1   # 10Hz — same cadence as old _sampling_loop side effects
        next_tick = time.monotonic() + interval
        while self._side_sampling_active:
            now = time.monotonic()
            sleep_s = next_tick - now
            if sleep_s > 0:
                time.sleep(sleep_s)
            next_tick += interval
            try:
                # IO sample — disk read/write bytes delta
                if self.collect_interrupt_samples:
                    self.scheduler.sample_interrupts()
                io_s = self.disk_reader.sample()
                if io_s:
                    self._io_samples.append(io_s)
            except Exception as e:
                logger.error("_side_sampling_loop error: %s", e)
                time.sleep(0.01)

    def start_measurement(self) -> str:
        """
        Start a new measurement session.

        This method:
        1. Captures snapshot values (RAPL, scheduler)
        2. Starts continuous readers (perf, turbostat)
        3. Starts high-frequency sampling
        """
        self.measurement_id = f"meas_{int(time.time())}_{os.getpid()}"
        self.start_time = time.time()

        # Pin to dedicated cores first
        self.pin_cores()

        # ====================================================================
        # STEP 1: Snapshot readers - capture START values
        # ====================================================================
        rapl_start = self.rapl.read_energy()
        self.scheduler_start = self.scheduler.read_all()

        self._start_thermal_sampling()

        # ====================================================================
        # Capture MSR thermal snapshot at START
        # ====================================================================
        msr_thermal_start = None
        msr_available = (
            hasattr(self.msr, "helper_available") and self.msr.helper_available
        ) or self.msr.rdmsr_available
        if hasattr(self, "msr") and msr_available:
            try:
                msr_thermal_start = self.msr.snapshot_thermal_state()
                print(f"\n🔥 THERMAL SNAPSHOT - START:")
                print(f"   Package: {msr_thermal_start['package']}")
                print(f"   Core: {msr_thermal_start['core']}")
                logger.debug(f"MSR thermal start: {msr_thermal_start}")
            except Exception as e:
                print(f"❌ Failed to capture start MSR thermal: {e}")
                logger.warning(f"Could not capture start MSR thermal: {e}")

        # GPU PP1 start counter — None on non-Tiger-Lake platforms
        gpu_start_uj = ReaderFactory.get_gpu_energy_uj(self.rapl)
        self.start_readings = {
            "rapl":        rapl_start,
            "scheduler":   self.scheduler_start,
            "sensor":      self.sensor.read_temperatures(),
            "msr_thermal": msr_thermal_start,
            "gpu_uj":      gpu_start_uj,   # MSR 0x641 at measurement start
        }
        # ====================================================================
        # Capture C-state counters at START
        # ====================================================================
        if hasattr(self, "msr") and self.msr:
            self.msr._cstate_start = self.msr.snapshot_cstate_counters()
            logger.debug(f"C-state start: {self.msr._cstate_start}")
        # ====================================================================
        # STEP 2: Start continuous readers
        # ====================================================================
        # perf: attach to task process pid so counters measure actual work
        # _workload_pid set by harness via set_workload_pid() before this call
        if self._platform_caps.has_perf:
            self.perf.start_process_measurement(pid=self._workload_pid)

        # turbostat: continuous sampling at the same rate as RAPL
        # <-- NEW: Compute interval in milliseconds from sampling_rate_hz
        interval_ms = (
            int(1000 / self.sampling_rate_hz) if self.sampling_rate_hz > 0 else 100
        )
        # <-- MODIFIED: Pass interval_ms to start_monitoring (new signature)
        if self._platform_caps.has_turbostat:
            self.turbostat.start_monitoring(interval_ms=interval_ms)
        elif self._platform_caps.arch == "aarch64" and self._platform_caps.has_arm_pmu:
            # ARM: ARMCPUFreqReader is the turbostat equivalent — start unconditionally
            self.turbostat.start_monitoring(interval_ms=interval_ms)

        # EnergyCollector: generic loop replacing _sampling_loop + SPBMSampler (16B3)
        try:
            schema = self.energy_reader.get_measurement_schema()
            if schema.domains:
                # Resolve domain_id_cache and source_id from schema
                # These are resolved here using pre-built schema — no DB access
                domain_id_cache = self._resolve_domain_id_cache(schema)
                source_id = self._resolve_source_id(schema)
                adapters = [NormalizedWriter(source_id, domain_id_cache)]
                if schema.source == "RAPL":
                    adapters.append(LegacyWriter())
                self._energy_collector = EnergyCollector(
                    reader=self.energy_reader,
                    adapters=adapters,
                    run_id=self.current_run_id,
                    source_id=source_id,
                )
                self._energy_collector.start()
            else:
                logger.info("start_measurement: empty schema — EnergyCollector not started")
                self._energy_collector = None
        except Exception as e:
            logger.warning("EnergyCollector start failed (PAC-2): %s", e)
            self._energy_collector = None
        # GPU energy sampling — runs at 10 Hz alongside EnergyCollector
        # GPUCollector.start() is no-op if no backend available (PAC-4 compliant)
        self.gpu_collector.start()
        # PowerRailSampler: 10 SPBM power rails — GN100 only (16B1)
        if self.power_rail_sampler:
            self.power_rail_sampler.start()        
        if self.collect_interrupt_samples:
            self.scheduler.start_interrupt_sampling(pid=self._workload_pid)
        
        self._io_samples = []
        self.disk_reader._last = None          # reset delta baseline
        self.disk_reader.device = self.disk_reader._detect_device()
        # Start 10Hz side-sampler for IO and interrupt sampling
        # Replaces the piggy-backed sampling that was in _sampling_loop (pre-16B3)
        self._side_sampling_active = True
        self._side_sampling_thread = threading.Thread(
            target=self._side_sampling_loop,
            name="EnergyEngine-SideSampler",
            daemon=True,
        )
        self._side_sampling_thread.start()
        dprint(f"Started measurement {self.measurement_id}")
        return self.measurement_id

    def _compute_gpu_total(
            self, gpu_start: Optional[int], gpu_end: Optional[int]
        ) -> Optional[int]:
            """
            Compute GPU total energy delta for a run.
            Returns None if either counter unavailable — never returns zero for missing.
            Args:
                gpu_start: MSR 0x641 value in µJ at run start, or None
                gpu_end:   MSR 0x641 value in µJ at run end, or None
            Returns:
                Delta in µJ as int, or None if unavailable.
            """
            if gpu_start is None or gpu_end is None:
                return None
            # Guard against counter wraparound (unlikely over a single run)
            if gpu_end < gpu_start:
                logger.warning("GPU MSR counter wraparound detected — returning None")
                return None
            return gpu_end - gpu_start

    def stop_measurement(self) -> RawEnergyMeasurement:
        """
        Stop measurement and return raw results.

        This method:
        1. Stops continuous readers and collects their data
        2. Captures snapshot end values
        3. Computes deltas
        4. Assembles RawEnergyMeasurement
        """
        if self.measurement_id is None:
            raise RuntimeError("No measurement in progress")

        # ====================================================================
        # STEP 1: Stop continuous readers FIRST
        # ====================================================================
        # EnergyCollector stop — flushes all adapters (16B3)
        # NormalizedWriter and LegacyWriter flush() called inside stop()
        if self._energy_collector is not None:
            self._energy_collector.stop()
            # Collect buffered v2 samples — inserted after insert_run() in experiment_runner
            self.last_v2_samples = list(self._energy_collector._flushed_v2_samples)
            self.last_legacy_samples = list(self._energy_collector._flushed_legacy_samples)
            self._energy_collector = None
        samples = []   # legacy var kept — downstream code checks len(samples)

        interrupt_samples = []
        if (
            hasattr(self, "collect_interrupt_samples")
            and self.collect_interrupt_samples
        ):
            interrupt_samples = self.scheduler.stop_interrupt_sampling()
            logger.debug(f"Collected {len(interrupt_samples)} interrupt samples")
            io_samples        = list(self._io_samples)
            self._io_samples  = []


        # ====================================================================
        # Store samples in instance for later access by harness
        # ====================================================================
        self.last_interrupt_samples = interrupt_samples
        self.last_io_samples        = io_samples if 'io_samples' in locals() else []
        self.last_samples = samples
        # Stop GPU collector and store samples for harness access
        # Returns empty list if NoneBackend or no samples collected
        self.last_gpu_samples = self.gpu_collector.stop()
        # SPBMSampler retired (16B3) — EnergyCollector handles GN100 now
        self.last_spbm_samples = []
        self.last_rail_result = (
            self.power_rail_sampler.stop() if self.power_rail_sampler else None
        )        
        logger.debug("stop_measurement: %d gpu_samples collected",
                     len(self.last_gpu_samples))
        # Optional: separate by type if samples have type field
        # Optional: separate by type if samples have type field
        self.last_energy_samples = []       
        self.last_cpu_samples = []

        # Try to categorize samples if they have a 'type' field
        # If we need to categorize, we need to know the tuple structure
        # For example, if samples are (timestamp, type, value) tuples
        for sample in samples:
            # Chunk 2: samples are now dicts (not tuples)
            if isinstance(sample, dict):
                self.last_energy_samples.append(sample)
            elif isinstance(sample, (tuple, list)) and len(sample) >= 2:
                # backward compat — old tuple format (timestamp, energy_dict)
                self.last_energy_samples.append(sample)
                # Add more logic based on actual formatif hasattr(self.energy_engine, 'samples'):
        # Stop side-sampler — no more IO/interrupt samples after this point
        self._side_sampling_active = False
        if hasattr(self, "_side_sampling_thread") and self._side_sampling_thread:
            self._side_sampling_thread.join(timeout=2.0)
        # Stop perf and get accumulated counters

        perf_data = self.perf.stop_process_measurement() if self._platform_caps.has_perf else {}
 
        # Stop turbostat and get continuous data
        _has_freq_reader = (
            self._platform_caps.has_turbostat or
            (self._platform_caps.arch == "aarch64" and self._platform_caps.has_arm_pmu)
        )
        turbostat_data = self.turbostat.stop_monitoring() if _has_freq_reader else {"dataframe": None, "num_samples": 0, "duration_seconds": 0.0, "summary": {}}
        thermal_samples = self._stop_thermal_sampling()
        # ====================================================================
        # STEP 2: Capture snapshot readers END values
        # ====================================================================
        rapl_end = self.rapl.read_energy()
        # GPU PP1 end counter — paired with start captured in start_measurement()
        gpu_end_uj  = ReaderFactory.get_gpu_energy_uj(self.rapl)
        scheduler_end = self.scheduler.read_all()

        # ====================================================================
        # STEP 3: Capture MSR thermal snapshot at END (BEFORE timestamp)
        # ====================================================================
        msr_thermal_end = None
        msr_available = (
            hasattr(self.msr, "helper_available") and self.msr.helper_available
        ) or self.msr.rdmsr_available
        if hasattr(self, "msr") and msr_available:
            try:
                msr_thermal_end = self.msr.snapshot_thermal_state()
                print(f"\n🔥 THERMAL SNAPSHOT - END:")
                print(f"   Package: {msr_thermal_end['package']}")
                print(f"   Core: {msr_thermal_end['core']}")
                logger.debug(f"MSR thermal end: {msr_thermal_end}")
            except Exception as e:
                print(f"❌ Failed to capture end MSR thermal: {e}")
                logger.warning(f"Could not capture end MSR thermal: {e}")

        # ====================================================================
        # Calculate C-state deltas (per-run, not cumulative)
        # ====================================================================
        cstate_deltas = {}
        msr_metrics = {}
        if (
            hasattr(self, "msr")
            and hasattr(self.msr, "_cstate_start")
            and self.msr._cstate_start
        ):
            try:
                self.msr._cstate_end = self.msr.snapshot_cstate_counters()

                for state in ["c2", "c3", "c6", "c7"]:
                    start_val = self.msr._cstate_start.get(state, 0)
                    end_val = self.msr._cstate_end.get(state, 0)
                    delta = max(0, end_val - start_val)
                    cstate_deltas[f"{state}_time_seconds"] = delta

                logger.debug(f"C-state deltas: {cstate_deltas}")

                # Add to msr_metrics
                msr_metrics["cstate_deltas"] = cstate_deltas

            except Exception as e:
                logger.warning(f"Failed to calculate C-state deltas: {e}")

        # Set end time IMMEDIATELY after thermal snapshot
        self.end_time = time.time()
        duration_seconds = self.end_time - self.start_time

        # Capture sensor temps AFTER timestamp (less timing-critical)
        sensor_end = self.sensor.read_temperatures()

        # ====================================================================
        # STEP 3: Compute deltas for snapshot readers
        # ====================================================================
        start_rapl = self.start_readings.get("rapl", {})

        # Scheduler delta
        scheduler_delta = {}
        start_sched = self.start_readings.get("scheduler", {})
        for key in scheduler_end:
            if key in start_sched:
                if isinstance(scheduler_end[key], (int, float)) and isinstance(
                    start_sched[key], (int, float)
                ):
                    scheduler_delta[key] = scheduler_end[key] - start_sched[key]
                else:
                    scheduler_delta[key] = scheduler_end[key]
            else:
                scheduler_delta[key] = scheduler_end[key]
                # ADD THIS DEBUG
        print(f"🔍 DEBUG scheduler_delta keys: {list(scheduler_delta.keys())}")
        print(
            f"🔍 DEBUG run queue value: {scheduler_delta.get('runnable', 'NOT FOUND')}"
        )

        # ====================================================================
        # STEP 4: Calculate actual sampling rate
        # ====================================================================
        actual_sampling_rate = (
            len(samples) / duration_seconds if duration_seconds > 0 else 0
        )

        # ====================================================================
        # STEP 5: Validate perf data
        # ====================================================================
        if hasattr(perf_data, "duration_seconds") and perf_data.duration_seconds <= 0:
            logger.warning(f"perf duration invalid: {perf_data.duration_seconds}s")

        # ====================================================================
        # Capture MSR metrics and calculate C-state deltas
        # ====================================================================
        msr_metrics = {}
        msr_available = (
            hasattr(self.msr, "helper_available") and self.msr.helper_available
        ) or self.msr.rdmsr_available

        if hasattr(self, "msr") and msr_available:
            try:
                # Get base MSR metrics (ring bus, thermal, etc.)
                msr_metrics = self.msr.get_all_metrics()

                # ========== NEW: Calculate C-state deltas if start exists ==========
                if hasattr(self.msr, "_cstate_start") and self.msr._cstate_start:
                    # Capture end snapshot
                    self.msr._cstate_end = self.msr.snapshot_cstate_counters()

                    start_counters = self.msr._cstate_start.get("counters", {})
                    end_counters = self.msr._cstate_end.get("counters", {})

                    cstate_deltas = {}
                    for state in ["c2", "c3", "c6", "c7"]:
                        start_val = start_counters.get(state, 0)
                        end_val = end_counters.get(state, 0)
                        delta_raw = max(0, end_val - start_val)

                        # Convert to seconds using TSC frequency
                        if (
                            hasattr(self.msr, "tsc_frequency_hz")
                            and self.msr.tsc_frequency_hz
                        ):
                            delta_sec = delta_raw / self.msr.tsc_frequency_hz
                        else:
                            delta_sec = delta_raw / 2.8e9  # Fallback

                        # Add directly to msr_metrics top level (for DB)
                        msr_metrics[f"{state}_time_seconds"] = delta_sec
                        cstate_deltas[f"{state}_delta_raw"] = delta_raw

                    msr_metrics["cstate_deltas"] = cstate_deltas
                    logger.debug(
                        f"C-state deltas (sec): c2={msr_metrics.get('c2_time_seconds', 0):.3f}"
                    )

                # Debug prints
                print(f"🟢 ENGINE_ID: {id(msr_metrics)}")
                print(
                    f"🟢 ENGINE_VALUE: c2={msr_metrics.get('c2_time_seconds', 0):.3f}s"
                )
                print(f"🟢 ENGINE_KEYS: {list(msr_metrics.keys())}")

            except Exception as e:
                logger.warning(f"MSR measurement failed: {e}")

        # Set end time and duration AFTER all readings are done
        self.end_time = time.time()
        duration_seconds = self.end_time - self.start_time

        # ====================================================================
        # STEP 7: Calculate derived thermal metrics (BEFORE building measurement)
        # ====================================================================
        thermal_start = self.start_readings.get("msr_thermal")
        thermal_end = msr_thermal_end

        thermal_during_experiment = 0
        thermal_now_active = 0
        thermal_since_boot = 0

        if thermal_start and thermal_end:
            # Get package and core log bits
            start_pkg_log = thermal_start["package"].get("thermal_log", 0)
            start_core_log = thermal_start["core"].get("thermal_log", 0)
            end_pkg_log = thermal_end["package"].get("thermal_log", 0)
            end_core_log = thermal_end["core"].get("thermal_log", 0)

            # Get current throttling state at end
            end_pkg_now = thermal_end["package"].get("thermal_now", 0)
            end_core_now = thermal_end["core"].get("thermal_now", 0)

            # Combined OR logic
            start_combined_log = 1 if (start_pkg_log == 1 or start_core_log == 1) else 0
            end_combined_log = 1 if (end_pkg_log == 1 or end_core_log == 1) else 0

            # Did throttling occur DURING experiment?
            thermal_during_experiment = (
                1 if end_combined_log > start_combined_log else 0
            )

            # Is system throttling NOW at end?
            thermal_now_active = 1 if (end_pkg_now == 1 or end_core_now == 1) else 0

            # Has system ever throttled since boot?
            thermal_since_boot = end_combined_log

        # Print derived metrics for verification (temporary)
        print(f"\n🔥 THERMAL DERIVED:")
        print(f"   during_experiment: {thermal_during_experiment}")
        print(f"   now_active: {thermal_now_active}")
        print(f"   since_boot: {thermal_since_boot}")

        # ====================================================================
        # STEP 8: Build raw measurement object
        # ====================================================================
        measurement = RawEnergyMeasurement(
            measurement_id=self.measurement_id,
            start_time=self.start_time,
            end_time=self.end_time,
            duration_seconds=duration_seconds,
            # RAPL (snapshot)
            rapl_start_uj=start_rapl,
            rapl_end_uj=rapl_end,
            # perf (continuous) - store object directly
            perf=perf_data,
            # turbostat (continuous) - store the full data dictionary
            turbostat=turbostat_data,
            # thermal (sensor)
            thermal=(
                sensor_end.to_dict() if hasattr(sensor_end, "to_dict") else sensor_end
            ),
            thermal_samples=thermal_samples,
            # Swap Start and end fileds
            scheduler_start=self.scheduler_start,
            scheduler_end=scheduler_end,
            # scheduler (snapshot with delta)
            scheduler_metrics=scheduler_delta,
            # High-frequency samples
            samples=samples,
            io_samples=self.last_io_samples,
            # Actual sampling rate
            sampling_rate_hz=actual_sampling_rate,
            # MSR metrics
            msr_metrics=msr_metrics,
            # NEW: Pass derived thermal values
            thermal_during_experiment=thermal_during_experiment,
            thermal_now_active=thermal_now_active,
            thermal_since_boot=thermal_since_boot,
            # GPU PP1 total energy for this run — None on non-Tiger-Lake platforms
            gpu_total_uj=self._compute_gpu_total(
                self.start_readings.get("gpu_uj"), gpu_end_uj
            ),
            # Metadata with thermal calculations
            # Metadata with thermal calculations
            metadata={
                "hostname": platform.node(),
                "python_version": sys.version.split()[0],
                "cpu_affinity": list(os.sched_getaffinity(0)),
                "pinned_cores": self.pinned_cores,
                "turbostat_version": self.turbostat.turbostat_version if self._platform_caps.has_turbostat else None,
                "cpu_topology": self.turbostat.cpu_topology if self._platform_caps.has_turbostat else {},
                # Raw thermal snapshots
                "thermal_start": thermal_start,
                "thermal_end": thermal_end,
                # Derived thermal metrics
                "thermal_during_experiment": thermal_during_experiment,
                "thermal_now_active": thermal_now_active,
                "thermal_since_boot": thermal_since_boot,
            },
        )

        # Add baseline info if available
        if self.idle_baseline:
            measurement.metadata["baseline_available"] = True
            measurement.metadata["baseline_power_watts"] = self.idle_baseline

        self.measurement = measurement
        self.measurement_id = None
        self.print_summary(measurement)
        return measurement

    def print_summary(self, measurement: RawEnergyMeasurement):
        """
        Print a comprehensive summary of all collected data.
        """
        print("\n" + "=" * 70)
        print("📊 ENERGY ENGINE COMPLETE SUMMARY")
        print("=" * 70)

        # 1. Timing
        print(f"\n⏱️  Duration: {measurement.duration_seconds:.3f}s")
        print(
            f"   Start: {measurement.start_time:.3f}, End: {measurement.end_time:.3f}"
        )

        # 2. RAPL Energy (snapshot deltas)
        rapl_start = measurement.rapl_start_uj
        rapl_end = measurement.rapl_end_uj
        print("\n⚡ RAPL Energy (µJ):")
        for domain in set(rapl_start.keys()) | set(rapl_end.keys()):
            start_val = rapl_start.get(domain, 0)
            end_val = rapl_end.get(domain, 0)
            delta = end_val - start_val
            print(f"   {domain}: {delta:>12} µJ ({delta/1e6:.6f} J)")

        # 3. perf counters – using correct attribute names
        if measurement.perf:
            perf = measurement.perf
            print("\n📈 Performance Counters:")
            # Instructions
            if hasattr(perf, "instructions_retired"):
                print(f"   Instructions: {perf.instructions_retired:,}")
            # Cycles
            if hasattr(perf, "cpu_cycles"):
                print(f"   Cycles:       {perf.cpu_cycles:,}")
            # IPC (method)
            if hasattr(perf, "instructions_per_cycle"):
                print(f"   IPC:          {perf.instructions_per_cycle():.2f}")
            # Cache
            if hasattr(perf, "cache_references"):
                print(f"   Cache Refs:   {perf.cache_references:,}")
            if hasattr(perf, "cache_misses"):
                print(f"   Cache Misses: {perf.cache_misses:,}")
                if perf.cache_references:
                    miss_rate = perf.cache_misses / perf.cache_references
                    print(f"   Miss Rate:    {miss_rate:.2%}")
            # Page faults
            major = getattr(perf, "major_page_faults", 0)
            minor = getattr(perf, "minor_page_faults", 0)
            if major or minor:
                print(f"   Page Faults:  {major+minor} (major={major}, minor={minor})")
            # Context switches
            vol = getattr(perf, "context_switches_voluntary", 0)
            invol = getattr(perf, "context_switches_involuntary", 0)
            if vol or invol:
                print(f"   Ctx Switches: vol={vol}, invol={invol}")
            # Thread migrations
            if hasattr(perf, "thread_migrations"):
                print(f"   Migrations:   {perf.thread_migrations:,}")

        # 4. Turbostat continuous data
        if measurement.turbostat and measurement.turbostat.get("dataframe") is not None:
            df = measurement.turbostat["dataframe"]
            summary = measurement.turbostat.get("summary", {})
            print(
                "\n🌡️ Turbostat Summary (over {:.2f}s, {} samples):".format(
                    measurement.turbostat.get("duration_seconds", 0),
                    measurement.turbostat.get("num_samples", 0),
                )
            )
            # C‑states
            cstates = [k for k in summary if k.endswith("_mean") and k.startswith("C")]
            if cstates:
                print("   C‑state residencies (%):")
                for c in sorted(cstates):
                    print(f"      {c}: {summary[c]:.2f}")
            # Frequency
            if "frequency_mean" in summary:
                print(
                    f"   Frequency (MHz): mean={summary['frequency_mean']:.0f}, "
                    f"min={summary.get('frequency_min', 0):.0f}, "
                    f"max={summary.get('frequency_max', 0):.0f}, "
                    f"std={summary.get('frequency_stddev', 0):.2f}"
                )
            # Temperature
            if "package_temp_mean" in summary:
                print(f"   Package Temp (°C): mean={summary['package_temp_mean']:.1f}")
            # Print first few turbostat samples
            if len(df) > 0:
                print("\n   First 3 turbostat samples:")
                for i in range(min(3, len(df))):
                    row = df.iloc[i].to_dict()
                    print(f"      Sample {i+1}: {row}")

        # 5. MSR metrics
        if measurement.msr_metrics:
            msr = measurement.msr_metrics
            print("\n🔧 MSR Metrics:")
            ring_bus = msr.get("ring_bus", {})
            if ring_bus:
                print(
                    f"   Ring Bus Frequency: {ring_bus.get('current_mhz', 0):.1f} MHz"
                )
            if "wakeup_latency_us" in msr:
                print(f"   Wake‑up Latency: {msr['wakeup_latency_us']:.2f} µs")
            if "thermal_throttle" in msr:
                print(f"   Thermal Throttle Flag: {msr['thermal_throttle']}")

        # 6. Scheduler metrics
        if measurement.scheduler_metrics:
            sched = measurement.scheduler_metrics
            print("\n🔄 Scheduler Metrics:")
            print(f"   Voluntary Ctx Sw:   {sched.get('voluntary_switches', 0)}")
            print(f"   Involuntary Ctx Sw: {sched.get('involuntary_switches', 0)}")
            print(f"   Thread Migrations:  {sched.get('thread_migrations', 0)}")
            print(f"   Run Queue Length:    {sched.get('runnable', 0):.2f}")
            print(f"   Kernel Time:         {sched.get('system_time', 0):.2f} ms")
            print(f"   User Time:           {sched.get('user_time', 0):.2f} ms")

        # 7. High‑frequency samples
        if measurement.samples:
            print(f"\n📊 High‑Frequency Samples: {len(measurement.samples)} collected")
            if len(measurement.samples) > 0:
                print("   First sample:", measurement.samples[0])

        print("\n" + "=" * 70)

    # ------------------------------------------------------------------------
    # Context manager interface
    # ------------------------------------------------------------------------
    def __enter__(self):
        """Enter context: start measurement."""
        self.start_measurement()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context: stop measurement and store result in self.measurement."""
        self.measurement = self.stop_measurement()

    # ------------------------------------------------------------------------
    # Multiple‑run convenience
    # ------------------------------------------------------------------------
    def run_multiple(
        self,
        func: Callable,
        args: tuple = (),
        kwargs: dict = None,
        iterations: int = 10,
        cool_down: Optional[int] = None,
        output_file: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run a function multiple times, measuring each run and collecting statistics.

        Args:
            func: The function to run (should contain the AI workload).
            args: Positional arguments for the function.
            kwargs: Keyword arguments for the function.
            iterations: Number of runs.
            cool_down: Seconds to wait between runs (default from config).
            output_file: Optional JSON file to save results.

        Returns:
            A dictionary containing:
                - 'all_runs': list of RawEnergyMeasurement objects
                - 'summary': statistical summary of key metrics
                - 'metadata': run parameters

        Req 3.4: Automated 10‑run iteration.
        """
        if kwargs is None:
            kwargs = {}
        if cool_down is None:
            cool_down = self.cool_down_seconds

        dprint(f"Running {iterations} iterations with {cool_down}s cool‑down")

        results = []
        for i in range(iterations):
            dprint(f"Run {i+1}/{iterations}")
            with self as engine:
                result = func(*args, **kwargs)
            results.append(self.measurement)

            if i < iterations - 1:
                time.sleep(cool_down)

        # Compute summary statistics
        summaries = {}
        metrics = [
            ("package_energy_uj", "µJ"),
            ("core_energy_uj", "µJ"),
            ("duration_seconds", "s"),
        ]

        for metric, unit in metrics:
            values = []
            for m in results:
                if m is not None:
                    if metric == "package_energy_uj":
                        values.append(m.package_energy_uj)
                    elif metric == "core_energy_uj":
                        values.append(m.core_energy_uj)
                    elif metric == "duration_seconds":
                        values.append(m.duration_seconds)

            if values:
                summaries[metric] = {
                    "mean": statistics.mean(values),
                    "median": statistics.median(values),
                    "stdev": statistics.stdev(values) if len(values) > 1 else 0,
                    "min": min(values),
                    "max": max(values),
                    "unit": unit,
                }

        output = {
            "metadata": {
                "iterations": iterations,
                "cool_down_seconds": cool_down,
                "function": func.__name__,
                "baseline_available": self.idle_baseline is not None,
            },
            "all_runs": [m.to_dict() if m else {} for m in results if m is not None],
            "summary": summaries,
        }

        if output_file:
            with open(output_file, "w") as f:
                json.dump(output, f, indent=2, default=str)
            dprint(f"Saved results to {output_file}")

        return output

    def __str__(self) -> str:
        """String representation of the energy engine."""
        readers = []
        if self.rapl:
            readers.append("rapl")
        if self.perf.perf_available:
            readers.append("perf")
        if self._platform_caps.has_turbostat:
            readers.append("turbostat")
        if self.sensor.available_sensors:
            readers.append("sensor")
        if self.msr.rdmsr_available:
            readers.append("msr")

        return f"EnergyEngine(readers={', '.join(readers)})"


# ============================================================================
# Example usage (standalone test)
# ============================================================================
if __name__ == "__main__":
    import json

    from core.config_loader import ConfigLoader

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    print("\n" + "=" * 70)
    print("ENERGY ENGINE TEST – RAW MEASUREMENTS ONLY")
    print("=" * 70)

    # Load configuration from Module 0
    config_loader = ConfigLoader()
    config = config_loader.get_hardware_config()  # hw_config.json

    # Merge with app settings
    settings = config_loader.get_settings()

    # Handle settings (could be dict or object from config_loader)
    if hasattr(settings, "__dict__"):
        config["settings"] = settings.__dict__
    else:
        config["settings"] = settings

    # Create engine
    engine = EnergyEngine(config)
    print(f"📊 {engine}")

    # Measure idle baseline (optional – stored as metadata)
    print("\n📝 Measuring idle baseline (2 samples of 2s each for quick test)...")
    baseline = engine.measure_idle_baseline(
        duration_seconds=2, num_samples=2, pre_wait_seconds=2
    )
    print(f"Idle baseline: {baseline} W")
    print(f"   (This baseline is stored as metadata, NOT applied to raw data)")

    # Simple workload for testing
    def dummy_workload():
        """A dummy workload that just sleeps."""
        time.sleep(1)
        return "done"

    # Single measurement – returns RAW data only
    print("\n📝 Running single measurement (RAW data)...")
    with engine as m:
        result = dummy_workload()

    print(f"Result: {result}")
    print(f"Raw package energy: {engine.measurement.package_energy_uj / 1e6:.4f} J")
    print(f"Raw core energy: {engine.measurement.core_energy_uj / 1e6:.4f} J")

    if engine.measurement.metadata.get("baseline_available"):
        print(
            f"Baseline available: {engine.measurement.metadata['baseline_power_watts']} W"
        )
        print(f"   (Use EnergyAnalyzer to compute corrected values)")

    # Multiple runs
    print("\n📝 Running 3 iterations with 2 second cool-down...")
    stats = engine.run_multiple(dummy_workload, iterations=3, cool_down=2)

    print("\n📊 Summary Statistics (RAW values):")
    for metric, values in stats["summary"].items():
        print(
            f"   {metric}: mean={values['mean']:.2f} {values['unit']}, "
            f"stdev={values['stdev']:.2f}"
        )

    print("\n" + "=" * 70)
    print("✅ Test complete – Raw measurements only, baseline stored separately!")
    print("=" * 70)
