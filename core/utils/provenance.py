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

    "experiment_type":  ("system_metadata_v1", "SYSTEM"),
    "experiment_goal":  ("system_metadata_v1", "SYSTEM"),
    "experiment_notes": ("system_metadata_v1", "SYSTEM"),
    # goal_execution table
    "ge.goal_id":                (None,                              "SYSTEM"),
    "ge.exp_id":                 (None,                              "SYSTEM"),
    "ge.goal_type":              (None,                              "SYSTEM"),
    "ge.workflow_type":          (None,                              "SYSTEM"),
    "ge.difficulty_level":       (None,                              "SYSTEM"),
    "ge.total_attempts":         (None,                              "SYSTEM"),
    "ge.success":                (None,                              "SYSTEM"),
    "ge.total_energy_uj":        ("goal_execution_rollup_v1",        "CALCULATED"),
    "ge.successful_energy_uj":   ("goal_execution_rollup_v1",        "CALCULATED"),
    "ge.overhead_energy_uj":     ("goal_execution_rollup_v1",        "CALCULATED"),
    "ge.overhead_fraction":      ("goal_overhead_fraction_v1",       "CALCULATED"),
    "ge.orchestration_fraction": ("goal_overhead_fraction_v1",       "CALCULATED"),
    "ge.wall_time_ms":           ("system_clock",                    "MEASURED"),
    # goal_attempt table
    "ga.attempt_id":             (None,                              "SYSTEM"),
    "ga.goal_id":                (None,                              "SYSTEM"),
    "ga.run_id":                 (None,                              "SYSTEM"),
    "ga.outcome":                (None,                              "SYSTEM"),
    "ga.failure_cause":          (None,                              "SYSTEM"),
    "ga.energy_uj":              ("goal_execution_rollup_v1",        "CALCULATED"),
    "ga.orchestration_uj":       ("goal_execution_rollup_v1",        "CALCULATED"),
    "ga.compute_uj":             ("goal_execution_rollup_v1",        "CALCULATED"),
    "ga.normalized_score":       ("output_quality_normalization_v1", "CALCULATED"),
    # hallucination_events table
    "he.hallucination_id":       ("system_metadata_v1",             "SYSTEM"),
    "he.attempt_id":             ("system_metadata_v1",             "SYSTEM"),
    "he.goal_id":                ("system_metadata_v1",             "SYSTEM"),
    "he.hallucination_type":     ("system_metadata_v1",             "SYSTEM"),
    "he.detection_method":       ("system_metadata_v1",             "SYSTEM"),
    "he.detection_confidence":   ("hallucination_detection_v1",     "INFERRED"),
    "he.semantic_similarity":    ("hallucination_detection_v1",     "INFERRED"),
    "he.severity":               ("hallucination_detection_v1",     "INFERRED"),
    "he.wasted_energy_uj":       ("hallucination_wasted_energy_v1", "CALCULATED"),
 
    # output_quality table
    "oq.quality_id":             ("system_metadata_v1",                 "SYSTEM"),
    "oq.attempt_id":             ("system_metadata_v1",                 "SYSTEM"),
    "oq.goal_id":                ("system_metadata_v1",                 "SYSTEM"),
    "oq.metric_type":            ("system_metadata_v1",                 "SYSTEM"),
    "oq.judge_method":           ("system_metadata_v1",                 "SYSTEM"),
    "oq.score_method":           ("system_metadata_v1",                 "SYSTEM"),
    "oq.judge_count":            ("system_metadata_v1",                 "SYSTEM"),
    "oq.manual_reviewed":        ("system_metadata_v1",                 "SYSTEM"),
    "oq.raw_score":              ("output_quality_normalization_v1",    "MEASURED"),
    "oq.normalized_score":       ("output_quality_normalization_v1",    "CALCULATED"),
    "oq.agreement_score":        ("output_quality_normalization_v1",    "CALCULATED"),
    "oq.energy_uj_at_judgment":  ("goal_execution_rollup_v1",           "CALCULATED"),
 
    # output_quality_judges table
    "oqj.judge_entry_id":        ("system_metadata_v1",                 "SYSTEM"),
    "oqj.quality_id":            ("system_metadata_v1",                 "SYSTEM"),
    "oqj.attempt_id":            ("system_metadata_v1",                 "SYSTEM"),
    "oqj.goal_id":               ("system_metadata_v1",                 "SYSTEM"),
    "oqj.judge_model":           ("system_metadata_v1",                 "SYSTEM"),
    "oqj.judge_provider":        ("system_metadata_v1",                 "SYSTEM"),
    "oqj.judge_version":         ("system_metadata_v1",                 "SYSTEM"),
    "oqj.judge_prompt_hash":     ("system_metadata_v1",                 "SYSTEM"),
    "oqj.judge_score":           ("output_quality_normalization_v1",    "MEASURED"),
    "oqj.judge_confidence":      ("output_quality_normalization_v1",    "INFERRED"),  
    # tool_failure_events table
    "tfe.failure_id":            ("system_metadata_v1",             "SYSTEM"),
    "tfe.attempt_id":            ("system_metadata_v1",             "SYSTEM"),
    "tfe.goal_id":               ("system_metadata_v1",             "SYSTEM"),
    "tfe.tool_name":             ("system_metadata_v1",             "SYSTEM"),
    "tfe.failure_type":          ("system_metadata_v1",             "SYSTEM"),
    "tfe.failure_phase":         ("system_metadata_v1",             "SYSTEM"),
    "tfe.retry_attempted":       ("system_metadata_v1",             "SYSTEM"),
    "tfe.retry_success":         ("system_metadata_v1",             "SYSTEM"),
    "tfe.recovery_strategy":     ("system_metadata_v1",             "SYSTEM"),
    "tfe.wasted_energy_uj":      ("tool_failure_wasted_energy_v1",  "CALCULATED"),

    # energy_attribution stub columns — populated by attribution ETL
    "ea.energy_per_accepted_answer_uj":  ("attribution_etl_v1",     "CALCULATED"),
    "ea.energy_per_solved_task_uj":      ("attribution_etl_v1",     "CALCULATED"),

    # goal_execution ETL columns
    "ge.total_energy_uj":        ("goal_execution_rollup_v1",       "CALCULATED"),
    "ge.successful_energy_uj":   ("goal_execution_rollup_v1",       "CALCULATED"),
    "ge.overhead_energy_uj":     ("goal_execution_rollup_v1",       "CALCULATED"),
    "ge.overhead_fraction":      ("goal_overhead_fraction_v1",      "CALCULATED"),
    "ge.orchestration_fraction": ("goal_overhead_fraction_v1",      "CALCULATED"),          
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
    # ── energy_attribution TABLE ──────────────────────────────────────────────
    # Every column in energy_attribution gets full provenance — same rigour as
    # runs table. This table is the primary research output of A-LEMS.
    # method_id "energy_attribution_v1" covers all CALCULATED columns below.
    # L0: Hardware — mirrored from runs RAPL reads
    "ea.pkg_energy_uj":                  ("rapl_msr_pkg_energy",        "MEASURED"),
    "ea.core_energy_uj":                 ("rapl_msr_pkg_energy",        "MEASURED"),
    "ea.dram_energy_uj":                 ("rapl_msr_pkg_energy",        "MEASURED"),
    "ea.uncore_energy_uj":               ("rapl_msr_pkg_energy",        "MEASURED"),
    # L1: System
    "ea.background_energy_uj":           ("energy_attribution_v1",      "CALCULATED"),
    "ea.interrupt_energy_uj":            ("energy_attribution_v1",      "INFERRED"),
    "ea.scheduler_energy_uj":            ("energy_attribution_v1",      "INFERRED"),
    # L2: Resource contention
    "ea.network_wait_energy_uj":         ("energy_attribution_v1",      "INFERRED"),
    "ea.io_wait_energy_uj":              ("energy_attribution_v1",      "INFERRED"),
    "ea.disk_energy_uj":                 ("energy_attribution_v1",      "INFERRED"),
    "ea.memory_pressure_energy_uj":      ("energy_attribution_v1",      "INFERRED"),
    "ea.cache_dram_energy_uj":           ("energy_attribution_v1",      "INFERRED"),
    # L3: Workflow
    "ea.orchestration_energy_uj":        ("energy_attribution_v1",      "CALCULATED"),
    "ea.planning_energy_uj":             ("phase_attribution_cpu_v1",   "CALCULATED"),
    "ea.execution_energy_uj":            ("phase_attribution_cpu_v1",   "CALCULATED"),
    "ea.synthesis_energy_uj":            ("phase_attribution_cpu_v1",   "CALCULATED"),
    "ea.tool_energy_uj":                 ("energy_attribution_v1",      "INFERRED"),
    "ea.retry_energy_uj":                ("attribution_etl_v1",         "CALCULATED"),
    "ea.failed_tool_energy_uj":          ("attribution_etl_v1",         "CALCULATED"),
    "ea.rejected_generation_energy_uj":  ("attribution_etl_v1",         "CALCULATED"),
    # L4: Model compute
    "ea.llm_compute_energy_uj":          ("energy_attribution_v1",      "CALCULATED"),
    "ea.llm_compute_energy_uj":          ("energy_attribution_v1",      "CALCULATED"),
    "ea.attribution_method":             ("energy_attribution_v1",      "SYSTEM"),
    "ea.ml_model_version":               ("ml_energy_estimator_v1",     "SYSTEM"),
    "ea.prefill_energy_uj":              ("energy_attribution_v1",      "INFERRED"),
    "ea.decode_energy_uj":               ("energy_attribution_v1",      "INFERRED"),
    # L5: Outcome normalisation
    "ea.energy_per_completion_token_uj": ("energy_attribution_v1",      "CALCULATED"),
    "ea.energy_per_successful_step_uj":  ("energy_attribution_v1",      "CALCULATED"),
    "ea.energy_per_accepted_answer_uj":  ("energy_attribution_v1",      "CALCULATED"),
    "ea.energy_per_solved_task_uj":      ("energy_attribution_v1",      "CALCULATED"),
    "ttft_ms":                           ("ttft_measurement_v1",        "MEASURED"),
    "tpot_ms":                           ("tpot_measurement_v1",        "MEASURED"),    
    # Thermal + residual
    "ea.thermal_penalty_energy_uj":      ("thermal_penalty_weighted",   "INFERRED"),
    "ea.thermal_penalty_time_ms":        ("thermal_penalty_weighted",   "MEASURED"),
    "ea.unattributed_energy_uj":         ("energy_attribution_v1",      "CALCULATED"),
    "ea.attribution_coverage_pct":       ("energy_attribution_v1",      "CALCULATED"),
 
    # ── normalization_factors TABLE ───────────────────────────────────────────
    # Structural factors (from task config + orchestration_events)
    "nf.difficulty_score":               ("normalization_factors_v1",   "CALCULATED"),
    "nf.difficulty_bucket":              ("normalization_factors_v1",   "CALCULATED"),
    "nf.task_category":                  (None,                         "SYSTEM"),
    "nf.workload_type":                  (None,                         "SYSTEM"),
    "nf.max_step_depth":                 ("normalization_factors_v1",   "MEASURED"),
    "nf.branching_factor":               ("normalization_factors_v1",   "CALCULATED"),
    "nf.input_tokens":                   ("ttft_tpot_wall_clock",       "MEASURED"),
    "nf.output_tokens":                  ("ttft_tpot_wall_clock",       "MEASURED"),
    "nf.context_window_size":            (None,                         "SYSTEM"),
    "nf.total_work_units":               ("normalization_factors_v1",   "CALCULATED"),
    # Behavioural factors (Chunk 8 — NULL until populated)
    "nf.successful_goals":               ("normalization_factors_v1",   "MEASURED"),
    "nf.attempted_goals":                ("normalization_factors_v1",   "MEASURED"),
    "nf.failed_attempts":                ("normalization_factors_v1",   "MEASURED"),
    "nf.retry_depth":                    ("normalization_factors_v1",   "MEASURED"),
    "nf.total_retries":                  ("normalization_factors_v1",   "MEASURED"),
    "nf.total_failures":                 ("normalization_factors_v1",   "MEASURED"),
    "nf.total_tool_calls":               ("normalization_factors_v1",   "MEASURED"),
    "nf.failed_tool_calls":              ("normalization_factors_v1",   "MEASURED"),
    "nf.hallucination_count":            ("normalization_factors_v1",   "MEASURED"),
    "nf.hallucination_rate":             ("normalization_factors_v1",   "CALCULATED"),
    # Resource factors
    "nf.rss_memory_gb":                  ("os_memory_reader",           "MEASURED"),
    "nf.cache_miss_rate":                ("perf_cache_counters",        "CALCULATED"),
    "nf.io_wait_ratio":                  ("disk_io_stats",              "CALCULATED"),
    "nf.stall_time_ms":                  ("normalization_factors_v1",   "INFERRED"),
    "nf.sla_violations":                 ("normalization_factors_v1",   "MEASURED"), 
    # ── v9: Measurement Boundary (Duration Fix) ───────────────────────────────
    # Separates task execution time from A-LEMS instrumentation overhead.
    # See: docs-src/mkdocs/source/research/14-measurement-boundary-methodology.md
    # Paper claim: "A-LEMS measures execution energy, not instrumentation energy"
    "task_duration_ns":           ("measurement_boundary_v1",  "MEASURED"),
    "framework_overhead_ns":      ("measurement_boundary_v1",  "MEASURED"),
    "total_run_duration_ns":      ("measurement_boundary_v1",  "MEASURED"),
    "duration_includes_overhead": (None,                        "SYSTEM"),
    "energy_sample_coverage_pct": ("measurement_coverage_v1",  "CALCULATED"),
    "avg_task_power_watts":       ("measurement_boundary_v1",  "CALCULATED"),
    # Pre-task instrumentation window (diagnostic, not in attribution model)
    # NULL on non-RAPL platforms (macOS, ARM VM) — PAC compliant
    "pre_task_energy_uj":         ("measurement_boundary_v1",  "MEASURED"),
    "pre_task_duration_ns":       ("measurement_boundary_v1",  "MEASURED"),
    # Post-task instrumentation window — stop_measurement() + cleanup cost
    # Regime-separated: uses idle_baselines.package_power_watts, not task baseline
    # NULL on non-RAPL platforms (macOS, ARM VM) — PAC compliant
    "post_task_energy_uj":          ("measurement_boundary_v1",  "MEASURED"),
    "post_task_duration_ns":        ("measurement_boundary_v1",  "MEASURED"),
    # RAPL package counter anchors bounding all three windows
    # rapl_after_task_uj captured AFTER stop_measurement() — prevents overshoot
    "rapl_before_pretask_uj":       ("measurement_boundary_v1",  "MEASURED"),
    "rapl_after_task_uj":           ("measurement_boundary_v1",  "MEASURED"),
    # Total framework energy = pre + post — proves measurement transparency
    "framework_overhead_energy_uj": ("measurement_boundary_v1",  "CALCULATED"),
    # run_quality columns — scored by quality_scorer_v1 post-run

    # run_quality columns — scored by quality_scorer_v1 post-run
    "run_quality.experiment_valid": ("quality_scorer_v1", "CALCULATED"),
    "run_quality.quality_score":    ("quality_scorer_v1", "CALCULATED"),
    "run_quality.rejection_reason": ("quality_scorer_v1", "CALCULATED"),                   
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
    "ge.task_id":     ("goal_tracking_runtime_v1", "SYSTEM"),
    "ge.status":      ("goal_tracking_runtime_v1", "SYSTEM"),
    "ge.started_at":  ("goal_tracking_runtime_v1", "SYSTEM"),
    "ge.finished_at": ("goal_tracking_runtime_v1", "SYSTEM"),
    "ge.updated_at":  ("goal_tracking_runtime_v1", "SYSTEM"),
    "ga.status":      ("goal_tracking_runtime_v1", "SYSTEM"),
    "ga.started_at":  ("goal_tracking_runtime_v1", "SYSTEM"),
    "ga.finished_at": ("goal_tracking_runtime_v1", "SYSTEM"),
    "ga.updated_at":  ("goal_tracking_runtime_v1", "SYSTEM"),
    "eq.entity_type": ("etl_queue_management_v1",  "SYSTEM"),
    "eq.entity_id":   ("etl_queue_management_v1",  "SYSTEM"),
    "eq.etl_name":    ("etl_queue_management_v1",  "SYSTEM"),
    "eq.status":      ("etl_queue_management_v1",  "SYSTEM"),
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
    "energy_attribution_v1":         0.95,   # multi-layer model, residual ~5%
    "thermal_penalty_weighted":      0.85,   # time-weighted thermal penalty
    "normalization_factors_v1":      0.90,   # structural factors high confidence 
    # v9: Measurement Boundary
    "measurement_boundary_v1":       1.0,    # perf_counter — monotonic, all platforms
    "measurement_coverage_v1":       1.0,    # derived from sample timestamps 
    "llm_wait_attribution_v1":  0.85,
    "ml_energy_estimator_v1":   0.0,    # placeholder until Chunk 1.2   
    "ttft_measurement_v1":      1.0,    # perf_counter monotonic, exact
    "tpot_measurement_v1":      0.95,   # derived from token count estimate 
    "quality_scorer_v1":        0.95,   # hard rules exact; soft weights empirical   
    "system_metadata_v1":       1.0,    # experiment classification metadata, no computation   
    "goal_execution_rollup_v1": 1.0,    # sum of run energies per goal, deterministic
    "goal_overhead_fraction_v1":1.0,    # overhead/total ratio, deterministic arithmetic  
    "output_quality_normalization_v1": 0.90,  # stub — seed entry owned by Agent 8.3 
    "hallucination_detection_v1":      0.85,  # detection confidence + similarity signals
    "hallucination_wasted_energy_v1":  0.85,  # energy from attempt start to detection 
    "tool_failure_wasted_energy_v1":   0.90,  # energy consumed by failed tool call
    "attribution_etl_v1":              0.90,  # attribution stub ETL
    "goal_execution_rollup_v1":        1.0,   # sum of attempt energies, deterministic
    "goal_overhead_fraction_v1":       1.0,   # overhead/total ratio, deterministic arithmetic 
    "goal_tracking_runtime_v1": 1.0,
    "etl_queue_management_v1":  1.0,           
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
