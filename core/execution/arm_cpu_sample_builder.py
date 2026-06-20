"""
core/execution/arm_cpu_sample_builder.py
=========================================
Helper: build one cpu_samples row from ARM PMU PerformanceCounters.

On x86, turbostat writes N continuous rows to cpu_samples during measurement.
On aarch64 (Grace), turbostat is absent. ARMPMUReader returns a PerformanceCounters
object that holds the aggregate counts for the entire run. This module converts
that object into the single-row dict format expected by insert_cpu_samples().

One summary row per run is sufficient because aggregate_hardware_metrics ETL
uses SUM() across cpu_samples rows. A single row with the full run totals
produces identical ETL output to N rows that sum to the same values.

PAC-2: this module has NO platform-conditional imports — caller guards with
       caps.arch == 'aarch64' before calling _build_arm_cpu_sample_row().
EEI:   no DB access — returns a dict only.
DC-1:  ~30% comments explaining WHY, not WHAT.
PVC-1: Python 3.9 compatible — no walrus operator, no 3.10+ syntax.
"""

import time as _time
import logging

logger = logging.getLogger(__name__)


def _build_arm_cpu_sample_row(run_id, result):
    # type: (int, dict) -> dict
    """
    Build a single cpu_samples row from ARM PMU PerformanceCounters.

    Extracts PerformanceCounters from the result dict returned by
    EnergyEngine.stop_measurement() on aarch64. The path through the
    result dict depends on how ARMPMUReader wires its output — currently
    via result['raw_energy'].perf (SPBMEnergyData carries perf counters
    as an attribute set by the sampling loop in energy_engine.py).

    Also accepts result['perf_counters'] as a direct key for future
    callers that surface it explicitly.

    Args:
        run_id: DB run_id — stored in timestamp row for traceability.
        result: dict from stop_measurement() or linear_result/agentic_result.

    Returns:
        dict ready for insert_cpu_samples(), or None if no counter data found.
    """
    # Try direct key first (future-proof path)
    perf = result.get("perf_counters")

    # Fall back to raw_energy['perf'] — confirmed live on GN100 (2026-06-20):
    # raw_energy is a plain dict (not an object), and 'perf' is a nested dict
    # with keys like instructions_retired, cpu_cycles, l1d_cache_misses, ipc
    # (ipc is precomputed by the reader, not a method to call).
    if perf is None:
        raw = result.get("raw_energy")
        if isinstance(raw, dict):
            perf = raw.get("perf")

    if not perf:
        # No ARM PMU data in result — not an error on platforms where
        # ARMPMUReader is not available (factory returns DummyCPUReader).
        logger.debug(
            "_build_arm_cpu_sample_row: no perf counters in result for run_id=%d", run_id
        )
        return None

    # Frequency data from ARMCPUFreqReader — also wrapped in raw_energy or turbostat_data
    freq_data = result.get("turbostat_data") or {}
    summary = freq_data.get("summary", {}) if isinstance(freq_data, dict) else {}
    freq_mean = summary.get("frequency_mean", 0.0)

    row = {
        "run_id":           run_id,
        "timestamp_ns":     _time.time_ns(),
        # Frequency from ARMCPUFreqReader summary (set by energy_engine.py sampling loop)
        # cpu_busy_mhz mirrors cpu_avg_mhz — ARM has no separate busy/idle frequency split
        "cpu_avg_mhz":      freq_mean,
        "cpu_busy_mhz":     freq_mean,
        # ARM PMU cache counters — these are the aggregates ETL sums for runs table columns:
        # l1d_cache_misses_total, l2_cache_misses_total, l3_cache_hits_total, l3_cache_misses_total
        "l1d_cache_misses": perf.get("l1d_cache_misses", 0),
        "l2_cache_misses":  perf.get("l2_cache_misses", 0),
        "l3_cache_hits":    perf.get("l3_cache_hits", 0),
        "l3_cache_misses":  perf.get("l3_cache_misses", 0),
        # ipc is precomputed by the reader — confirmed in live data (0.7306...).
        # Note: cpu_samples table has no instructions/cycles columns (confirmed
        # via pragma_table_info on both platforms) — ipc is the only derived
        # value from these counters that has a real column to land in.
        "ipc":              perf.get("ipc", 0.0),
        # package_temp: NULL on ARM at this call site.
        # ThermalAggregator writes thermal columns via update_run_stats() separately.
        "package_temp":     None,
    }
    return row
