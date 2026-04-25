#!/usr/bin/env python3
"""
================================================================================
SEED METHODOLOGY — Populate measurement_method_registry + method_references
================================================================================

Fills ALL columns of measurement_method_registry and method_references.
Three source types:

    READERS         — hardware reader classes (RAPLReader etc.)
    DERIVED_METHODS — computed metrics (CALCULATED/INFERRED, have fn)
    MEASURED_METHODS— non-reader measured methods (no fn, no latexify)

Re-run whenever: code changes, doc updated, new method added.

Usage:
    python scripts/seed_methodology.py
    python scripts/seed_methodology.py --dry-run

Author: Deepak Panigrahy
================================================================================
"""

import argparse
import inspect
import json
import logging
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

BASE     = Path(__file__).resolve().parent.parent
REFS_DIR = BASE / "config" / "methodology_refs"
sys.path.insert(0, str(BASE))

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger(__name__)


# =============================================================================
# READERS — hardware reader classes
# =============================================================================

def _load_readers() -> List[Any]:
    """Import and return all reader classes to seed."""
    from core.readers.rapl_reader                  import RAPLReader
    from core.readers.darwin.iokit_power_reader    import IOKitPowerReader
    from core.readers.fallback.energy_estimator    import EnergyEstimator
    from core.readers.fallback.dummy_energy_reader import DummyEnergyReader
    return [RAPLReader, IOKitPowerReader, EnergyEstimator, DummyEnergyReader]


# =============================================================================
# MEASURED METHODS — direct hardware/OS reads, no compute fn
# No latexify attempted — formula is architectural description
# =============================================================================

def _load_measured_methods() -> List[Dict]:
    """Static measured methods — sensors, clocks, OS readers."""
    return [
        {
            "id":           "system_metadata_v1",
            "name":         "Experiment Classification Metadata",
            "provenance":   "MEASURED",
            "layer":        "orchestration",
            "output_metric":"experiment_type",
            "output_unit":  "category",
            "applicable_on":["any"],
            "formula_latex": r"\text{experiment\_type} \in \{\text{normal, overhead\_study, retry\_study, ...}\}",
            "parameters":   {"values": "VALID_EXPERIMENT_TYPES", "enforcement": "sqlite_trigger"},
            "doc":          "17-experiment-classification-methodology.md",
            "section":      "Experiment Classification Methodology",
        },
        {
            "id":           "perf_counters",
            "name":         "Linux perf Hardware Counters",
            "provenance":   "MEASURED",
            "layer":        "silicon",
            "output_metric":"instructions",
            "output_unit":  "count",
            "applicable_on":["linux_x86_64"],
            "formula_latex": r"N_{inst} = \text{perf\_event\_open}(\text{PERF\_COUNT\_HW\_INSTRUCTIONS})",
            "parameters":   {"interface": "perf_event_open", "syscall": 298},
            "doc":          "01-measurement-methodology.md",
            "section":      "Performance Counter Methodology",
        },
        {
            "id":           "thermal_sensor",
            "name":         "Linux sysfs Thermal Sensor",
            "provenance":   "MEASURED",
            "layer":        "silicon",
            "output_metric":"package_temp_celsius",
            "output_unit":  "°C",
            "applicable_on":["linux_x86_64"],
            "formula_latex": r"T = \frac{\text{sysfs\_millicelsius}}{1000}",
            "parameters":   {"path": "/sys/class/thermal/thermal_zoneN/temp"},
            "doc":          "01-measurement-methodology.md",
            "section":      "Thermal Measurement",
        },
        {
            "id":           "ttft_tpot_wall_clock",
            "name":         "TTFT / TPOT Wall Clock Measurement",
            "provenance":   "MEASURED",
            "layer":        "application",
            "output_metric":"api_latency_ms",
            "output_unit":  "ms",
            "applicable_on":["any"],
            "formula_latex": r"T_{api} = t_{response} - t_{request}",
            "parameters":   {"precision": "perf_counter", "unit": "ms"},
            "doc":          "05-llm-measurement-methodology.md",
            "section":      "Measurement Model",
        },
        {
            "id":           "system_clock",
            "name":         "System Wall Clock",
            "provenance":   "MEASURED",
            "layer":        "application",
            "output_metric":"duration_ns",
            "output_unit":  "ns",
            "applicable_on":["any"],
            "formula_latex": r"\Delta t = t_{end} - t_{start}",
            "parameters":   {"source": "time.time_ns()", "precision_ns": 1},
            "doc":          "01-measurement-methodology.md",
            "section":      "Timestamp Precision",
        },
        {
            "id":           "os_memory_reader",
            "name":         "OS Memory Statistics Reader",
            "provenance":   "MEASURED",
            "layer":        "os",
            "output_metric":"rss_memory_mb",
            "output_unit":  "MB",
            "applicable_on":["any"],
            "formula_latex": r"M_{RSS} = \frac{\text{VmRSS}}{1024}",
            "parameters":   {"source": "psutil.Process().memory_info()"},
            "doc":          "01-measurement-methodology.md",
            "section":      "Measurement Modes",
        },
        {
            "id":           "network_measurement",
            "name":         "Network I/O Measurement",
            "provenance":   "MEASURED",
            "layer":        "os",
            "output_metric":"bytes_sent",
            "output_unit":  "bytes",
            "applicable_on":["any"],
            "formula_latex": r"\Delta B = B_{end} - B_{start}",
            "parameters":   {"source": "psutil.net_io_counters()"},
            "doc":          "05-llm-measurement-methodology.md",
            "section":      "Network Metrics",
        },
        {
            "id":           "turbostat_reader",
            "name":         "Intel Turbostat CPU Frequency Reader",
            "provenance":   "MEASURED",
            "layer":        "silicon",
            "output_metric":"frequency_mhz",
            "output_unit":  "MHz",
            "applicable_on":["linux_x86_64"],
            "formula_latex": r"f = \text{turbostat Avg\_MHz}",
            "parameters":   {"tool": "turbostat", "interval_ms": 100},
            "doc":          "01-measurement-methodology.md",
            "section":      "Performance Counter Methodology",
        },
        {
            "id":           "os_scheduler_reader",
            "name":         "OS Scheduler Statistics Reader",
            "provenance":   "MEASURED",
            "layer":        "os",
            "output_metric":"context_switches_voluntary",
            "output_unit":  "count",
            "applicable_on":["linux_x86_64"],
            "formula_latex": r"CS = \text{/proc/[pid]/status voluntary\_ctxt\_switches}",
            "parameters":   {"source": "/proc/[pid]/status"},
            "doc":          "01-measurement-methodology.md",
            "section":      "Measurement Modes",
        },
        {
            "id":           "msr_reader",
            "name":         "MSR C-State Register Reader",
            "provenance":   "MEASURED",
            "layer":        "silicon",
            "output_metric":"c2_time_seconds",
            "output_unit":  "s",
            "applicable_on":["linux_x86_64"],
            "formula_latex": r"C_x = \frac{\Delta MSR_{C_x}}{TSC_{freq}}",
            "parameters":   {
                "c2_msr": "0x60D",
                "c3_msr": "0x3FC",
                "c6_msr": "0x3FD",
                "c7_msr": "0x3FE",
            },
            "doc":          "01-measurement-methodology.md",
            "section":      "C-State Measurement",
        },
        {
            "id":           "perf_cache_counters",
            "name":         "Perf Cache Counters",
            "provenance":   "MEASURED",
            "layer":        "silicon",
            "confidence":   1.0,
            "description":  "L1d/L2/L3 cache hit and miss counters from Linux perf_events via perf stat. Events: L1-dcache-load-misses, l2_rqsts.miss, LLC-loads, LLC-load-misses.",
            "formula_latex": r"\text{perf\_stat}(L1\text{-}dcache\text{-}load\text{-}misses,\ l2\_rqsts.miss,\ LLC\text{-}loads,\ LLC\text{-}load\text{-}misses)",
            "parameters":   {"sampling": "once per run", "source": "perf_event_open", "unit": "event_count", "cache_line_bytes": 64},
            "doc":          "09-derived-metrics-methodology.md",
            "section":      "Hardware Telemetry Metrics (Chunk 12)",
        },
        {
            "id":           "disk_io_stats",
            "name":         "Disk I/O Statistics",
            "provenance":   "MEASURED",
            "layer":        "os",
            "confidence":   1.0,
            "description":  "Disk read/write bytes and latency from /proc/diskstats. Delta between run start and end snapshots. Sector count * 512 = bytes.",
            "formula_latex": r"\Delta bytes = (\text{sectors}_{end} - \text{sectors}_{start}) \times 512",
            "parameters":   {"source": "/proc/diskstats", "sector_size": 512},
            "doc":          "09-derived-metrics-methodology.md",
            "section":      "Hardware Telemetry Metrics (Chunk 12)",
        },
        {
            "id":           "disk_io_stats",
            "name":         "Disk I/O Statistics",
            "provenance":   "MEASURED",
            "layer":        "os",
            "confidence":   1.0,
            "description":  "Disk read/write bytes and latency from /proc/diskstats. Delta between run start and end snapshots. Sector count * 512 = bytes.",
            "formula_latex": r"\Delta bytes = (\text{sectors}_{end} - \text{sectors}_{start}) \times 512",
            "parameters":   {"source": "/proc/diskstats", "sector_size": 512},
            "doc":          "09-derived-metrics-methodology.md",
            "section":      "Hardware Telemetry Metrics (Chunk 12)",
        },

    ]


# =============================================================================
# DERIVED METHODS — CALCULATED/INFERRED, have specific compute fn
# fn points to SPECIFIC function — not a 200-line general compute()
# =============================================================================

def _load_derived_methods() -> List[Dict]:
    """Derived method definitions with specific compute functions."""
    from core.analysis.energy_analyzer  import EnergyAnalyzer
    from core.sustainability.calculator import SustainabilityCalculator
    from core.execution.agentic         import AgenticExecutor

    return [
        {
            "id":           "goal_execution_rollup_v1",
            "name":         "Goal Execution Energy Rollup",
            "provenance":   "CALCULATED",
            "layer":        "orchestration",
            "confidence":   1.0,
            "description":  "Aggregates attempt-level energies into goal-level totals. total_energy_uj = sum of all attempts. successful_energy_uj = winning attempt only. overhead_energy_uj = total - successful.",
            "formula_latex": r"E_{total} = \sum_{i=1}^{N} E_{attempt_i}, \quad E_{overhead} = E_{total} - E_{success}",
            "parameters":   {"etl_script": "goal_execution_etl.py", "insert_as": "NULL"},
            "doc":          "18-goal-execution-methodology.md",
            "section":      "Goal Execution and Overhead Fraction Methodology",
        },
        {
            "id":           "goal_overhead_fraction_v1",
            "name":         "Goal Overhead and Orchestration Fraction",
            "provenance":   "CALCULATED",
            "layer":        "orchestration",
            "confidence":   1.0,
            "description":  "Computes overhead_fraction (wasted energy ratio) and orchestration_fraction (orchestration share of winning run). Core metrics for paper thesis.",
            "formula_latex": r"f_{overhead} = \frac{E_{overhead}}{E_{total}}, \quad f_{orchestration} = \frac{E_{orchestration}}{E_{success}}",
            "parameters":   {"etl_script": "goal_execution_etl.py", "source": "energy_attribution.orchestration_energy_uj"},
            "doc":          "18-goal-execution-methodology.md",
            "section":      "Goal Execution and Overhead Fraction Methodology",
        },
        {
            "id":           "hallucination_detection_v1",
            "name":         "Hallucination Detection",
            "provenance":   "INFERRED",
            "layer":        "orchestration",
            "confidence":   0.85,
            "description":  "Classifies LLM outputs as hallucinatory using detection_method (exact_match, semantic_similarity, llm_judge, unit_test, human_review). Records detection_confidence and semantic_similarity as evidence signals. hallucination_type governed by core/ontology_registry.py.",
            "formula_latex": r"\text{detection\_confidence} \in [0,1], \quad \text{semantic\_similarity} = \cos(\vec{e}_{expected}, \vec{e}_{actual})",
            "parameters":   {"ontology": "core/ontology_registry.py", "version": "1.0.0"},
            "doc":          "19-hallucination-output-quality-methodology.md",
            "section":      "Hallucination Detection Methodology",
        },
        {
            "id":           "hallucination_wasted_energy_v1",
            "name":         "Hallucination Wasted Energy",
            "provenance":   "CALCULATED",
            "layer":        "orchestration",
            "confidence":   0.85,
            "description":  "Computes energy wasted per hallucination event: energy consumed from attempt start until hallucination detected. Populated by energy_attribution_etl.py.",
            "formula_latex": r"E_{wasted} = E_{attempt\_start \to detected}",
            "parameters":   {"etl_script": "energy_attribution_etl.py", "source": "orchestration_events.event_energy_uj"},
            "doc":          "19-hallucination-output-quality-methodology.md",
            "section":      "Hallucination Wasted Energy Methodology",
        },
        {
            "id":           "output_quality_normalization_v1",
            "name":         "Output Quality Normalization",
            "provenance":   "CALCULATED",
            "layer":        "orchestration",
            "confidence":   0.90,
            "description":  "Reconciles N judge scores into a single normalized_score using tie-break logic: agreement>=0.8 averaged, >=0.5 conservative_min, <0.5 needs_review. agreement_score = 1 - ABS(score_a - score_b) for two judges, normalized std for N judges.",
            "formula_latex": r"\text{agreement} = 1 - |s_1 - s_2|, \quad s_{norm} = \begin{cases} \bar{s} & \text{agreement} \geq 0.8 \\ \min(s) & \text{agreement} \geq 0.5 \\ \text{NULL} & \text{otherwise} \end{cases}",
            "parameters":   {"child_table": "output_quality_judges", "judge_count_field": "judge_count"},
            "doc":          "19-hallucination-output-quality-methodology.md",
            "section":      "Output Quality Normalization Methodology",
        },  
        {
            "id":            "goal_tracking_runtime_v1",
            "name":          "Goal Tracking Runtime Wiring",
            "provenance":    "SYSTEM",
            "layer":         "application",
            "confidence":    1.0,
            "description":   (
                "Records goal_execution and goal_attempt rows at experiment "
                "runtime. GoalTracker owns all state transitions. "
                "experiment_runner calls GoalTracker — never writes goal tables directly."
            ),
            "formula_latex": r"\text{goal\_id} \leftarrow \text{INSERT on experiment start}",
            "parameters":    {},
            "doc":           "21-goal-tracking-runtime.md",
            "section":       "Goal Tracking Runtime",           
        },
        {
            "id":            "etl_queue_management_v1",
            "name":          "ETL Queue Management",
            "provenance":    "SYSTEM",
            "layer":         "application",
            "confidence":    1.0,
            "description":   (
                "Table-backed queue for decoupled ETL execution. "
                "Runner enqueues pending entries after save_pair(). "
                "ETL runner reads etl_queue and processes entries independently."
            ),
            "formula_latex": r"\text{queue} \leftarrow \text{pending} \rightarrow \text{done}",
            "parameters":    {},
            "doc":           "21-goal-tracking-runtime.md",
            "section":       "ETL Queue Management",         
        },        
        {
            "id":           "tool_failure_wasted_energy_v1",
            "name":         "Tool Failure Wasted Energy",
            "provenance":   "CALCULATED",
            "layer":        "orchestration",
            "confidence":   0.90,
            "description":  "Energy consumed by a failed tool call. Source: orchestration_events.event_energy_uj when event is linked, otherwise inferred from attempt energy fraction. Populated by energy_attribution_etl.py.",
            "formula_latex": r"E_{wasted} = E_{\text{tool call start} \to \text{failure detected}}",
            "parameters":   {"etl_script": "energy_attribution_etl.py", "source": "orchestration_events.event_energy_uj"},
            "doc":          "20-tool-failure-methodology.md",
            "section":      "Tool Failure Wasted Energy Methodology",
        },
        {
            "id":           "attribution_etl_v1",
            "name":         "Chunk 8 Attribution ETL",
            "provenance":   "CALCULATED",
            "layer":        "orchestration",
            "confidence":   0.90,
            "description":  "Populates 5 stub columns in energy_attribution: retry_energy_uj, failed_tool_energy_uj, rejected_generation_energy_uj, energy_per_accepted_answer_uj, energy_per_solved_task_uj. Also backfills hallucination_count, hallucination_rate, failed_tool_calls in normalization_factors.",
            "formula_latex": r"E_{retry} = \sum_{k>1} E_{attempt_k}, \quad E_{per\_solved} = E_{successful} / N_{solved}",
            "parameters":   {"etl_script": "energy_attribution_etl.py", "acceptance_threshold": 0.7, "threshold_method": "output_quality_normalization_v1"},
            "doc":          "20-tool-failure-methodology.md",
            "section":      "Attribution ETL Methodology",
        },              
        {
            "id":           "dynamic_energy_calculation",
            "name":         "Dynamic Energy Calculation",
            "provenance":   "CALCULATED",
            "layer":        "silicon",
            "output_metric":"dynamic_energy_uj",
            "output_unit":  "µJ",
            "applicable_on":["any"],
            "formula_latex": r"E_{dyn} = \max(0, E_{pkg} - E_{idle})",
            "parameters":   {"method": "min_baseline_2sigma", "percentile": 2},
            "doc":          "02-mathematical-derivations.md",
            "section":      "Workload Isolation",
            "fn":           EnergyAnalyzer.compute,
        },
        {
            "id":           "ipc_calculation",
            "name":         "Instructions Per Cycle (IPC)",
            "provenance":   "CALCULATED",
            "layer":        "silicon",
            "output_metric":"ipc",
            "output_unit":  "ratio",
            "applicable_on":["linux_x86_64"],
            "formula_latex": r"IPC = \frac{N_{instructions}}{N_{cycles}}",
            "parameters":   {"counter": "perf_event_open"},
            "doc":          "02-mathematical-derivations.md",
            "section":      "Efficiency Metrics",
            "fn":           None,   # no specific sub-method — formula is self-contained
        },
        {
            "id":           "cache_miss_calculation",
            "name":         "LLC Cache Miss Rate",
            "provenance":   "CALCULATED",
            "layer":        "silicon",
            "output_metric":"cache_miss_rate",
            "output_unit":  "%",
            "applicable_on":["linux_x86_64"],
            "formula_latex": r"\%_{miss} = \frac{N_{LLC\_miss}}{N_{LLC\_ref}} \times 100",
            "parameters":   {"counter": "LLC-load-misses"},
            "doc":          "02-mathematical-derivations.md",
            "section":      "Efficiency Metrics",
            "fn":           None,   # formula is self-contained
        },
        {
            "id":           "orchestration_tax_calculation",
            "name":         "Orchestration Tax Calculation",
            "provenance":   "CALCULATED",
            "layer":        "orchestration",
            "output_metric":"orchestration_tax_uj",
            "output_unit":  "µJ",
            "applicable_on":["any"],
            "formula_latex": r"\tau = E_{agentic} - E_{linear}",
            "parameters":   {},
            "doc":          "03-orchestration-tax.md",
            "section":      "Orchestration Tax",
            "fn":           EnergyAnalyzer.compute,
        },
        {
            "id":           "efficiency_metrics_calculation",
            "name":         "Energy Efficiency Metrics",
            "provenance":   "CALCULATED",
            "layer":        "application",
            "output_metric":"energy_per_token",
            "output_unit":  "µJ/unit",
            "applicable_on":["any"],
            "formula_latex": r"\epsilon = \frac{E_{pkg}}{N_{units}} \quad \text{where } N_{units} \in \{tokens, instructions, cycles\}",
            "parameters":   {},
            "doc":          "02-mathematical-derivations.md",
            "section":      "Efficiency Metrics",
            "fn":           None,   # self-contained ratio formula
        },
        {
            "id":           "carbon_calculation",
            "name":         "Carbon Emission Calculation",
            "provenance":   "INFERRED",
            "layer":        "application",
            "output_metric":"carbon_g",
            "output_unit":  "g",
            "applicable_on":["any"],
            "formula_latex": r"C = E_{pkg} \cdot I_{carbon} \cdot 10^3",
            "parameters":   {"source": "Ember 2026", "unit": "g CO2/kWh"},
            "doc":          "02-mathematical-derivations.md",
            "section":      "Efficiency Metrics",
            "fn":           SustainabilityCalculator.calculate_from_raw,
        },
        {
            "id":           "water_calculation",
            "name":         "Water Consumption Calculation",
            "provenance":   "INFERRED",
            "layer":        "application",
            "output_metric":"water_ml",
            "output_unit":  "ml",
            "applicable_on":["any"],
            "formula_latex": r"W = E_{pkg} \cdot WUE \cdot 10^3",
            "parameters":   {"source": "UN-Water 2025", "unit": "L/kWh"},
            "doc":          "02-mathematical-derivations.md",
            "section":      "Efficiency Metrics",
            "fn":           SustainabilityCalculator.calculate_from_raw,
        },
        {
            "id":           "methane_calculation",
            "name":         "Methane Emission Calculation",
            "provenance":   "INFERRED",
            "layer":        "application",
            "output_metric":"methane_mg",
            "output_unit":  "mg",
            "applicable_on":["any"],
            "formula_latex": r"CH_4 = E_{pkg} \cdot I_{methane} \cdot 10^3",
            "parameters":   {"source": "IEA 2026", "gwp_20yr": 86, "gwp_100yr": 34},
            "doc":          "02-mathematical-derivations.md",
            "section":      "Efficiency Metrics",
            "fn":           SustainabilityCalculator.calculate_from_raw,
        },

                {
            "id":           "idle_baseline_cpu_pinning_2sigma",
            "name":         "Idle Baseline with CPU Pinning and 2-Sigma",
            "provenance":   "MEASURED",
            "layer":        "silicon",
            "output_metric":"baseline_energy_uj",
            "output_unit":  "µJ",
            "applicable_on":["linux_x86_64"],
            "formula_latex": r"E_{idle} = \max(0, \bar{P} - 2\sigma) \times t_{duration}",
            "parameters":   {
                "pinned_cores":    [0, 1],
                "duration_seconds": 10,
                "num_samples":      10,
                "sigma_threshold":  2.0,
                "method":          "min_2sigma_baseline",
            },
            "doc":          "07-energy-readers-methodology.md",
            "section":      "RAPL Energy Measurement",
            "fn":           None,
        },
        {
            "id":            "cpu_fraction_attribution",
            "name":          "CPU Fraction-Based Energy Attribution",
            "provenance":    "CALCULATED",
            "layer":         "os",
            "confidence":    0.95,
            "description":   (
                "Attributes dynamic energy to the workload process by multiplying "
                "system-wide dynamic energy by the fraction of CPU ticks consumed "
                "by the workload PID. Tick counts are read from /proc/stat (total) "
                "and /proc/[pid]/stat (workload) at experiment start and end. "
                "Isolates workload energy from background processes (cron, sshd, systemd)."
            ),
            "formula_latex": (
                r"E_{attr} = \frac{\Delta ticks_{pid}}{\Delta ticks_{total}} \times E_{dyn}"
            ),
            "parameters":    {
                "tick_source_total":    "/proc/stat fields: user+nice+system",
                "tick_source_process":  "/proc/[pid]/stat fields: utime+stime",
                "energy_source":        "dynamic_energy_uj (pkg minus idle baseline)",
            },
            "fn":            "proc_reader.compute_cpu_fraction",
            "doc":           "09-derived-metrics-methodology.md",
            "section":       "CPU Fraction Attribution",
        },        

        {
            "id":           "complexity_score_calculation",
            "name":         "Orchestration Complexity Score",
            "provenance":   "CALCULATED",
            "layer":        "orchestration",
            "output_metric":"complexity_score",
            "output_unit":  "ratio",
            "applicable_on":["any"],
            "formula_latex": r"S = \alpha \cdot \hat{L} + \beta \cdot \hat{T} + \gamma \cdot \hat{N}",
            "parameters":   {
                "alpha": 0.4, "beta": 0.3, "gamma": 0.3,
                "max_llm_calls": 10, "max_tool_calls": 10,
                "token_threshold": 1000,
            },
            "doc":          "03-orchestration-tax.md",
            "section":      "Orchestration Tax",
            "fn":           AgenticExecutor._calculate_complexity_score,
        },
        {
            "id":           "phase_attribution_cpu_v1",
            "name":         "Phase Attribution (CPU-only, Normalized Signal Weighting)",
            "provenance":   "CALCULATED",
            "layer":        "orchestration",
            "confidence":   0.95,
            "description":  (
                "Per-phase energy attribution using normalized CPU signal weighting. "
                "Guarantees: planning + execution + synthesis == attributed_energy_uj. "
                "Step 1: score_i = cpu_fraction_i x raw_energy_i. "
                "Step 2: weight_i = score_i / sum(scores). "
                "Step 3: E_phase_i = weight_i x attributed_energy_uj. "
                "CPU fraction from /proc/[pid]/stat and /proc/stat counter deltas (MAX-MIN). "
                "Raw energy from RAPL energy_samples MAX(pkg_end_uj) - MIN(pkg_start_uj)."
            ),
            "formula_latex": (
                r"S_i = f_i \times E_{raw,i},\quad"
                r"w_i = \frac{S_i}{\sum_j S_j},\quad"
                r"E_{phase,i} = w_i \times E_{attributed}"
            ),
            "parameters": {
                "energy_sample_rate_hz":  100,
                "cpu_sample_rate_hz":     10,
                "counter_delta_method":   "max_min",
                "normalization":          "signal_weighted",
                "clamp_range":            [0, 1],
                "fallback":               "run_level_cpu_fraction",
                "residual_policy":        "add_to_largest_phase",
            },
            "fn":      "phase_attribution_etl.compute_phase_attribution",
            "doc":     "09-derived-metrics-methodology.md",
            "section": "Phase Energy Attribution",
        },
        # ── Chunk 6: Energy Attribution ───────────────────────────────────────────
        {
            "id":            "energy_attribution_v1",
            "name":          "Multi-Layer Energy Attribution v1",
            "provenance":    "CALCULATED",
            "layer":         "os",
            "confidence":    0.95,
            "description":   (
                "Decomposes total pkg energy into five attribution layers: "
                "L0 hardware (RAPL domains), L1 system overhead (background, "
                "interrupts, scheduler), L2 resource contention (network wait, "
                "I/O wait, memory pressure, cache-DRAM), L3 workflow "
                "(orchestration, planning, execution, synthesis, tools, retries), "
                "L4 model compute (LLM application fraction via UCR), and L5 "
                "outcome normalisation (energy per token/step/answer/task). "
                "UCR (utilisation compute ratio) = compute_time_ms / duration_ms. "
                "Application energy = attributed × UCR. "
                "Orchestration energy = attributed − application. "
                "Unattributed residual = pkg − Σ all layers."
            ),
            "formula_latex": (
                r"E_{total} = E_{core} + E_{dram} + E_{uncore} + E_{background}"
                r" + E_{network} + E_{io} + E_{orchestration} + E_{application}"
                r" + E_{thermal} + E_{unattributed}"
            ),
            "parameters":    {
                "ucr_formula":          "compute_time_ms / duration_ms",
                "application_formula":  "attributed_energy × ucr",
                "background_formula":   "max(0, pkg - core - dram - orchestration - application - network - io)",
                "unattributed_formula": "max(0, pkg - Σ_all_layers)",
                "model_version":        "v1",
            },
            "doc":           "12-energy-attribution-methodology.md",
            "section":       "Attribution Model v1",
        },
    
        # ── Chunk 6: Thermal Penalty ──────────────────────────────────────────────
        {
            "id":            "thermal_penalty_weighted",
            "name":          "Time-Weighted Thermal Penalty",
            "provenance":    "INFERRED",
            "layer":         "silicon",
            "confidence":    0.85,
            "description":   (
                "Estimates energy wasted due to CPU thermal throttling. "
                "Only time intervals where cpu_temp > 85°C contribute. "
                "throttle_ratio = Σ(interval_ns | temp>85) / Σ(all interval_ns). "
                "penalty = pkg_energy × throttle_ratio × 0.20. "
                "The 0.20 (20%) factor is an empirical estimate of frequency "
                "reduction at thermal throttle on Intel x86. "
                "Source: thermal_samples table, cpu_temp and interval columns."
            ),
            "formula_latex": (
                r"E_{thermal} = E_{pkg} \times"
                r" \frac{\sum_{i: T_i > 85} \Delta t_i}{\sum_i \Delta t_i}"
                r" \times 0.20"
            ),
            "parameters":    {
                "threshold_c":          85.0,
                "penalty_fraction":     0.20,
                "interval_source":      "thermal_samples.sample_end_ns - sample_start_ns",
                "temp_source":          "thermal_samples.cpu_temp",
            },
            "doc":           "12-energy-attribution-methodology.md",
            "section":       "Thermal Penalty Model",
        },
    
        # ── Chunk 6: Normalization Factors ────────────────────────────────────────
        {
            "id":            "normalization_factors_v1",
            "name":          "Run Normalisation Factor Computation",
            "provenance":    "CALCULATED",
            "layer":         "application",
            "confidence":    0.90,
            "description":   (
                "Computes structural and behavioural normalisation factors for "
                "each run, enabling apples-to-apples energy comparison across "
                "tasks of different difficulty, depth, and retry behaviour. "
                "Structural factors (difficulty_score, max_step_depth, "
                "branching_factor, total_work_units) are derived from task config "
                "and orchestration_events. "
                "Behavioural factors (successful_goals, attempted_goals, "
                "total_retries, hallucination_rate) require Chunk 8 tables "
                "(query_execution, query_attempt, hallucination_events). "
                "total_work_units = input_tokens × max_step_depth × branching_factor."
            ),
            "formula_latex": (
                r"W_{total} = T_{input} \times D_{max} \times B_{avg}"
            ),
            "parameters":    {
                "total_work_units_formula": "input_tokens × max_step_depth × branching_factor",
                "difficulty_bucket_thresholds": {
                    "easy":      "score < 0.25",
                    "medium":    "0.25 ≤ score < 0.50",
                    "hard":      "0.50 ≤ score < 0.75",
                    "very_hard": "score ≥ 0.75",
                },
                "chunk8_dependency": "successful_goals, attempted_goals, retries, hallucinations",
            },
            "doc":           "13-normalization-factors-methodology.md",
            "section":       "Normalisation Factor Taxonomy",
        },
        # ── v9: Measurement Boundary ──────────────────────────────────────────────
        {
            "id":            "measurement_boundary_v1",
            "name":          "Task vs Framework Duration Boundary",
            "provenance":    "MEASURED",
            "layer":         "os",
            "confidence":    1.0,
            "description":   (
                "Separates the run wall-clock into three explicit windows using "
                "the t0/t1/t2 timestamp model. "
                "t0 = run_start_perf (before start_measurement, after pre-task reads). "
                "t1 = task_end_perf (immediately after executor.execute returns). "
                "t2 = run_end_perf (after all post-processing). "
                "task_duration_ns = t1-t0: executor time only — canonical denominator "
                "for all energy-per-time calculations. "
                "framework_overhead_ns = t2-t1: A-LEMS instrumentation cost "
                "(stop_measurement cleanup, sample processing, metric aggregation). "
                "An additional pre-task window is captured for diagnostic purposes: "
                "pre_task_energy_uj = RAPL delta during interrupt/temperature/governor "
                "reads that precede start_measurement(). This is NOT part of the "
                "attribution model — it is instrumentation overhead. "
                "Core paper claim: A-LEMS measures execution energy, not "
                "instrumentation energy. "
                "Prior benchmarking tools that capture t_end after monitoring teardown "
                "inflate duration by up to 50%% for agentic workloads. "
                "Uses time.perf_counter() — platform agnostic, monotonic, "
                "nanosecond resolution. PAC compliant: works on Linux x86, "
                "Linux ARM, macOS, Windows."
            ),
            "formula_latex": (
                # Duration windows — time.perf_counter() anchors
                r"t_{pre} = t_0 - t_{before}, \quad"
                r"t_{task} = t_1 - t_0, \quad"
                r"t_{post} = t_2 - t_1, \quad"
                r"t_{total} = t_{pre} + t_{task} + t_{post} \\"
                # Corrected power — task window only
                r"\bar{P}_{task} = \frac{E_{pkg}}{t_{task}}, \quad"
                r"\tau_{framework} = \frac{t_{pre} + t_{post}}{t_{task}} \\"
                # Pre-task energy — idle regime
                r"E_{pre} = \max\!\left(0,\ \bigl(RAPL(t_0) - RAPL(t_{before})\bigr)"
                r" - P_{idle} \cdot t_{pre}\right) \times f_{cpu,pre} \\"
                # Post-task energy — idle regime
                r"E_{post} = \max\!\left(0,\ \bigl(RAPL(t_2) - RAPL(t_1)\bigr)"
                r" - P_{idle} \cdot t_{post}\right) \times f_{cpu,post} \\"
                # Framework overhead energy
                r"E_{framework} = E_{pre} + E_{post}"
            ),
            "parameters":    {
                "t_before": "_pre_task_start_perf — before instrumentation reads",
                "t0":       "run_start_perf — before start_measurement()",
                "t1":       "task_end_perf — immediately after executor.execute() returns",
                "t2":       "run_end_perf — after stop_measurement() and all post-processing",
                "RAPL_t0":  "MIN(energy_samples.pkg_start_uj) — first energy sample anchor",
                "RAPL_t1":  "rapl_after_task_uj — read AFTER stop_measurement() to prevent MAX(pkg_end_uj) overshoot",
                "RAPL_t_before": "rapl_before_pretask_uj — raw pkg counter before pre-task reads",
                "P_idle":   "idle_baselines.package_power_watts — measured idle power, NOT task-era baseline",
                "f_cpu_pre":  "/proc/stat ticks ratio for A-LEMS process during pre window",
                "f_cpu_post": "/proc/stat ticks ratio for A-LEMS process during post window",
                "regime_note": "Overhead windows use idle baseline — regime-separated from task window",
                "timer":    "time.perf_counter() — monotonic, nanosecond resolution, all platforms",
                "rapl_domain": "package-0 — full socket energy including CPU+uncore+DRAM",
                "platform_note": "All energy columns NULL on non-RAPL platforms (macOS, ARM VM) — PAC compliant",
                "historical_runs": "task_duration_ns estimated from energy_samples span for pre-v9 runs",
                "total_run_duration": "pre + task + post — fixed in v3, previously missing pre window",
            },
            "doc":           "14-measurement-boundary-methodology.md",
            "section":       "Task Duration Model and Framework Overhead Energy",
        },
    
        # ── v9: Measurement Coverage ──────────────────────────────────────────────
        {
            "id":            "measurement_coverage_v1",
            "name":          "Energy Sample Coverage Metric",
            "provenance":    "CALCULATED",
            "layer":         "os",
            "confidence":    1.0,
            "description":   (
                "Quantifies what fraction of task execution time is covered by "
                "energy_samples. At 100Hz sampling, a 5-second run should have "
                "~500 samples spanning the full task duration. "
                "coverage_pct = (MAX(sample_end_ns) - MIN(sample_start_ns)) "
                "/ task_duration_ns × 100. "
                "Thresholds: gold ≥95%%, acceptable 80-95%%, poor <80%%. "
                "Runs with poor coverage are excluded from research views by default. "
                "Historical pre-v9 runs: expected ~48-50%% coverage due to measurement "
                "boundary bug (energy sampler stopped at executor return but "
                "duration_ns included post-processing time). "
                "Post-v9 new runs: expected >95%% coverage."
            ),
            "formula_latex": (
                r"C = \frac{t_{last\_sample} - t_{first\_sample}}{t_{task}} \times 100"
            ),
            "parameters":    {
                "gold_threshold":       ">=95%",
                "acceptable_threshold": "80-95%",
                "poor_threshold":       "<80%",
                "exclusion_policy":     "research views WHERE energy_sample_coverage_pct >= 80",
                "historical_coverage":  "~48-50% (pre-v9 runs)",
                "expected_new":         ">95% (post-v9 runs)",
            },
            "doc":           "14-measurement-boundary-methodology.md",
            "section":       "Measurement Coverage Validation",
        },

# ── v10: LLM Wait Energy Attribution ─────────────────────────────────────
        {
            "id":            "llm_wait_attribution_v1",
            "name":          "LLM API Wait Energy Attribution",
            "provenance":    "CALCULATED",
            "layer":         "application",
            "confidence":    0.85,
            "description":   (
                "Energy consumed during LLM API blocking wait. "
                "Computed as attributed_energy × (api_latency_ms / task_duration_ms). "
                "Novel metric: prior tools miss this energy since process is not CPU-active. "
                "During API wait, process power ~12.9W (sub-active), above idle (3-5W) "
                "but below active compute (33W). Empirically ~48% of agentic run time."
            ),
            "formula_latex": (
                r"E_{llm\_wait} = E_{attr} \times \frac{t_{api}}{t_{task}}"
            ),
            "parameters":    {
                "source_column":    "llm_interactions.api_latency_ms",
                "base_energy":      "attributed_energy_uj",
                "confidence_note":  "INFERRED time-fraction; power assumed constant during wait",
                "typical_fraction": "~48% agentic, ~49% linear",
            },
            "doc":           "15-llm-wait-energy-finding.md",
            "section":       "LLM Wait Energy Attribution Formula",
        },
        # ── v10: ML Energy Estimator Provision ───────────────────────────────────
        {
            "id":            "ml_energy_estimator_v1",
            "name":          "ML Model Energy Estimator (Provision)",
            "provenance":    "INFERRED",
            "layer":         "application",
            "confidence":    0.0,
            "description":   (
                "Placeholder for Chunk 1.2 ARM ML-based energy estimator. "
                "Will replace cpu_fraction_v1 on ARM platforms where RAPL is unavailable. "
                "Uses performance counters as features to estimate energy consumption."
            ),
            "formula_latex": (
                r"E_{est} = f_{ml}(\text{perf\_counters})"
            ),
            "parameters":    {
                "status":       "not_implemented",
                "target_chunk": "1.2",
                "platform":     "aarch64",
            },
            "doc":           "15-llm-wait-energy-finding.md",
            "section":       "Future Work",
        },
        {
            "id":            "ttft_measurement_v1",
            "name":          "Time to First Token Measurement",
            "provenance":    "MEASURED",
            "layer":         "application",
            "confidence":    1.0,
            "description":   (
                "Wall-clock time from request send to first token received. "
                "Streaming only — NULL for non-streaming calls. "
                "Provisioned Chunk 7, populated Chunk 4."
            ),
            "formula_latex": (
                r"TTFT = t_{first\_token} - t_{request\_sent}"
            ),
            "parameters":    {},
            "doc":           "09-derived-metrics-methodology.md",
            "section":       "Streaming Latency Metrics",
        },
        {
            "id":            "tpot_measurement_v1",
            "name":          "Time Per Output Token Measurement",
            "provenance":    "MEASURED",
            "layer":         "application",
            "confidence":    0.95,
            "description":   (
                "Mean inter-token latency after first token. "
                "(total_time - ttft) / (completion_tokens - 1). "
                "Streaming only — NULL for non-streaming calls."
            ),
            "formula_latex": (
                r"TPOT = \frac{T_{total} - TTFT}{N_{tokens} - 1}"
            ),
            "parameters":    {},
            "doc":           "09-derived-metrics-methodology.md",
            "section":       "Streaming Latency Metrics",
        },
            {
            "id":            "quality_scorer_v1",
            "name":          "Run Quality Scorer",
            "provenance":    "CALCULATED",
            "layer":         "system",
            "confidence":    0.95,
            "output_metric": "quality_score",
            "output_unit":   "score",
            "applicable_on": ["any"],
            "formula_latex": (
                r"Q = \max\!\left(0,\; 1 - \sum_{i} w_i p_i\right)"
            ),
            "parameters":    {"config": "config/quality.yaml", "version": 1},
            "doc":           "16-run-quality-methodology.md",
            "section":       "Run Quality Scoring",
            "fn":            None,
        },
            {
            "id":            "failure_classification_v1",
            "name":          "Failure Type Classifier",
            "provenance":    "CALCULATED",
            "layer":         "orchestration",
            "confidence":    0.85,
            "output_metric": "failure_type",
            "output_unit":   "category",
            "applicable_on": ["goal_attempt"],
            "formula_latex": r"T_{failure} = \text{classify}(exc, result)",
            "parameters":    {"version": 1},
            "doc":           "22-retry-tool-failure-methodology.md",
            "section":       "Failure Classification",
            "fn":            None,
        },
        {
            "id":            "failure_injection_v1",
            "name":          "Deterministic Failure Injector",
            "provenance":    "CALCULATED",
            "layer":         "orchestration",
            "confidence":    1.0,
            "output_metric": "tool_failure_events.error_message",
            "output_unit":   "flag",
            "applicable_on": ["tool_failure_events"],
            "formula_latex": r"seed = \text{hash}(tool, run\_id, attempt) \bmod 2^{32}",
            "parameters":    {"version": 1},
            "doc":           "22-retry-tool-failure-methodology.md",
            "section":       "Failure Injection",
            "fn":            None,
        },        
    ]


# =============================================================================
# LOADERS
# =============================================================================

def _load_doc_map() -> Dict[str, Dict]:
    """Load config/methodology_docs.yaml."""
    yaml_path = BASE / "config" / "methodology_docs.yaml"
    if not yaml_path.exists():
        logger.warning("methodology_docs.yaml not found")
        return {}
    raw     = yaml.safe_load(yaml_path.read_text())
    methods = raw.get("methods", {})
    base    = BASE / raw.get("docs_base", "docs-src/mkdocs/source/research")
    for entry in methods.values():
        entry["_base"] = base
    return methods


def _load_references(method_id: str) -> List[Dict]:
    """Load citation rows from config/methodology_refs/{method_id}.yaml."""
    ref_file = REFS_DIR / f"{method_id}.yaml"
    if not ref_file.exists():
        return []
    data = yaml.safe_load(ref_file.read_text())
    return data if isinstance(data, list) else data.get("references", [])


def _extract_section(doc_path: Path, keyword: str) -> str:
    """Extract section from markdown by heading keyword."""
    if not doc_path.exists():
        return f"[Documentation not found: {doc_path.name}]"
    content = doc_path.read_text(encoding="utf-8")
    lines   = content.split("\n")
    start   = next(
        (i for i, ln in enumerate(lines)
         if ln.startswith("#") and keyword.lower() in ln.lower()),
        None,
    )
    if start is None:
        return content
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    end   = next(
        (i for i, ln in enumerate(lines[start + 1:], start + 1)
         if ln.startswith("#" * level + " ")),
        len(lines),
    )
    return "\n".join(lines[start:end]).strip()


def _get_code_version() -> str:
    """Get git commit hash or fallback."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=BASE,
        )
        return result.stdout.strip() or "1.0"
    except Exception:
        return "1.0"


def _try_latexify(fn) -> Optional[str]:
    """Try auto formula extraction. Returns None on any failure."""
    if fn is None:
        return None
    try:
        import latexify
        return latexify.function(fn)._repr_latex_()
    except Exception:
        return None


# =============================================================================
# VALIDATION
# =============================================================================

def _validate_row(row: Dict) -> List[str]:
    """Return list of validation errors. Empty = valid."""
    errors = []
    if not row.get("formula_latex"):
        errors.append(f"{row['id']}: missing formula_latex")
    if not row.get("description"):
        errors.append(f"{row['id']}: missing description")
    if row.get("provenance") in ("CALCULATED", "INFERRED"):
        if not row.get("code_snapshot") and not row.get("formula_latex"):
            errors.append(f"{row['id']}: missing both code_snapshot AND formula_latex")
    return errors


# =============================================================================
# INSERT HELPERS
# =============================================================================

def _insert_registry(conn, row: Dict, dry_run: bool) -> None:
    """Validate then insert/replace one registry row."""
    # Validate before insert — fail loud, not silent
    errors = _validate_row(row)
    for err in errors:
        logger.warning("VALIDATION: %s", err)

    # Ensure confidence has a value — older methods may not define it explicitly
    if "confidence" not in row:
        row["confidence"] = 1.0

    if dry_run:
        logger.info(
            "[DRY-RUN] %-42s  %-12s  %-12s  formula=%s  code=%s  desc=%d  warns=%d",
            row["id"], row["layer"], row["provenance"],
            "✓" if row.get("formula_latex") else "✗",
            "✓" if row.get("code_snapshot") else "✗",
            len(row.get("description", "")),
            len(errors),
        )
        return

    conn.execute("""
        INSERT OR REPLACE INTO measurement_method_registry (
            id, name, version, description, formula_latex,
            code_snapshot, code_language, code_version,
            parameters, output_metric, output_unit,
            provenance, layer, applicable_on, fallback_method_id,
            validated, active, confidence, updated_at
        ) VALUES (
            :id, :name, :version, :description, :formula_latex,
            :code_snapshot, :code_language, :code_version,
            :parameters, :output_metric, :output_unit,
            :provenance, :layer, :applicable_on, :fallback_method_id,
            0, 1, :confidence, unixepoch()
        )
    """, row)


def _insert_references(conn, method_id: str, refs: List, dry_run: bool) -> None:
    """Delete stale then insert fresh references."""
    if dry_run or not refs:
        return
    conn.execute("DELETE FROM method_references WHERE method_id = ?", (method_id,))
    for ref in refs:
        conn.execute("""
            INSERT INTO method_references (
                method_id, ref_type, title, authors, year,
                venue, doi, url, relevance, cited_text, page_or_section
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            method_id,
            ref.get("ref_type", "paper"), ref.get("title", ""),
            ref.get("authors"), ref.get("year"), ref.get("venue"),
            ref.get("doi"), ref.get("url"), ref.get("relevance"),
            ref.get("cited_text"), ref.get("page_or_section"),
        ))


# =============================================================================
# SEED FUNCTIONS
# =============================================================================

def _build_row_from_entry(entry: Dict, doc_map: Dict, code_version: str) -> Dict:
    """Build complete registry row from a method entry dict."""
    method_id = entry["id"]
    fn        = entry.get("fn")

    # Formula: manual wins → latexify fallback (Bug 1 fix — explicit logic)
    formula_latex = entry.get("formula_latex")
    if not formula_latex:
        formula_latex = _try_latexify(fn)

    # Code snapshot: specific fn only (Bug 2 fix — no giant compute() for all)
    code_snapshot = ""
    if fn:
        try:
            code_snapshot = inspect.getsource(fn)
        except Exception:
            pass

    # Description from doc map (entry overrides map)
    doc_entry   = doc_map.get(method_id, {})
    base        = doc_entry.get("_base") or (BASE / "docs-src/mkdocs/source/research")
    doc_file    = doc_entry.get("doc") or entry.get("doc", "")
    section     = doc_entry.get("section") or entry.get("section", "")
    description = _extract_section(base / doc_file, section) if doc_file else ""

    return {
        "id":                method_id,
        "name":              entry["name"],
        "version":           entry.get("version", "1.0"),
        "description":       description,
        "formula_latex":     formula_latex or "",
        "code_snapshot":     code_snapshot,
        "code_language":     "python",
        "code_version":      code_version,
        "parameters":        json.dumps(entry.get("parameters", {})),
        "output_metric":     entry.get("output_metric", ""),
        "output_unit":       entry.get("output_unit", ""),
        "provenance":        entry["provenance"],
        "layer":             entry["layer"],
        "applicable_on":     json.dumps(entry.get("applicable_on", ["any"])),
        "fallback_method_id": entry.get("fallback_method_id"),
        "confidence":        entry.get("confidence", 1.0),
    }


def seed_reader(cls, conn, doc_map: Dict, code_version: str, dry_run: bool) -> None:
    """Seed one hardware reader class."""
    method_id = cls.METHOD_ID

    # Formula from @formula decorator
    formula_latex = ""
    for fn_name in ("get_energy_delta", "read_energy_uj"):
        fn = getattr(cls, fn_name, None)
        if fn and hasattr(fn, "_formula_latex"):
            formula_latex = fn._formula_latex
            break

    # Full file as code_snapshot for readers
    try:
        code_snapshot = Path(inspect.getfile(cls)).read_text(encoding="utf-8")
    except Exception:
        code_snapshot = ""

    doc_entry   = doc_map.get(method_id, {})
    base        = doc_entry.get("_base", BASE / "docs-src/mkdocs/source/research")
    description = _extract_section(
        base / doc_entry.get("doc", ""),
        doc_entry.get("section", ""),
    ) if doc_entry.get("doc") else ""

    # Bug 4 fix: read APPLICABLE_ON from class if available
    applicable_on = json.dumps(
        getattr(cls, "APPLICABLE_ON",
                ["linux_x86_64"] if "RAPL" in cls.METHOD_NAME else ["any"])
    )

    row = {
        "id":                method_id,
        "name":              cls.METHOD_NAME,
        "version":           "1.0",
        "description":       description,
        "formula_latex":     formula_latex,
        "code_snapshot":     code_snapshot,
        "code_language":     "python",
        "code_version":      code_version,
        "parameters":        json.dumps(cls.METHOD_PARAMS),
        "output_metric":     "pkg_energy_uj",
        "output_unit":       "µJ",
        "provenance":        cls.METHOD_PROVENANCE,
        "layer":             cls.METHOD_LAYER,
        "applicable_on":     applicable_on,
        "fallback_method_id": cls.FALLBACK_METHOD_ID,
    }

    _insert_registry(conn, row, dry_run)
    if not dry_run:
        refs = _load_references(method_id)   # Bug 3 fix: load once
        _insert_references(conn, method_id, refs, dry_run)
        logger.info("  ✓ %-42s  refs=%d", method_id, len(refs))


def seed_entry(entry: Dict, conn, doc_map: Dict, code_version: str, dry_run: bool) -> None:
    """Seed one measured or derived method entry."""
    row  = _build_row_from_entry(entry, doc_map, code_version)
    _insert_registry(conn, row, dry_run)
    if not dry_run:
        refs = _load_references(entry["id"])  # Bug 3 fix: load once
        _insert_references(conn, entry["id"], refs, dry_run)
        logger.info("  ✓ %-42s  refs=%d", entry["id"], len(refs))


# =============================================================================
# ENTRY POINT
# =============================================================================

def main() -> None:
    """Seed all readers, measured methods, and derived methods."""
    parser = argparse.ArgumentParser(description="Seed measurement_method_registry")
    parser.add_argument("--db",      default="data/experiments.db")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db_path      = BASE / args.db
    readers      = _load_readers()
    measured     = _load_measured_methods()
    derived      = _load_derived_methods()
    doc_map      = _load_doc_map()
    code_version = _get_code_version()

    total = len(readers) + len(measured) + len(derived)
    logger.info("Readers : %d  Measured: %d  Derived: %d  Total: %d",
                len(readers), len(measured), len(derived), total)

    if args.dry_run:
        logger.info("DRY-RUN — no DB writes")
        for cls in readers:
            seed_reader(cls, None, doc_map, code_version, dry_run=True)
        for entry in measured + derived:
            seed_entry(entry, None, doc_map, code_version, dry_run=True)
        return

    if not db_path.exists():
        logger.error("DB not found: %s", db_path)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        with conn:
            for cls in readers:
                seed_reader(cls, conn, doc_map, code_version, dry_run=False)
            for entry in measured + derived:
                seed_entry(entry, conn, doc_map, code_version, dry_run=False)

        logger.info(
            "Done — %d methods seeded. Verify:\n"
            "  sqlite3 %s \"SELECT id, provenance, "
            "length(formula_latex), length(code_snapshot) "
            "FROM measurement_method_registry;\"",
            total, db_path,
        )
    except Exception as exc:
        logger.error("Seed failed: %s", exc)
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
