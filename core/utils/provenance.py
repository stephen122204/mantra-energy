#!/usr/bin/env python3
"""
================================================================================
PROVENANCE — Per-Run Per-Metric Provenance Recording
================================================================================

Single entry point called ONCE from experiment_runner after insert_run().
Fills ALL columns of measurement_methodology table for every metric.

Provenance Definitions:
    MEASURED   — direct hardware or OS read, no mathematics
    CALCULATED — deterministic formula applied to measured values
    INFERRED   — uses external constants, emission factors, or models
    SYSTEM     — infrastructure metadata, no scientific meaning

Scalability:
    New runs column → add ONE line to COLUMN_PROVENANCE
    New method      → add ONE line to METHOD_CONFIDENCE
    Zero other changes required

Usage:
    from core.utils.provenance import record_run_provenance
    run_id = db.insert_run(exp_id, hw_id, result)
    record_run_provenance(db, run_id, result)

Author: Deepak Panigrahy
================================================================================
"""

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# UNIT OVERRIDES — explicit wins over suffix inference
# =============================================================================

UNIT_OVERRIDES: Dict[str, str] = {
    "cache_miss_rate":       "%",      # Bug 4 fix: not Hz
    "ipc":                   "ratio",
    "complexity_score":      "ratio",
    "complexity_level":      "level",
    "interrupt_rate":        "Hz",
    "interrupts_per_second": "Hz",
    "phase_planning_ratio":  "ratio",
    "phase_execution_ratio": "ratio",
    "phase_synthesis_ratio": "ratio",
}


# =============================================================================
# COLUMN PROVENANCE MAP
# metric_id → (method_id, provenance_type)
# Add ONE line when new runs table column added.
# =============================================================================

COLUMN_PROVENANCE: Dict[str, Tuple[Optional[str], str]] = {

    # ── MEASURED ─────────────────────────────────────────────────────────────
    "pkg_energy_uj":                ("rapl_msr_pkg_energy",           "MEASURED"),
    "core_energy_uj":               ("rapl_msr_pkg_energy",           "MEASURED"),
    "uncore_energy_uj":             ("rapl_msr_pkg_energy",           "MEASURED"),
    "dram_energy_uj":               ("rapl_msr_pkg_energy",           "MEASURED"),
    "instructions":                 ("perf_counters",                  "MEASURED"),
    "cycles":                       ("perf_counters",                  "MEASURED"),
    "cache_misses":                 ("perf_counters",                  "MEASURED"),
    "cache_references":             ("perf_counters",                  "MEASURED"),
    "page_faults":                  ("perf_counters",                  "MEASURED"),
    "major_page_faults":            ("perf_counters",                  "MEASURED"),
    "minor_page_faults":            ("perf_counters",                  "MEASURED"),
    "context_switches_voluntary":   ("perf_counters",                  "MEASURED"),
    "context_switches_involuntary": ("perf_counters",                  "MEASURED"),
    "thread_migrations":            ("perf_counters",                  "MEASURED"),
    "package_temp_celsius":         ("thermal_sensor",                 "MEASURED"),
    "api_latency_ms":               ("ttft_tpot_wall_clock",           "MEASURED"),
    "total_tokens":                 ("ttft_tpot_wall_clock",           "MEASURED"),
    "prompt_tokens":                ("ttft_tpot_wall_clock",           "MEASURED"),
    "completion_tokens":            ("ttft_tpot_wall_clock",           "MEASURED"),
    "bytes_sent":                   ("network_measurement",            "MEASURED"),
    "bytes_recv":                   ("network_measurement",            "MEASURED"),
    "tcp_retransmits":              ("network_measurement",            "MEASURED"),
    "swap_total_mb":                ("os_memory_reader",               "MEASURED"),
    "swap_end_free_mb":             ("os_memory_reader",               "MEASURED"),
    "swap_start_cached_mb":         ("os_memory_reader",               "MEASURED"),
    "swap_end_cached_mb":           ("os_memory_reader",               "MEASURED"),
    "swap_end_percent":             ("os_memory_reader",               "MEASURED"),
    "rss_memory_mb":                ("os_memory_reader",               "MEASURED"),
    "vms_memory_mb":                ("os_memory_reader",               "MEASURED"),
    "frequency_mhz":                ("turbostat_reader",               "MEASURED"),
    "ring_bus_freq_mhz":            ("turbostat_reader",               "MEASURED"),
    "cpu_busy_mhz":                 ("turbostat_reader",               "MEASURED"),
    "run_queue_length":             ("os_scheduler_reader",            "MEASURED"),
    "kernel_time_ms":               ("os_scheduler_reader",            "MEASURED"),
    "user_time_ms":                 ("os_scheduler_reader",            "MEASURED"),
    "interrupt_rate":               ("os_scheduler_reader",            "MEASURED"),
    "interrupts_per_second":        ("os_scheduler_reader",            "MEASURED"),
    "wakeup_latency_us":            ("os_scheduler_reader",            "MEASURED"),
    "background_cpu_percent":       ("os_scheduler_reader",            "MEASURED"),
    "process_count":                ("os_scheduler_reader",            "MEASURED"),
    "c2_time_seconds":              ("msr_reader",                     "MEASURED"),
    "c3_time_seconds":              ("msr_reader",                     "MEASURED"),
    "c6_time_seconds":              ("msr_reader",                     "MEASURED"),
    "c7_time_seconds":              ("msr_reader",                     "MEASURED"),
    "start_time_ns":                ("system_clock",                   "MEASURED"),
    "end_time_ns":                  ("system_clock",                   "MEASURED"),

    # ── CALCULATED ───────────────────────────────────────────────────────────
    "dynamic_energy_uj":            ("dynamic_energy_calculation",     "CALCULATED"),
    "baseline_energy_uj":           ("dynamic_energy_calculation",     "CALCULATED"),
    "total_energy_uj":              ("dynamic_energy_calculation",     "CALCULATED"),
    "avg_power_watts":              ("dynamic_energy_calculation",     "CALCULATED"),
    "ipc":                          ("ipc_calculation",                "CALCULATED"),
    "cache_miss_rate":              ("cache_miss_calculation",         "CALCULATED"),
    "total_context_switches":       ("perf_counters",                  "CALCULATED"),
    "start_temp_c":                 ("thermal_sensor",                 "CALCULATED"),
    "max_temp_c":                   ("thermal_sensor",                 "CALCULATED"),
    "min_temp_c":                   ("thermal_sensor",                 "CALCULATED"),
    "cpu_avg_mhz":                  ("turbostat_reader",               "CALCULATED"),
    "swap_start_used_mb":           ("os_memory_reader",               "CALCULATED"),
    "swap_end_used_mb":             ("os_memory_reader",               "CALCULATED"),
    "thermal_delta_c":              ("thermal_sensor",                 "CALCULATED"),
    "baseline_temp_celsius":        ("thermal_sensor",                 "CALCULATED"),
    "duration_ns":                  ("system_clock",                   "CALCULATED"),
    # Bug 1 fix: all efficiency metrics → efficiency_metrics_calculation
    "energy_per_instruction":       ("efficiency_metrics_calculation", "CALCULATED"),
    "energy_per_cycle":             ("efficiency_metrics_calculation", "CALCULATED"),
    "energy_per_token":             ("efficiency_metrics_calculation", "CALCULATED"),
    "instructions_per_token":       ("efficiency_metrics_calculation", "CALCULATED"),
    # Bug 2 fix: phase timings → orchestration_tax_calculation not ttft
    "planning_time_ms":             ("orchestration_tax_calculation",  "CALCULATED"),
    "execution_time_ms":            ("orchestration_tax_calculation",  "CALCULATED"),
    "synthesis_time_ms":            ("orchestration_tax_calculation",  "CALCULATED"),
    "avg_step_time_ms":             ("orchestration_tax_calculation",  "CALCULATED"),
    "phase_planning_ratio":         ("orchestration_tax_calculation",  "CALCULATED"),
    "phase_execution_ratio":        ("orchestration_tax_calculation",  "CALCULATED"),
    "phase_synthesis_ratio":        ("orchestration_tax_calculation",  "CALCULATED"),
    "orchestration_cpu_ms":         ("orchestration_tax_calculation",  "CALCULATED"),
    "thermal_during_experiment":    ("thermal_sensor",                 "CALCULATED"),
    "thermal_now_active":           ("thermal_sensor",                 "CALCULATED"),
    "thermal_since_boot":           ("thermal_sensor",                 "CALCULATED"),
    "thermal_throttle_flag":        ("thermal_sensor",                 "CALCULATED"),
    "complexity_score":             ("complexity_score_calculation",   "CALCULATED"),
    "complexity_level":             ("complexity_score_calculation",   "CALCULATED"),
    # ── Chunk 3: CPU fraction attribution ──────────────────
    "pid":                    (None,                        "SYSTEM"),
    "cpu_fraction":           ("cpu_fraction_attribution",  "CALCULATED"),
    "attributed_energy_uj":   ("cpu_fraction_attribution",  "CALCULATED"),
    "energy_measurement_mode": ("platform_detection",       "MEASURED"),
    "planning_energy_uj":      ("phase_attribution_cpu_v1",  "CALCULATED"),
    "execution_energy_uj":     ("phase_attribution_cpu_v1",  "CALCULATED"),
    "synthesis_energy_uj":     ("phase_attribution_cpu_v1",  "CALCULATED"),
    "l1d_cache_misses_total":    ("perf_cache_counters",      "MEASURED"),
    "l2_cache_misses_total":     ("perf_cache_counters",      "MEASURED"),
    "l3_cache_hits_total":       ("perf_cache_counters",      "MEASURED"),
    "l3_cache_misses_total":     ("perf_cache_counters",      "MEASURED"),
    "disk_read_bytes_total":     ("disk_io_stats",            "MEASURED"),
    "disk_write_bytes_total":    ("disk_io_stats",            "MEASURED"),
    "voltage_vcore_avg":         ("sensors_voltage",          "MEASURED"),         
    # ── INFERRED ─────────────────────────────────────────────────────────────
    "carbon_g":                     ("carbon_calculation",             "INFERRED"),
    "water_ml":                     ("water_calculation",              "INFERRED"),
    "methane_mg":                   ("methane_calculation",            "INFERRED"),

    # ── SYSTEM — no scientific provenance recorded ────────────────────────────
    "run_id":                       (None, "SYSTEM"),
    "exp_id":                       (None, "SYSTEM"),
    "hw_id":                        (None, "SYSTEM"),
    "baseline_id":                  (None, "SYSTEM"),
    "run_number":                   (None, "SYSTEM"),
    "workflow_type":                (None, "SYSTEM"),
    "experiment_valid":             (None, "SYSTEM"),
    "run_state_hash":               (None, "SYSTEM"),
    "global_run_id":                (None, "SYSTEM"),
    "sync_status":                  (None, "SYSTEM"),
    "sync_samples_status":          (None, "SYSTEM"),
    "governor":                     (None, "SYSTEM"),
    "turbo_enabled":                (None, "SYSTEM"),
    "is_cold_start":                (None, "SYSTEM"),
    "llm_calls":                    (None, "SYSTEM"),
    "tool_calls":                   (None, "SYSTEM"),
    "tools_used":                   (None, "SYSTEM"),
    "steps":                        (None, "SYSTEM"),
}


# =============================================================================
# METHOD CONFIDENCE MAP
# =============================================================================

METHOD_CONFIDENCE: Dict[str, float] = {
    "rapl_msr_pkg_energy":           1.0,
    "iokit_power_reader":            0.5,
    "ml_energy_estimator":           0.0,
    "dummy_energy_reader":           0.0,
    "perf_counters":                 1.0,
    "thermal_sensor":                1.0,
    "ttft_tpot_wall_clock":          1.0,
    "network_measurement":           1.0,
    "os_memory_reader":              1.0,
    "turbostat_reader":              1.0,
    "os_scheduler_reader":           1.0,
    "msr_reader":                    1.0,
    "system_clock":                  1.0,
    "dynamic_energy_calculation":    1.0,
    "ipc_calculation":               1.0,
    "cache_miss_calculation":        1.0,
    "orchestration_tax_calculation": 1.0,
    "efficiency_metrics_calculation":1.0,
    "carbon_calculation":            0.7,
    "water_calculation":             0.7,
    "methane_calculation":           0.7,
    "complexity_score_calculation":  0.8,
    "cpu_fraction_attribution":      0.95,
    "platform_detection":            1.0,
    "phase_attribution_cpu_v1":      0.95,
    "perf_cache_counters":           1.0,
    "disk_io_stats":                 1.0,
    "sensors_voltage":               1.0,    
}


# =============================================================================
# CROSS-MAP VALIDATION — runs at import time, fails loud
# Design 1 fix: every method_id in COLUMN_PROVENANCE must be in METHOD_CONFIDENCE
# =============================================================================

def _validate_maps() -> None:
    """Validate COLUMN_PROVENANCE and METHOD_CONFIDENCE are in sync."""
    missing = {
        method_id
        for method_id, _ in COLUMN_PROVENANCE.values()
        if method_id and method_id not in METHOD_CONFIDENCE
    }
    if missing:
        raise ValueError(
            f"Methods in COLUMN_PROVENANCE missing from METHOD_CONFIDENCE: {missing}"
        )

_validate_maps()


# =============================================================================
# PARAMETERS MAP
# metric_id → which result dict keys go into parameters_used
# =============================================================================

PARAMETERS_MAP: Dict[str, list] = {
    "ipc":                   ["instructions", "cycles"],
    "cache_miss_rate":       ["cache_misses", "cache_references"],
    "dynamic_energy_uj":     ["pkg_energy_uj", "baseline_energy_uj"],
    "total_energy_uj":       ["pkg_energy_uj", "baseline_energy_uj"],
    "avg_power_watts":       ["pkg_energy_uj", "duration_ns"],
    "energy_per_token":      ["pkg_energy_uj", "total_tokens"],
    "energy_per_instruction":["pkg_energy_uj", "instructions"],
    "energy_per_cycle":      ["pkg_energy_uj", "cycles"],
    "instructions_per_token":["instructions", "total_tokens"],
    "carbon_g":              ["pkg_energy_uj"],
    "water_ml":              ["pkg_energy_uj"],
    "methane_mg":            ["pkg_energy_uj"],
    "complexity_score":      ["llm_calls", "tool_calls", "total_tokens"],
    "orchestration_cpu_ms":  ["planning_time_ms", "execution_time_ms", "synthesis_time_ms"],
    "thermal_delta_c":       ["start_temp_c", "max_temp_c"],
    "start_temp_c":          ["package_temp_celsius"],
    "max_temp_c":            ["package_temp_celsius"],
    "min_temp_c":            ["package_temp_celsius"],
    "phase_planning_ratio":  ["planning_time_ms", "duration_ns"],
    "phase_execution_ratio": ["execution_time_ms", "duration_ns"],
    "phase_synthesis_ratio": ["synthesis_time_ms", "duration_ns"],
}


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def record_run_provenance(
    db,
    run_id: int,
    result: Dict[str, Any],
    reader_mode: Optional[str] = None,
) -> None:
    """
    Record provenance for every metric in a run result dict.

    Called ONCE from experiment_runner after insert_run().
    Writes one row to measurement_methodology per metric.

    Args:
        db:          DatabaseManager with methodology repo wired.
        run_id:      DB run ID from insert_run().
        result:      Result dict from harness.
        reader_mode: Energy reader mode e.g. "INFERRED" for ARM VM.
    """
    recorded = 0

    metrics = result.get("ml_features", result)
    for metric_id, value in metrics.items():

        # Skip unmapped — future columns safe
        if metric_id not in COLUMN_PROVENANCE:
            continue

        method_id, provenance = COLUMN_PROVENANCE[metric_id]

        # Skip SYSTEM — no scientific provenance needed
        if provenance == "SYSTEM":
            continue

        # Skip None values — metric not computed this run
        if value is None:
            continue

        # Design 2 fix: warn on non-numeric instead of silent None
        if not isinstance(value, (int, float, bool)):
            logger.warning(
                "Non-numeric value for %s: %r — value_raw will be NULL",
                metric_id, value,
            )
            value_raw = None
        else:
            value_raw = float(value)

        # Build parameters_used from result dict inputs
        parameters: Dict[str, Any] = {}
        for input_key in PARAMETERS_MAP.get(metric_id, []):
            if input_key in result and result[input_key] is not None:
                parameters[input_key] = result[input_key]

        # Add reader_mode for RAPL metrics — documents platform capability
        if reader_mode and method_id == "rapl_msr_pkg_energy":
            parameters["reader_mode"] = reader_mode

        # Write provenance row
        db.methodology.insert_provenance({
            "run_id":                run_id,
            "metric_id":             metric_id,
            "method_id":             method_id,
            "value_raw":             value_raw,
            "value_unit":            _unit(metric_id),
            "provenance":            provenance,
            "hw_available":          1,
            "confidence":            METHOD_CONFIDENCE.get(method_id, 1.0),
            "primary_method_failed": 0,
            "failure_reason":        None,
            "parameters_used":       parameters,
        })
        recorded += 1

    logger.info(
        "record_run_provenance: run_id=%d  recorded=%d",
        run_id, recorded,
    )


# =============================================================================
# UNIT HELPER
# =============================================================================

def _unit(metric_id: str) -> str:
    """Return unit string. Explicit overrides win over suffix inference."""
    # Explicit overrides first — prevents suffix collision (Bug 4 fix)
    if metric_id in UNIT_OVERRIDES:
        return UNIT_OVERRIDES[metric_id]

    # Suffix inference — ordered longest suffix first to prevent collision
    if metric_id.endswith("_uj"):      return "µJ"
    if metric_id.endswith("_watts"):   return "W"
    if metric_id.endswith("_ms"):      return "ms"
    if metric_id.endswith("_ns"):      return "ns"
    if metric_id.endswith("_seconds"): return "s"
    if metric_id.endswith("_mb"):      return "MB"
    if metric_id.endswith("_mhz"):     return "MHz"
    if metric_id.endswith("_celsius"): return "°C"
    if metric_id.endswith("_pct"):     return "%"
    if metric_id.endswith("_percent"): return "%"
    if metric_id.endswith("_us"):      return "µs"
    if metric_id.endswith("_g"):       return "g"
    if metric_id.endswith("_ml"):      return "ml"
    if metric_id.endswith("_mg"):      return "mg"
    if metric_id.endswith("_j"):       return "J"
    if metric_id.endswith("_c"):       return "°C"
    return ""
