"""
================================================================================
SAMPLE PROCESSOR – Handle energy, CPU, and interrupt sample processing
================================================================================
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

logger = logging.getLogger(__name__)


def process_energy_samples(energy_engine) -> tuple:
    """
    Process energy samples from energy_engine.

    Returns:
        Tuple of (energy_samples, interrupt_samples)
    """
    energy_samples = []
    interrupt_samples = []

    if hasattr(energy_engine, "last_samples"):
        samples = energy_engine.last_samples
        logger.debug(
            f"🔍 DEBUG - Found {len(samples)} samples in energy_engine.last_samples"
        )

        # Samples are tuples - identify them by structure
        for sample in samples:
            if len(sample) == 2 and isinstance(sample[1], dict):
                # This is an energy sample: (timestamp, {'core':..., 'package-0':..., 'uncore':...})
                timestamp, energy_dict = sample
                energy_samples.append(
                    {
                        "timestamp_ns": int(
                            timestamp * 1_000_000_000
                        ),  # Convert seconds to ns
                        "pkg_energy_uj": energy_dict.get("package-0", 0),
                        "core_energy_uj": energy_dict.get("core", 0),
                        "uncore_energy_uj": energy_dict.get("uncore", 0),
                        "dram_energy_uj": 0,  # DRAM not in samples
                    }
                )
            elif len(sample) == 2 and isinstance(sample[1], (int, float)):
                # This is an interrupt sample: (timestamp, value)
                interrupt_timestamp, interrupt_value = sample
                print(
                    f"🔍 INTERRUPT RAW - timestamp: {interrupt_timestamp}, type: {type(interrupt_timestamp)}"
                )
                print(f"🔍 INTERRUPT RAW - value: {interrupt_value}")
                print(
                    f"🔍 INTERRUPT CALC - divided by 1e9: {interrupt_timestamp / 1e9}"
                )
                print(f"🔍 INTERRUPT CALC - epoch time: {time.time()}")

                interrupt_samples.append(
                    {
                        "timestamp_ns": int(interrupt_timestamp),
                        "interrupts_per_sec": interrupt_value,
                    }
                )
            else:
                logger.debug(f"⚠️ Unknown sample format: {sample}")

        logger.debug(
            f"📊 Processed {len(energy_samples)} energy samples, {len(interrupt_samples)} interrupt samples"
        )
    io_samples = []
    if hasattr(energy_engine, "last_io_samples"):
        io_samples = energy_engine.last_io_samples
    return energy_samples, interrupt_samples, io_samples


def process_cpu_samples(raw_energy, canonical_metrics, store_extra=True) -> list:
    """
    Extract CPU samples from turbostat continuous data.

    Returns:
        List of CPU sample dictionaries
    """
    cpu_samples = []

    if (
        hasattr(raw_energy, "turbostat")
        and raw_energy.turbostat.get("dataframe") is not None
    ):
        df = raw_energy.turbostat["dataframe"]

        # Get timing info from metadata
        start_ns = None
        interval_ns = 100_000_000  # Default 100ms
        if hasattr(raw_energy, "metadata"):
            start_ns = raw_energy.metadata.get("turbostat_start_ns")
            interval_ns = raw_energy.metadata.get("turbostat_interval_ns", 100_000_000)

        # Fix 2 (BUG-01): resolve k10temp path ONCE per run, not per
        # sample. detect_thermal_paths() globs /sys/class/thermal and
        # /sys/class/hwmon and opens a type/name file per candidate —
        # cheap once, wasteful at 10Hz. Only runs when turbostat's own
        # DataFrame has no PkgTmp column at all, so platforms where
        # turbostat already reports temperature (UBUNTU2505) never pay
        # this cost and are otherwise untouched by this change.
        _k10temp_path = None
        if not df.empty and "PkgTmp" not in df.columns:
            from scripts.detect_hardware import detect_thermal_paths
            _thermal_paths, _pkg_temp_zone = detect_thermal_paths()
            if _pkg_temp_zone == "k10temp":
                _k10temp_path = _thermal_paths.get("k10temp")

        if not df.empty:
            for idx, row in df.iterrows():
                # Calculate timestamp using monotonic clock
                if start_ns is not None:
                    # Each turbostat sample ends at start + (idx+1) * interval
                    sample_end_ns   = start_ns + (idx + 1) * interval_ns
                    sample_start_ns = start_ns + idx * interval_ns
                    timestamp_ns    = sample_end_ns   # backward compat
                else:
                    # Fallback to old method
                    sample_end_ns   = int((raw_energy.start_time + (idx + 1) * 0.1) * 1e9)
                    sample_start_ns = int((raw_energy.start_time + idx * 0.1) * 1e9)
                    timestamp_ns    = sample_end_ns

                # Start with timestamp fields — explicit start/end + backward compat
                sample = {
                    "timestamp_ns":    timestamp_ns,
                    "sample_start_ns": sample_start_ns,
                    "sample_end_ns":   sample_end_ns,
                    "interval_ns":     interval_ns,
                }

                # Extract canonical metrics.
                # ALIAS SUPPORT (BUG-01 fix, 2026-08-31): turbostat renames
                # columns across kernel/turbostat versions and CPU vendors
                # (Intel emits "C1ACPI%", AMD Zen 2 emits "C1%" for the same
                # physical quantity — confirmed by real header capture on
                # both platforms). canonical_metrics values may be a single
                # column name (legacy string, backward compatible) or a
                # list of alias names tried in order; first one present in
                # this row wins. Self-healing across future turbostat or
                # kernel renames without another override-file edit.
                matched_alias_names = set()
                for our_name, turbostat_col in canonical_metrics.items():
                    aliases = (
                        turbostat_col if isinstance(turbostat_col, list)
                        else [turbostat_col]
                    )
                    try:
                        raw = None
                        for alias in aliases:
                            candidate = row.get(alias)
                            # MIC-1: missing column -> NULL, not 0.0.
                            # Try the next alias before giving up.
                            if candidate is None:
                                continue
                            if hasattr(candidate, '__class__') and candidate.__class__.__name__ == 'float' and candidate != candidate:
                                continue  # NaN -- try next alias
                            raw = candidate
                            matched_alias_names.add(alias)
                            break

                        if raw is None:
                            # No alias matched — genuinely unmeasured on
                            # this hardware/turbostat build, not a bug.
                            sample[our_name] = None
                            continue
                        val = float(raw)

                        # Scale percentages (C-states, GPU RC6)
                        if our_name in [
                            "c1_residency",
                            "c2_residency",
                            "c3_residency",
                            "c6_residency",
                            "c7_residency",
                            "pkg_c8_residency",
                            "pkg_c9_residency",
                            "pkg_c10_residency",
                            "gpu_rc6",
                        ]:
                            val = val / 100.0

                        # IPC might need scaling if >10
                        if our_name == "ipc" and val > 10:
                            val = val / 10.0

                        sample[our_name] = val
                    except (TypeError, ValueError):
                        sample[our_name] = None

                # Fix 2 (BUG-01): package_temp via k10temp hwmon when
                # turbostat emits no thermal column at all. AMD's
                # turbostat build on Ryzen 5 3600 has no PkgTmp column
                # (confirmed by real header capture 2026-08-31) — no
                # alias can recover a column turbostat never reports.
                # Falls back to the same k10temp path already proven for
                # thermal_samples_v2 (EDIT 5). Path resolved once above
                # this loop (see _k10temp_path), not per sample — cheap
                # read only, no re-discovery per tick.
                if sample.get("package_temp") is None and _k10temp_path:
                    try:
                        with open(_k10temp_path) as f:
                            sample["package_temp"] = int(f.read().strip()) / 1000.0
                    except (IOError, OSError, ValueError):
                        pass  # stays None — honest NULL, not fabricated

                # Store all other columns in JSON. Excludes every alias
                # that actually matched (not just the primary name), so a
                # column consumed via its AMD-style alias (e.g. "C1%")
                # does not also leak into extra_metrics_json.
                if store_extra:
                    extra = {}
                    for col in df.columns:
                        if col not in matched_alias_names:
                            val = row.get(col)
                            if val is not None:
                                try:
                                    extra[col] = float(val)
                                except (TypeError, ValueError):
                                    extra[col] = str(val)
                    sample["extra_metrics_json"] = json.dumps(extra) if extra else "{}"

                cpu_samples.append(sample)
        # Chunk 12: inject perf cache counters into each sample
        # perf gives run-total counts — divide evenly across samples
        if cpu_samples and hasattr(raw_energy, "perf") and raw_energy.perf:
            n = len(cpu_samples)
            perf = raw_energy.perf
            l1d = getattr(perf, "l1d_cache_misses", 0) // n
            l2  = getattr(perf, "l2_cache_misses",  0) // n
            l3h = getattr(perf, "l3_cache_hits",    0) // n
            l3m = getattr(perf, "l3_cache_misses",  0) // n
            for s in cpu_samples:
                s["l1d_cache_misses"] = l1d
                s["l2_cache_misses"]  = l2
                s["l3_cache_hits"]    = l3h
                s["l3_cache_misses"]  = l3m 
            logger.debug(
                f"📊 Extracted {len(cpu_samples)} CPU samples with {len(canonical_metrics)} canonical metrics"
            )
            if cpu_samples:
                print(f"🔍 First 3 CPU samples:")
                for i, sample in enumerate(cpu_samples[:3]):
                    print(f"   Sample {i}: {sample}")

    return cpu_samples


def calculate_thermal_metrics(cpu_samples, thermal_samples=None) -> tuple:
    """
    Calculate thermal metrics from thermal_samples (primary) or cpu_samples fallback.

    thermal_samples (from ThermalReaderV2 / SensorReader) is the primary source
    on all platforms. cpu_samples.package_temp (turbostat) is unreliable on x86
    after version changes and empty on ARM — used only as last resort.

    Returns:
        Tuple of (start_temp_c, max_temp_c, min_temp_c, thermal_delta_c)
    """
    # Primary: read cpu_temp from thermal_samples (works on all platforms)
    temps = []
    if thermal_samples:
        temps = [
            s.get("cpu_temp") for s in thermal_samples
            if s.get("cpu_temp") is not None and s.get("cpu_temp") > 10
        ]

    # Fallback: turbostat package_temp from cpu_samples (x86 only, unreliable)
    if not temps and cpu_samples:
        temps = [
            s.get("package_temp") for s in cpu_samples
            if s.get("package_temp") is not None and s.get("package_temp") > 10
        ]

    if temps:
        start_temp_c    = temps[0]
        max_temp_c      = max(temps)
        min_temp_c      = min(temps)
        thermal_delta_c = max_temp_c - start_temp_c
    else:
        start_temp_c    = 0
        max_temp_c      = 0
        min_temp_c      = 0
        thermal_delta_c = 0

    return start_temp_c, max_temp_c, min_temp_c, thermal_delta_c


def load_canonical_metrics() -> tuple:
    """
    Load canonical metrics from turbostat_override.yaml.

    Returns:
        Tuple of (canonical_metrics dict, store_extra boolean)
    """
    canonical_metrics = {}
    store_extra = True

    override_path = Path("config/turbostat_override.yaml")
    if override_path.exists():
        try:
            with open(override_path, "r") as f:
                override_config = yaml.safe_load(f)
            canonical_metrics = override_config.get("canonical_metrics", {})
            store_extra = override_config.get("store_extra_in_json", True)
            logger.debug(
                f"📋 Loaded {len(canonical_metrics)} canonical metrics from override file"
            )
        except Exception as e:
            logger.debug(f"⚠️ Failed to load override file: {e}")

    return canonical_metrics, store_extra
