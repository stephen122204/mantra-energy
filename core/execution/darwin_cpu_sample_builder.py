"""
core/execution/darwin_cpu_sample_builder.py
============================================
Helper: build one cpu_samples row from KPerfPMUReader PerformanceCounters
on Apple Silicon (Darwin arm64).

Mirrors arm_cpu_sample_builder.py exactly — one summary row per run.
On x86, turbostat writes N continuous rows. On Darwin, KPerfPMUReader
returns aggregate PerformanceCounters for the full measurement window.
aggregate_hardware_metrics ETL uses SUM() so one row produces identical
ETL output to N rows summing to the same values.

PAC-2: No platform-conditional imports — caller guards with
       platform.system() == 'Darwin' before calling this function.
EEI:   No DB access — returns a dict only.
DC-1:  ~30% comments explaining WHY, not WHAT.
PVC-1: Python 3.9 compatible — no walrus operator, no 3.10+ syntax.
"""

import logging
import time as _time

logger = logging.getLogger(__name__)


def _build_darwin_cpu_sample_row(run_id, result):
    # type: (int, dict) -> dict
    """
    Build a single cpu_samples row from KPerfPMUReader PerformanceCounters.

    Extracts PerformanceCounters from result dict returned by
    EnergyEngine.stop_measurement() on Darwin arm64. The perf counters
    are stored under result['perf_counters'] or result['raw_energy'].perf
    following the same convention as arm_cpu_sample_builder.

    Frequency comes from turbostat_data summary (IOReportCPUFreqReader).
    cpu_util comes from cpu_active_ratio * 100 (populated by IOReport).

    IPC: available from KPerfPMUReader (instructions/cycles).
    L2/L3 cache misses: NULL — not in a14.plist (hardware limitation).

    Args:
        run_id: DB run_id for traceability.
        result: dict from stop_measurement() or linear_result.

    Returns:
        dict ready for insert_cpu_samples(), or None if no counter data.
    """
    # Try direct key first (future-proof path)
    perf = result.get("perf_counters")

    # Fall back to raw_energy['perf'] — same convention as ARM builder
    if perf is None:
        raw = result.get("raw_energy")
        if isinstance(raw, dict):
            perf = raw.get("perf")
        elif raw is not None:
            perf = getattr(raw, "perf", None)

    if not perf:
        # KPerfPMUReader not available or helper failed — not an error
        logger.debug(
            "_build_darwin_cpu_sample_row: no perf counters for run_id=%d", run_id
        )
        return None

    # Frequency from IOReportCPUFreqReader via turbostat_data summary
    freq_data = result.get("turbostat_data") or {}
    summary = freq_data.get("summary", {}) if isinstance(freq_data, dict) else {}
    freq_mean = summary.get("frequency_mean", 0.0)

    # cpu_active_ratio from IOReport — convert to percent for cpu_util_percent
    # cpu_active_ratio is the fraction of wall time P-cluster was non-idle
    cpu_active_ratio = summary.get("cpu_active_ratio", None)
    cpu_util = (cpu_active_ratio * 100.0) if cpu_active_ratio is not None else None

    # Extract counter values — PerformanceCounters object or dict
    if isinstance(perf, dict):
        instructions = perf.get("instructions_retired", 0)
        cycles = perf.get("cpu_cycles", 0)
        cache_misses = perf.get("cache_misses", None)
        l1d_misses = perf.get("l1d_cache_misses", None)
        ipc = perf.get("ipc", None)
        if ipc is None and cycles and cycles > 0:
            ipc = instructions / cycles
    else:
        # PerformanceCounters object
        instructions = getattr(perf, "instructions_retired", 0)
        cycles = getattr(perf, "cpu_cycles", 0)
        cache_misses = getattr(perf, "cache_misses", None)
        l1d_misses = getattr(perf, "l1d_cache_misses", None)
        # instructions_per_cycle() is a method on PerformanceCounters
        try:
            ipc = perf.instructions_per_cycle() if cycles > 0 else None
        except Exception:
            ipc = None

    now_ns = _time.time_ns()

    return {
        "run_id":            run_id,
        "timestamp_ns":      now_ns,
        # sample_start_ns and sample_end_ns are patched in by caller
        # (same pattern as arm_cpu_sample_builder — set from run record)
        "sample_start_ns":   None,
        "sample_end_ns":     None,
        "interval_ns":       None,
        # Frequency from IOReportCPUFreqReader (more accurate than psutil)
        "cpu_busy_mhz":      freq_mean or None,
        "cpu_avg_mhz":       freq_mean or None,
        # cpu_util from IOReport active ratio — more accurate than psutil
        "cpu_util_percent":  cpu_util,
        # PMU counters from KPerfPMUReader
        "instructions":      instructions or None,
        "cycles":            cycles or None,
        "ipc":               ipc,
        "cache_misses":      cache_misses if cache_misses else None,
        "l1d_cache_misses":  l1d_misses if l1d_misses else None,
        # L2/L3 not in a14.plist — MIC-1: NULL not zero
        "l2_cache_misses":   None,
        "l3_cache_misses":   None,
        # package_power not available in this path (IOKit provides energy not power here)
        "package_power":     None,
    }
