#!/usr/bin/env python3
"""
================================================================================
IDLE BASELINE MEASUREMENT UTILITY
================================================================================

Research-grade idle power measurement with platform-agnostic reader dispatch,
normalized domain storage, and machine-aware cache path resolution.

Architecture:
    BASELINE_DOMAIN_MAP is the single source of truth for raw-key -> canonical
    domain name mapping. It lives here and nowhere else. All other modules
    consume this map; none define their own mappings (BDC-2).

    Raw platform keys (pkg, cpu_p, package-0) exist ONLY inside
    measure_idle_baseline() during the sampling loop. They never leave
    this module in raw form. BaselineMeasurement.power_watts always
    uses canonical uppercase energy_domains.name values (BDC-6).

    Every domain returned by read_energy() is stored. No threshold
    filtering, no sign filtering, no silent drops (BDC-7).

Author: Deepak Panigrahy
================================================================================
"""

import sys
from pathlib import Path

# Project root resolution — must happen before any local imports
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import json
import logging
import os
import socket
import statistics
import time
from typing import Any, Dict, List, Optional

import psutil

from core.models.baseline_measurement import BaselineMeasurement
from core.readers.gpu_collector import GPUCollector
from core.readers.interfaces import EnergyReaderABC       # PAC-2: ABC only, never RAPLReader
from core.readers.scheduler_monitor import SchedulerMonitor
from core.utils.core_pinner import CorePinner
from core.utils.debug import dprint

logger = logging.getLogger(__name__)

# =============================================================================
# BASELINE_DOMAIN_MAP — single source of truth (BDC-2)
# =============================================================================
# Format: raw_reader_key -> (canonical_name, legacy_idle_baselines_col, legacy_std_col)
#
# canonical_name MUST match energy_domains.name exactly (uppercase).
# legacy_* is None for domains with no fixed column in idle_baselines.
# This map is the ONLY place in A-LEMS that translates raw keys to canonical names.
# _verify_domain_map_integrity() cross-checks this against the live DB at startup.
#
# How to add a new platform reader:
#   1. Add its raw keys here with correct canonical_name and legacy columns.
#   2. Run _verify_domain_map_integrity() — it will tell you if canonical_name
#      is missing from energy_domains table (add via seed if so).
#   3. No other file needs to change for the mapping to take effect.

BASELINE_DOMAIN_MAP = {
    # ---- RAPL keys (UBUNTU2505, Intel x86) -----------------------------------
    'package-0': ('PACKAGE', 'package_power_watts', 'package_std'),
    'core':      ('CORE',    'core_power_watts',    'core_std'),
    'dram':      ('DRAM',    'dram_power_watts',    'dram_std'),
    'uncore':    ('UNCORE',  'uncore_power_watts',  'uncore_std'),
    # ---- SPBM keys (GN100, NVIDIA Grace aarch64) ----------------------------
    'pkg':       ('PACKAGE', 'package_power_watts', 'package_std'),
    'cpu_p':     ('CPU_P',   'core_power_watts',    'core_std'),
    'cpu_e':     ('CPU_E',   None,                  None),       # no legacy column
    'gpu':       ('GPU',     'gpu_power_watts',     'gpu_std'),
    'gpu_dcgm':  ('GPU_DCGM', 'gpu_dcgm_power_watts', 'gpu_dcgm_std'),
    # ---- Apple IOKit keys (Stephen M1) — Chunk 16F --------------------------
    'cpu':       ('CORE',    'core_power_watts',    'core_std'),
    'gpu_apple': ('GPU_APPLE', None,                None),
    # ---- AMD keys (Alex Ryzen) — Chunk 16E ----------------------------------
    'ccd0':      ('CCD0',    None,                  None),
    'ccd1':      ('CCD1',    None,                  None),
    'package':   ('PACKAGE', 'package_power_watts', 'package_std'),
}

# =============================================================================
# Machine-aware cache path resolution
# =============================================================================

def get_baseline_cache_path():
    # type: () -> str
    """
    Resolve idle_baseline.json path for this machine.

    Same 3-layer resolution as get_alems_db_path() — same pattern, same rules.

    Priority:
      Layer 1: ALEMS_DATA_ROOT env var + hostname
               -> $ALEMS_DATA_ROOT/$hostname/idle_baseline.json
      Layer 2: app_settings.yaml baseline.cache_file (relative path)
      Layer 3: hardcoded fallback -> data/idle_baseline.json

    Returns:
        Absolute or relative path string for the cache JSON file.
    """
    # Source ~/.alemsrc if not already done — Ab Initio pattern
    alemsrc = os.path.expanduser("~/.alemsrc")
    if os.path.exists(alemsrc):
        with open(alemsrc) as f:
            for line in f:
                line = line.strip()
                if line.startswith("export "):
                    key, _, val = line[7:].partition("=")
                    os.environ.setdefault(key.strip(), val.strip())

    base = os.environ.get("ALEMS_DATA_ROOT")
    if base:
        # Layer 1: machine-specific directory alongside experiments.db
        machine_id = socket.gethostname().lower()
        return os.path.join(base, machine_id, "idle_baseline.json")

    # Layer 2: read from app_settings.yaml
    try:
        import yaml
        settings_path = project_root / "config" / "app_settings.yaml"
        if settings_path.exists():
            with open(settings_path) as f:
                settings = yaml.safe_load(f) or {}
            cache_file = (settings
                          .get("experiment", {})
                          .get("baseline", {})
                          .get("cache_file", ""))
            if cache_file:
                return str(project_root / cache_file)
    except Exception as e:
        logger.debug("get_baseline_cache_path: yaml read failed: %s", e)

    # Layer 3: hardcoded fallback
    return str(project_root / "data" / "idle_baseline.json")


# Module-level default resolved once at import time
DEFAULT_CACHE_FILE = Path(get_baseline_cache_path())

# =============================================================================
# Domain integrity verification (BDC-8)
# =============================================================================

class DomainMapIntegrityError(RuntimeError):
    """Raised at startup when BASELINE_DOMAIN_MAP does not match energy_domains."""
    pass


def _verify_domain_map_integrity(db_conn, domain_map=None):
    # type: (Any, Optional[Dict]) -> None
    """
    Cross-check BASELINE_DOMAIN_MAP against live energy_domains table.

    Called once from EnergyEngine.__init__(). Fails loud before any
    measurement runs. Never called during sampling loop (BDC-8).

    Checks:
      1. Every canonical_name in domain_map exists in energy_domains.
      2. No duplicate raw_keys in domain_map.
      3. Every legacy_column (non-None) exists as a real column in idle_baselines.
      4. v62 reader_keys column (if present) matches domain_map — WARNING only.

    Args:
        db_conn:    sqlite3 connection to the experiments DB.
        domain_map: Defaults to BASELINE_DOMAIN_MAP if None.

    Raises:
        DomainMapIntegrityError: If any hard check fails.
    """
    if domain_map is None:
        domain_map = BASELINE_DOMAIN_MAP

    errors   = []
    warnings = []

    # Build canonical name set from DB
    try:
        cur = db_conn.execute("SELECT name FROM energy_domains")
        db_canonical = {row[0] for row in cur.fetchall()}
    except Exception as e:
        raise DomainMapIntegrityError(
            "Cannot query energy_domains: %s — run setup_new_machine.sh first" % e
        )

    # Check 1: every canonical_name exists in DB
    code_canonical = {v[0] for v in domain_map.values()}
    missing = code_canonical - db_canonical
    if missing:
        errors.append(
            "Canonical names in BASELINE_DOMAIN_MAP missing from energy_domains: %s"
            % sorted(missing)
        )

    # Check 2: no duplicate raw_keys
    raw_keys = list(domain_map.keys())
    if len(raw_keys) != len(set(raw_keys)):
        errors.append("Duplicate raw_keys detected in BASELINE_DOMAIN_MAP")

    # Check 3: legacy_column values exist in idle_baselines DDL
    idle_cols = set()
    try:
        cur = db_conn.execute("PRAGMA table_info(idle_baselines)")
        idle_cols = {row[1] for row in cur.fetchall()}
    except Exception as e:
        warnings.append("Cannot verify idle_baselines columns: %s" % e)

    if idle_cols:
        for raw_key, (canonical, legacy_col, legacy_std) in domain_map.items():
            if legacy_col and legacy_col not in idle_cols:
                errors.append(
                    "raw_key '%s' -> legacy_col '%s' not found in idle_baselines"
                    % (raw_key, legacy_col)
                )
            if legacy_std and legacy_std not in idle_cols:
                errors.append(
                    "raw_key '%s' -> legacy_std '%s' not found in idle_baselines"
                    % (raw_key, legacy_std)
                )

    # Check 4: v62 reader_keys consistency — WARNING only (v62 is documentation)
    try:
        cur = db_conn.execute(
            "SELECT name, reader_keys FROM energy_domains WHERE reader_keys IS NOT NULL"
        )
        for row in cur.fetchall():
            db_name, db_keys_str = row[0], row[1]
            db_keys = set(k.strip() for k in db_keys_str.split(','))
            # find raw_keys in domain_map that map to this canonical name
            code_keys = {k for k, v in domain_map.items() if v[0] == db_name}
            orphan_in_db   = db_keys - code_keys
            orphan_in_code = code_keys - db_keys
            if orphan_in_db:
                warnings.append(
                    "energy_domains.reader_keys has '%s' for %s but BASELINE_DOMAIN_MAP does not"
                    % (orphan_in_db, db_name)
                )
            if orphan_in_code:
                warnings.append(
                    "BASELINE_DOMAIN_MAP has raw_keys %s for %s but energy_domains.reader_keys does not (run v62)"
                    % (orphan_in_code, db_name)
                )
    except Exception:
        # v62 not yet applied on this machine — silently skip
        pass

    for w in warnings:
        logger.warning("DomainMap: %s", w)

    if errors:
        raise DomainMapIntegrityError(
            "BASELINE_DOMAIN_MAP integrity check failed:\n" + "\n".join(errors)
        )

    logger.info(
        "Domain map integrity verified: %d raw_keys, %d canonical domains",
        len(domain_map), len(code_canonical),
    )


# =============================================================================
# System state capture
# =============================================================================

def get_system_state():
    # type: () -> Dict[str, Any]
    """
    Capture current system state for baseline reproducibility metadata.

    Returns:
        Dict with governor, turbo, processes, background_cpu.
        All fields have safe fallback values — never raises.
    """
    state = {}  # type: Dict[str, Any]

    # CPU frequency governor — affects idle power significantly
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor") as f:
            state["governor"] = f.read().strip()
    except Exception:
        state["governor"] = "unknown"

    # Intel turbo boost status (x86 only — ARM has no equivalent path)
    try:
        with open("/sys/devices/system/cpu/intel_pstate/no_turbo") as f:
            state["turbo"] = "disabled" if f.read().strip() == "1" else "enabled"
    except Exception:
        state["turbo"] = "unknown"   # ARM, AMD, or non-pstate — not an error

    # Background process and CPU load — noise indicators for baseline validity
    state["processes"] = len(psutil.pids())
    state["background_cpu"] = psutil.cpu_percent(interval=1)

    return state


# =============================================================================
# Core measurement function
# =============================================================================

def measure_idle_baseline(
    energy_reader,                       # type: EnergyReaderABC
    core_pinner,                         # type: CorePinner
    duration_seconds=10,                 # type: int
    num_samples=10,                      # type: int
    pre_wait_seconds=10,                 # type: int
    pin_cores=None,                      # type: Optional[List[int]]
    cache_file=None,                     # type: Optional[Path]
    force_remeasure=False,               # type: bool
    measure_gpu=True,                    # type: bool
):
    # type: (...) -> BaselineMeasurement
    """
    Measure system idle energy baseline using research-grade methodology.

    Platform-agnostic: energy_reader is any EnergyReaderABC — RAPLReader on
    x86, SPBMEnergyReader on GN100, IOKitCPUEnergyReader on Apple M1.
    The factory in energy_engine.py selects the correct reader before calling here.

    Key design decisions:
      - read_energy() is called (not read_energy_uj()) to get ALL platform domains.
        BDC-7: nothing is filtered. Every domain the reader returns is stored.
      - Raw keys (pkg, package-0) are converted to canonical uppercase names
        via BASELINE_DOMAIN_MAP before BaselineMeasurement is constructed.
        The returned object always has canonical keys — never raw platform keys.
      - measure_gpu=False disables the optional separate GPU collector call only.
        It never suppresses domains already returned by read_energy().
      - Cache validation checks governor + turbo — same system state required
        for cache hit. ALEMS_DATA_ROOT machines use machine-specific cache path.

    Args:
        energy_reader:    Platform reader from ReaderFactory.get_energy_reader().
        core_pinner:      CorePinner for CPU affinity during measurement.
        duration_seconds: Duration of each idle sample in seconds.
        num_samples:      Number of samples to average over.
        pre_wait_seconds: Wait time before sampling for system to reach deep idle.
        pin_cores:        Specific cores to pin to (None = pinner default).
        cache_file:       Override cache path (None = DEFAULT_CACHE_FILE).
        force_remeasure:  If True, ignore existing cache and remeasure.
        measure_gpu:      If True, call energy_reader.read_gpu_msr() for separate
                          GPU energy accumulator reading alongside read_energy().
                          Does NOT affect whether gpu domain from read_energy() is stored.

    Returns:
        BaselineMeasurement with canonical uppercase keys in power_watts.
    """
    # Resolve cache path — machine-aware
    if cache_file is None:
        cache_file = DEFAULT_CACHE_FILE
    cache_file = Path(cache_file)
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    current_state = get_system_state()
    dprint(
        "System state: governor=%s turbo=%s processes=%d background_cpu=%.1f%%",
        current_state["governor"], current_state["turbo"],
        current_state["processes"], current_state["background_cpu"],
    )

    # ------------------------------------------------------------------
    # Cache load — skip if force_remeasure or state mismatch
    # ------------------------------------------------------------------
    if not force_remeasure and cache_file.exists():
        try:
            with open(cache_file) as f:
                cache_data = json.load(f)
            cached_meta = cache_data.get("metadata", {})
            # Governor and turbo must match — these change idle power significantly.
            # GPU measurement state must also match: if GPU is being requested
            # now (measure_gpu=True) but the cached baseline predates GPU_DCGM,
            # or came from a run where the backend wasn't available, the cache
            # would otherwise look valid forever and silently never pick up
            # real GPU baseline data.
            gpu_state_ok = (
                not measure_gpu
                or cached_meta.get("measured_gpu_dcgm") is True
            )
            if (cached_meta.get("governor") == current_state["governor"]
                    and cached_meta.get("turbo") == current_state["turbo"]
                    and gpu_state_ok):
                dprint("Loaded idle baseline from cache: %s", cache_file)
                return BaselineMeasurement.from_dict(cache_data)
            else:
                dprint("Cache invalid (system state changed or GPU measurement state mismatch) — remeasuring")
        except Exception as e:
            logger.warning("Failed to load baseline cache, remeasuring: %s", e)

    dprint(
        "Measuring idle baseline: %d samples x %ds each",
        num_samples, duration_seconds,
    )

    # ------------------------------------------------------------------
    # Step 1: Pin to dedicated cores (Req 1.15)
    # ------------------------------------------------------------------
    if pin_cores is not None:
        core_pinner.pin_to_cores(pin_cores)
        dprint("Pinned to cores: %s", pin_cores)
    else:
        core_pinner.pin_to_cores()
        dprint("Pinned to default cores: %s", core_pinner.default_cores)

    # ------------------------------------------------------------------
    # Step 2: Pre-wait for system to reach deep idle states (Req 1.7)
    # ------------------------------------------------------------------
    dprint("Waiting %ds for deep idle...", pre_wait_seconds)
    time.sleep(pre_wait_seconds)

    # ------------------------------------------------------------------
    # Step 3: Collect samples
    # ------------------------------------------------------------------
    sched_monitor = SchedulerMonitor({})
    all_powers    = {}   # type: Dict[str, List[float]]   # raw_key -> [watts per sample]
    all_stds      = {}   # type: Dict[str, List[float]]

    start_interrupts = sched_monitor._read_total_interrupts()
    start_time       = time.time()

    for sample_idx in range(num_samples):
        dprint("Sample %d/%d", sample_idx + 1, num_samples)

        # read_energy() returns ALL domains the platform exposes — BDC-7
        start_raw = energy_reader.read_energy()

        # Optional separate GPU accumulator read (measure_gpu flag controls this ONLY)
        # This is ADDITIONAL to whatever gpu domain read_energy() already returns.
        # Uses GPUCollector — same backend auto-detection as the run-level total
        # energy fix earlier this session: DCGM on GN100, MSR PP1 on Tiger Lake,
        # NVML/ROCm/IOKit elsewhere. Replaces the old direct read_gpu_msr() call,
        # which only ever worked on Tiger Lake and silently measured nothing on
        # every other platform, GN100 included.
        gpu_collector = None
        if measure_gpu:
            try:
                gpu_collector = GPUCollector(rapl_reader=energy_reader)
                gpu_collector.start()
            except Exception:
                gpu_collector = None   # no backend available — MIC-1
 
        time.sleep(duration_seconds)
 
        end_raw = energy_reader.read_energy()
 
        gpu_samples = []
        if gpu_collector is not None:
            try:
                gpu_samples = gpu_collector.stop()
            except Exception:
                gpu_samples = []

        # Compute per-domain power for this sample
        for raw_key in start_raw:
            if raw_key not in end_raw:
                continue    # domain disappeared mid-sample — skip, not zero
            delta_uj = max(0, end_raw[raw_key] - start_raw[raw_key])
            power_w  = (delta_uj / 1_000_000) / duration_seconds
            if raw_key not in all_powers:
                all_powers[raw_key] = []
            all_powers[raw_key].append(power_w)

        # Separate GPU accumulator sample — only if real samples came back.
        # Key 'gpu_dcgm' distinguishes this from the gpu domain in read_energy()
        # (SPBM's broad rail, kept separate and unchanged for the NVLink work).
        measured_uj = [s.energy_uj for s in gpu_samples if s.energy_uj is not None]
        if measured_uj:
            gpu_power_w = sum(measured_uj) / 1_000_000 / duration_seconds
            if 'gpu_dcgm' not in all_powers:
                all_powers['gpu_dcgm'] = []
            all_powers['gpu_dcgm'].append(gpu_power_w)

    # ------------------------------------------------------------------
    # Step 4: Statistics
    # ------------------------------------------------------------------
    raw_power  = {}   # type: Dict[str, float]
    raw_std    = {}   # type: Dict[str, float]

    for raw_key, values in all_powers.items():
        raw_power[raw_key] = statistics.mean(values)
        raw_std[raw_key]   = statistics.stdev(values) if len(values) > 1 else 0.0
        dprint(
            "  %s: mean=%.4fW std=%.4fW",
            raw_key, raw_power[raw_key], raw_std[raw_key],
        )

    end_time       = time.time()
    end_interrupts = sched_monitor._read_total_interrupts()
    elapsed        = end_time - start_time
    interrupt_rate = (end_interrupts - start_interrupts) / max(elapsed, 1)
    current_state["interrupt_rate"] = interrupt_rate

    # ------------------------------------------------------------------
    # Step 5: Normalize raw keys to canonical names (BDC-6)
    # This is the ONLY place in A-LEMS where raw keys become canonical names.
    # After this point, no code anywhere sees pkg, package-0, cpu_p etc.
    # ------------------------------------------------------------------
    canonical_power = {}   # type: Dict[str, float]
    canonical_std   = {}   # type: Dict[str, float]

    for raw_key, power in raw_power.items():
        if raw_key not in BASELINE_DOMAIN_MAP:
            # Unknown key — log warning, do not store (BDC-7: only skip truly unmapped keys)
            logger.warning(
                "measure_idle_baseline: raw_key '%s' not in BASELINE_DOMAIN_MAP "
                "— add it to maintain BDC-7 completeness",
                raw_key,
            )
            continue
        canonical_name = BASELINE_DOMAIN_MAP[raw_key][0]
        # If two raw_keys map to same canonical (e.g. 'core' and 'cpu' both -> CORE)
        # only one platform sends each key so this will not collide in practice
        canonical_power[canonical_name] = power
        canonical_std[canonical_name]   = raw_std.get(raw_key, 0.0)

    # Determine gpu_method for provenance — stored in metadata, inserted by insert_baseline
    gpu_method = getattr(energy_reader, 'METHOD_ID', None)
    current_state["gpu_method"] = gpu_method
    # Record whether GPU_DCGM was actually populated this run, not just
    # requested. A cache hit later must match this, or a stale cache from
    # before GPU measurement existed, or from a run where the backend
    # simply wasn't available, would silently look valid forever and never
    # get remeasured, even when measure_gpu=True was explicitly asked for.
    current_state["measured_gpu_dcgm"] = "GPU_DCGM" in canonical_power

    # ------------------------------------------------------------------
    # Step 6: Construct BaselineMeasurement with canonical keys
    # ------------------------------------------------------------------
    baseline = BaselineMeasurement(
        baseline_id=f"baseline_{int(time.time())}_{os.getpid()}",
        timestamp=time.time(),
        power_watts=canonical_power,         # canonical uppercase keys always
        duration_seconds=duration_seconds * num_samples,
        sample_count=num_samples,
        std_dev_watts=canonical_std,
        cpu_temperature_c=None,              # MIC-1: NULL not 0.0 when unavailable
        method="idle_measurement",
        metadata=current_state,
    )

    # BDC-7 self-check: canonical count must equal raw domain count from read_energy()
    expected_count = len(all_powers)
    actual_count   = len(canonical_power)
    if actual_count < expected_count:
        logger.warning(
            "BDC-7 warning: read_energy() returned %d domains but only %d "
            "were mapped via BASELINE_DOMAIN_MAP. Add missing raw_keys.",
            expected_count, actual_count,
        )

    # ------------------------------------------------------------------
    # Step 7: Save to cache
    # ------------------------------------------------------------------
    try:
        with open(cache_file, "w") as f:
            json.dump(baseline.to_dict(), f, indent=2, default=str)
        dprint("Saved idle baseline to %s", cache_file)
    except Exception as e:
        logger.error("Failed to save baseline cache: %s", e)

    return baseline


# =============================================================================
# Baseline correction utility (unchanged)
# =============================================================================

def apply_baseline_correction(raw_energy_uj, baseline_power_watts, duration_seconds):
    # type: (Dict[str, int], Dict[str, float], float) -> Dict[str, int]
    """
    Apply idle baseline correction to raw energy measurements.

    Args:
        raw_energy_uj:        Raw energy in microjoules per domain.
        baseline_power_watts: Idle power in Watts per domain (canonical keys).
        duration_seconds:     Duration of the measurement window.

    Returns:
        Corrected energy in microjoules (raw minus idle), minimum 0.
    """
    corrected = {}
    for domain, energy_uj in raw_energy_uj.items():
        if domain in baseline_power_watts:
            idle_uj = int(baseline_power_watts[domain] * duration_seconds * 1_000_000)
            corrected[domain] = max(0, energy_uj - idle_uj)
        else:
            corrected[domain] = energy_uj    # no baseline for this domain — use raw
    return corrected


# =============================================================================
# Standalone test
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("\n" + "=" * 70)
    print("IDLE BASELINE MEASUREMENT TEST")
    print("=" * 70)

    # Factory dispatch — correct reader for this platform (PAC-2)
    from core.readers.factory import ReaderFactory
    reader = ReaderFactory.get_energy_reader()
    pinner = CorePinner(default_cores=[0, 1])

    print(f"Reader: {reader.__class__.__name__}")
    print(f"Available: {reader.is_available()}")

    print("\nFirst call (measuring, will save to cache)...")
    b1 = measure_idle_baseline(
        energy_reader=reader,
        core_pinner=pinner,
        duration_seconds=2,
        num_samples=2,
        pre_wait_seconds=2,
    )
    print(f"  power_watts: {b1.power_watts}")
    print(f"  domains: {list(b1.power_watts.keys())}")

    print("\nSecond call (should load from cache)...")
    b2 = measure_idle_baseline(energy_reader=reader, core_pinner=pinner)
    print(f"  power_watts: {b2.power_watts}")

    # Round-trip integrity check (BDC-7)
    assert set(b1.power_watts.keys()) == set(b2.power_watts.keys()), \
        "Round-trip key mismatch!"
    print("\nRound-trip integrity: PASS")

    print("\n" + "=" * 70)
    print("Test complete")
    print("=" * 70)
