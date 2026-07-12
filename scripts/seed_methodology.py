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
    from core.readers.darwin.iokit_thermal_reader  import IOKitThermalReader
    from core.readers.fallback.energy_estimator    import EnergyEstimator
    from core.readers.fallback.dummy_energy_reader import DummyEnergyReader
    return [RAPLReader, IOKitPowerReader, IOKitThermalReader, EnergyEstimator, DummyEnergyReader]


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
            "id":           "ioreport_cpufreq_v1",
            "name":         "IOReport DVFS Residency Weighted CPU Frequency",
            "provenance":   "MEASURED",
            "layer":        "silicon",
            "output_metric":"frequency_mhz",
            "output_unit":  "MHz",
            "applicable_on":["darwin_arm64"],
            "formula_latex": (
                r"f_{\text{weighted}} = "
                r"\frac{\sum_{i=0}^{N-1} f_i \cdot r_{i+1}}"
                r"{\sum_{j=0}^{N} r_j}"
            ),
            "parameters":   {
                "f_i": "DVFS state frequency in MHz from IORegistry voltage-states blob",
                "r_j": "IOReport residency in nanoseconds for state j (r_0 = IDLE)",
                "N":   "Number of active DVFS states for the primary compute cluster",
            },
            "description":  (
                "Reads per-core DVFS residency counters from Apple's IOReport "
                "library (the same data source used internally by powermetrics). "
                "Computes wall-clock-weighted average frequency for the primary "
                "compute cluster (P-cluster on Apple Silicon) over the measurement "
                "window. Residency counters are cumulative hardware counters "
                "providing exact state accounting, not sampled data. "
                "No sudo required. No subprocess. Pure Python ctypes."
            ),
            "doc":          "07-energy-readers-methodology.md",
            "section":      "IOReport CPU Frequency (ioreport_cpufreq_v1)",
        },        
        {
            "id":           "gpu_rapl_pp1_v1",
            "name":         "Intel Iris Xe GPU Energy via MSR 0x641",
            "provenance":   "MEASURED",
            "layer":        "silicon",
            "output_metric":"gpu_total_energy_uj",
            "output_unit":  "µJ",
            "applicable_on":["linux_x86_64"],
            "formula_latex": r"E_{gpu} = (R_{end} - R_{start}) \times 61.0352\,\mu J",
            "parameters":   {"msr": "0x641", "energy_unit_uj": 61.0352, "platform": "Tiger Lake i7-1165G7"},
            "description":  "GPU PP1 energy via MSR_PP1_ENERGY_STATUS (0x641). Read via msr_read binary at run start/end. Energy unit from MSR 0x606 bits[12:8]=14. Cross-validated against perf power/energy-gpu/ PMU within 7%.",
            "doc":          "07-energy-readers-methodology.md",
            "section":      "GPU PP1 Energy Measurement",
        },
        {
            "id":           "gpu_dynamic_baseline_v1",
            "name":         "GPU Dynamic Energy via Baseline Subtraction",
            "provenance":   "CALCULATED",
            "layer":        "silicon",
            "output_metric":"gpu_dynamic_energy_uj",
            "output_unit":  "µJ",
            "applicable_on":["linux_x86_64"],
            "formula_latex": r"E_{gpu,dyn} = E_{gpu,total} - \dot{E}_{gpu,base} \cdot t",
            "parameters":   {"baseline_method": "min_power_watts", "percentile": "2nd"},
            "description":  "GPU dynamic energy = total GPU energy minus idle baseline. Baseline from idle_baselines.gpu_power_watts measured at experiment start. Same methodology as cpu dynamic_energy_uj.",
            "doc":          "07-energy-readers-methodology.md",
            "section":      "GPU PP1 Energy Measurement",
        },  
        {
            "id":           "gpu_dynamic_run_local_v1",
            "name":         "GPU Dynamic Energy via Run-Local Adaptive Idle Baseline",
            "provenance":   "CALCULATED",
            "layer":        "silicon",
            "output_metric":"gpu_dynamic_energy_uj",
            "output_unit":  "µJ",
            "applicable_on":["linux_x86_64", "linux_aarch64"],
            "formula_latex": r"P_{idle} = \mathrm{median}(P_i \mid \text{sample classified idle}); \quad E_{gpu,dyn} = \sum_i \max(P_i - P_{idle}, 0)\,\Delta t_i",
            "parameters":   {"idle_classifier": "util_gpu_pct == 0, platform-specific instantiation, see _is_idle_gpu_sample in core/energy_engine.py", "central_tendency": "median", "fallback_method_id": "gpu_dynamic_baseline_v1"},
            "description":  "GPU dynamic energy via run-local adaptive baseline. Idle power is the median power across this run's own idle-classified GPU samples, not a separately-measured calibration baseline, removing thermal drift, clock drift, and background load differences between calibration time and run time. Dynamic energy is the sum of max(sample_power - idle_power, 0) integrated across every sample in the run. Median chosen over mean because idle samples occasionally contain scheduler noise or telemetry jitter; median gives a robust estimator of steady-state idle power. Falls back to gpu_dynamic_baseline_v1 only when a run has zero idle-classified samples. Primary method as of 2026-06-21, replacing gpu_dynamic_baseline_v1 as the default: confirmed on two same-experiment runs that external calibration, measured once and separately, produced baseline-exceeds-total in opposite directions depending on run duration and idle-time fraction, which the run-local method resolves by referencing the run's own conditions instead of a fixed external number.",
            "doc":          "07-energy-readers-methodology.md",
            "section":      "GPU Dynamic Energy Measurement",
        },
        {
            "id":            "nvml_total_energy_v1",
            "name":          "NVIDIA NVML Cumulative Energy Counter",
            "provenance":    "MEASURED",
            "layer":         "silicon",
            "confidence":    1.0,
            "description":   (
                "nvmlDeviceGetTotalEnergyConsumption() returns cumulative mJ. "
                "Converted to µJ. Available on NVIDIA drivers >= 340.x. "
                "Validated on RTX 2070 Super (Alex Flesher) and GN100 GB10."
            ),
            "formula_latex": r"E_{gpu} = \Delta\text{NVML}_{energy} \times 1000\,\mu J/mJ",
            "parameters":    {"nvml_field": "totalEnergyConsumption", "unit": "mJ"},
            "doc":           "24-gpu-energy-methodology.md",
            "section":       "NVML Backend (NVIDIA Discrete GPUs)",
        },
        {
            "id":            "nvml_power_integration_v1",
            "name":          "NVIDIA NVML Power Integration Fallback",
            "provenance":    "MEASURED",
            "layer":         "silicon",
            "confidence":    0.85,
            "description":   (
                "nvmlDeviceGetPowerUsage() returns instantaneous mW. "
                "Energy = power x dt. Used when cumulative counter unavailable. "
                "Lower confidence due to integration error accumulation."
            ),
            "formula_latex": r"E_{gpu} = P_{gpu} \times \Delta t",
            "parameters":    {"nvml_field": "powerUsage", "unit": "mW"},
            "doc":           "24-gpu-energy-methodology.md",
            "section":       "NVML Backend (NVIDIA Discrete GPUs)",
        },
        {
            "id":            "dcgm_energy_v1",
            "name":          "NVIDIA DCGM Field 156 Energy",
            "provenance":    "MEASURED",
            "layer":         "silicon",
            "confidence":    1.0,
            "description":   (
                "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION (field 156). "
                "Cumulative mJ counter from DCGM daemon. "
                "Validated on GN100 GB10 Superchip: spark_hwmon loaded, "
                "4 energy accumulators confirmed. "
                "Primary GPU energy path on ARM where RAPL is absent."
            ),
            "formula_latex": r"E_{gpu} = \Delta\text{DCGM}_{f156} \times 1000\,\mu J/mJ",
            "parameters":    {"dcgm_field": 156, "unit": "mJ"},
            "doc":           "24-gpu-energy-methodology.md",
            "section":       "DCGM Backend (GN100)",
        },
        {
            "id":            "iokit_gpu_energy_v1",
            "name":          "Apple IOKit GPU Energy (powermetrics)",
            "provenance":    "MEASURED",
            "layer":         "silicon",
            "confidence":    0.90,
            "description":   (
                "Apple Silicon GPU energy via sudo powermetrics. "
                "Instantaneous power integrated over sample interval. "
                "Platform: Stephen Abkin M1 Pro. "
                "Confidence 0.90: Apple internal counter, not independently validated."
            ),
            "formula_latex": r"E_{gpu} = P_{gpu,powermetrics} \times \Delta t",
            "parameters":    {"tool": "powermetrics", "sampler": "gpu_power"},
            "doc":           "24-gpu-energy-methodology.md",
            "section":       "IOKit Backend",
        },
        {
            "id":            "rocm_smi_energy_v1",
            "name":          "AMD ROCm SMI Energy Counter (Stub)",
            "provenance":    "MEASURED",
            "layer":         "silicon",
            "confidence":    0.85,
            "description":   (
                "rsmi_dev_energy_count_get() cumulative counter. "
                "Stub only — no AMD GPU hardware in lab as of 2026-06. "
                "Activate when AMD hardware joins the lab."
            ),
            "formula_latex": r"E_{gpu} = \Delta\text{ROCm}_{energy}",
            "parameters":    {"api": "rsmi_dev_energy_count_get"},
            "doc":           "24-gpu-energy-methodology.md",
            "section":       "ROCm Backend",
        },

        {
            "id":            "gpu_attribution_exclusive_v1",
            "name":          "GPU Dynamic Energy Attribution (Exclusive Workload)",
            "provenance":    "CALCULATED",
            "layer":         "application",
            "confidence":    1.0,
            "description":  "GPU attributed energy = gpu_total_energy_uj - gpu_baseline_energy_uj. Valid when workload has exclusive GPU use (single-process A-LEMS experiments). gpu_dynamic_energy_uj is the canonical attributed metric per B decision. attribution_method=exclusive set by gpu_attribution_etl.py.",
            "formula_latex": r"E_{gpu,dynamic} = E_{gpu,total} - E_{gpu,baseline}",
            "parameters":    {"attribution_method": "exclusive"},
        },
        {
            "id":            "gpu_baseline_2sigma_v1",
            "name":          "GPU Idle Baseline (2-Sigma Method)",
            "provenance":    "MEASURED",
            "layer":         "silicon",
            "confidence":    1.0,
            "description":  "GPU idle baseline power measured at 10 Hz via GPUCollector during idle period before experiment. Uses same 2-sigma methodology as CPU baseline. Stored in idle_baselines.gpu_power_watts. gpu_baseline_energy_uj = gpu_power_watts * run_duration_ns / 1e9.",
            "formula_latex": r"E_{gpu,baseline} = P_{gpu,idle} \times t_{run}",
            "parameters":    {"method": "2sigma_idle", "rate_hz": 10},
        },
        {
            "id":           "energy_domain_registry_v1",
            "name":         "Energy Domain Registry",
            "provenance":   "SYSTEM",
            "layer":        "silicon",
            "confidence":   1.00,
            "description":  (
                "Lookup table mapping energy domain names to hardware topology. "
                "PACKAGE, NETWORK, ACCELERATOR, STORAGE are independent roots. "
                "contributes_to_parent per platform in platform_domain_relationships. "
                "Adding a new platform requires only new rows in energy_sources "
                "and platform_domain_relationships — zero schema changes."
            ),
            "formula_latex": r"\text{domain} \in \mathcal{D}_{\text{platform}}",
            "parameters":   {},
            "doc":          "26-unified-energy-schema.md",
            "section":      "Core Tables",
        },
        {
            "id":           "nvlink_c2c_isolation_v1",
            "name":         "NVLink-C2C Energy Isolation via SPBM Subtraction",
            "provenance":   "INFERRED",
            "layer":        "silicon",
            "confidence":   0.95,
            "description":  (
                "NVLink-C2C die-to-die energy isolated by subtracting DCGM GPU "
                "compute energy from SPBM GPU rail energy on GN100 GB10. "
                "SPBM GPU rail = GPU compute + HBM + NVLink-C2C overhead. "
                "DCGM field 156 = GPU compute only (excludes HBM and NVLink-C2C). "
                "Delta = NVLink-C2C + HBM memory bandwidth energy. "
                "Validated idle baseline: 992 mW delta on GN100 (2026-06-14). "
                "First measurement of NVLink-C2C power on GB10 unified memory SoC. "
                "ISPASS 2027 paper primary methodology."
            ),
            "formula_latex": r"E_{nvlink\_c2c} = E_{spbm\_gpu} - E_{dcgm\_gpu}",
            "parameters":   {"idle_baseline_mw": 992, "dcgm_field": 156},
            "doc":          "26-network-wait-energy-methodology.md",
            "section":      "NVLink-C2C Energy Isolation",
        },
        {
            "id":           "device_telemetry_v1",
            "name":         "Device Telemetry (Power, Temperature, Utilization)",
            "provenance":   "MEASURED",
            "layer":        "os",
            "confidence":   1.00,
            "description":  (
                "Instantaneous device state sampled at 10 Hz alongside energy_samples_v2. "
                "Covers GPU telemetry (NVML, DCGM), SoC wall power (SPBM dc_input), "
                "and future network and storage device telemetry. "
                "power_mw is instantaneous milliwatts — not cumulative. "
                "energy_uj present for NVML and DCGM backends (cumulative counter). "
                "energy_uj is NULL for SMI_INTEG — power integration done at ETL. "
                "dc_input_mw captures wall input power on GN100 SOC device type."
            ),
            "formula_latex": r"P(t) = \frac{dE}{dt}\bigg|_{t}",
            "parameters":   {"sampling_hz": 10},
            "doc":          "07-energy-readers-methodology.md",
            "section":      "Device Telemetry",
        },
        {
            "id":           "power_rail_sampling_v1",
            "name":         "Power Rail Sampling (SPBM hwmon, GN100)",
            "provenance":   "MEASURED",
            "layer":        "hardware",
            "confidence":   1.00,
            "description":  (
                "Instantaneous power readings from 10 SPBM hwmon rails on GN100 at configurable Hz (default 10 Hz). "
                "Rails sourced from hw_config.json spbm.power_paths — no hardcoded hwmon numbers. "
                "Covers full power topology: dc_input (wall), sys_total, soc_pkg, cpu_gpu, "
                "cpu_p, cpu_e, vcore, gpu, prereg, dla. "
                "Power limits (PL1, PL2, SYSPL1, SYSPL2) captured once per run in run_power_limits — "
                "not sampled at frequency (firmware constants during normal operation). "
                "Mid-run limit changes recorded in power_limit_events if detected. "
                "Values in µW from sysfs converted to mW at read time. "
                "Decoupled from energy_samples_v2 — independent timestamp stream allows "
                "different sampling frequencies per stream in future platforms."
            ),
            "formula_latex": r"E_{derived}(t_1, t_2) = \int_{t_1}^{t_2} P(t)\, dt \approx \sum_i P_i \cdot \Delta t_i",
            "parameters":   {"sampling_hz": 10, "rails": 10, "limits": 4},
            "doc":          "27-power-rail-schema.md",
            "section":      "Power Rail Sampling",
        },
        {
            "id":           "power_rail_etl_v1",
            "name":         "Power Rail ETL: Time-Integrated Energy Derivation",
            "provenance":   "DERIVED",
            "layer":        "etl",
            "confidence":   0.95,
            "description":  (
                "ETL-computed energy derived by integrating instantaneous power rail samples "
                "over time (power × interval_ns). Produces three derived metrics per run: "
                "wall_energy_uj (dc_input rail integrated), dla_energy_uj (dla rail integrated), "
                "board_overhead_uj (wall_energy_uj minus pkg accumulator energy_uj). "
                "Stored in energy_derived_metrics with derivation_formula field for paper citability. "
                "Confidence 0.95 reflects Riemann sum approximation at 10 Hz sampling. "
                "Conservation check: dc_input_integrated ≈ pkg_accumulator + board_overhead. "
                "Deviation from conservation invariant flags measurement anomalies."
            ),
            "formula_latex": r"E_{board} = E_{dc\_input} - E_{pkg}",
            "parameters":   {"integration_method": "riemann_sum", "source_hz": 10},
            "doc":          "27-power-rail-schema.md",
            "section":      "ETL Integration",
        },        
        {
            "id":            "gpu_phase_alignment_v1",
            "name":          "GPU Phase Energy Alignment (CPU Proxy)",
            "provenance":    "INFERRED",
            "layer":         "application",
            "confidence":    0.70,
            "description":  "GPU phase energy estimated by applying CPU orchestration_events phase fractions to gpu_dynamic_energy_uj. Proxy method. GPU sampling at 10 Hz provides sufficient temporal resolution for phase alignment but phase-level GPU attribution is inferred from CPU structure, not directly measured. Confidence 0.70 reflects proxy limitation. D8 invariant holds exactly by construction.",
            "formula_latex": r"E_{gpu,phase} = E_{gpu,dynamic} \times f_{phase,cpu}",
            "parameters":    {
                "proxy_source": "orchestration_events phase fractions",
                "rate_hz":      10,
            },
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
            "id":           "tool_instrumentation_v1",
            "name":         "Tool Execution Instrumentation",
            "provenance":   "MEASURED",
            "layer":        "orchestration",
            "confidence":   1.0,
            "description":  (
                "Per-tool measurement of CPU time, memory delta, I/O bytes, "
                "payload hashes, and success/failure captured synchronously "
                "during tool call execution. Emitted into orchestration_events "
                "via _emit_event() backfill. Not ETL-derived."
            ),
            "formula_latex": (
                r"cpu\_ns = (ru\_utime + ru\_stime)_{after} "
                r"- (ru\_utime + ru\_stime)_{before}"
            ),
            "parameters": {
                "cpu_source":    "resource.getrusage(RUSAGE_SELF)",
                "memory_source": "/proc/self/status VmRSS",
                "hash_algorithm": "SHA-256 truncated 16 chars",
            },
            "doc":          "24-tool-instrumentation-methodology.md",
            "section":      "Tool Execution Instrumentation Methodology",
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
        {
            "id":           "phase_attribution_sample_v2",
            "name":         "Phase Attribution v2 (Direct RAPL Sample Measurement)",
            "provenance":   "MEASURED",
            "layer":        "orchestration",
            "confidence":   0.98,
            "description":  (
                "Per-phase energy measured directly from 100Hz RAPL energy_samples "
                "within orchestration_events phase timestamp windows. "
                "E_phase_i = SUM(pkg_end_uj - pkg_start_uj) x cpu_frac_i "
                "for samples where sample_start_ns >= phase.start AND sample_end_ns <= phase.end. "
                "inter_phase_energy_uj = E_attributed - SUM(E_phase_i) captures honest residual: "
                "Python interpreter overhead, tool dispatch, framework calls between phases. "
                "Replaces v1 weighted allocation which forced SUM=attributed by construction. "
                "phase_sample_coverage_pct documents what fraction of run samples fell in phase windows."
            ),
            "formula_latex": (
                r"E_{phase,i} = \sum_{s \in W_i} (pkg\_end_s - pkg\_start_s) \times f_{cpu,i}"
                r",\quad E_{inter} = E_{attr} - \sum_i E_{phase,i}"
            ),
            "parameters": {
                "energy_sample_rate_hz":  100,
                "cpu_sample_rate_hz":     10,
                "window_match":           "sample_start_ns >= phase.start AND sample_end_ns <= phase.end",
                "fallback":               "run_level_cpu_fraction when phase ticks unavailable",
                "residual_policy":        "inter_phase_energy_uj — honest residual, not forced to 0",
            },
            "fn":      "phase_attribution_etl.compute_phase_attribution",
            "doc":     "09-derived-metrics-methodology.md",
            "section": "Phase Energy Attribution v2",
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
                r"\text{AXIS 1A: } E_{pkg} = E_{core} + E_{uncore} + E_{dram}"
                r",\quad E_{dynamic} = E_{pkg} - E_{baseline}"
                r",\quad E_{attributed} = \alpha_{cpu} \times E_{dynamic}"
                r",\quad E_{background} = E_{dynamic} - E_{attributed}"
                r"\\\text{AXIS 2A: } E_{attributed} = E_{llm\_window} + E_{orch}"
                r"\\\text{AXIS 2B: } E_{attributed} = E_{plan} + E_{exec} + E_{synth} + E_{inter}"
                r"\\\text{AXIS 3 signals (non-conserved): } \{E_{network}, E_{io}, E_{cache}, E_{interrupt}, ...\}"
            ),
            "parameters":    {
                "axis_1a":           "Hardware domain partition: pkg=core+uncore+dram",
                "axis_1b":           "Process attribution: attributed=alpha_cpu×dynamic",
                "axis_2a":           "Functional partition: attributed=llm_window+orchestration (TWO-TERM)",
                "axis_2b":           "Phase partition: attributed=planning+execution+synthesis+inter_phase",
                "axis_3":            "Resource signals: MODELED proxies, NOT conservation partitions",
                "unattributed":      "max(0, pkg - Σ conservation layers)",
                "model_version":     "v1",
                "framework":         "A-LEMS Four-Axis Energy Attribution Framework",
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
        {
            "id":            "network_wait_energy_v1",
            "name":          "Network Wait Energy Attribution v1 (RAPL Slice)",
            "provenance":    "MEASURED",
            "layer":         "application",
            "confidence":    0.95,
            "description":   (
                "Energy during network IO blocking periods measured via direct RAPL "
                "sample slice over [request_start_ns → first_token_time_ns] windows "
                "from llm_interactions. "
                "This is an AXIS 3A physical observable — NOT a conservation partition. "
                "Key finding: energy is NON-ZERO even when cpu_percent_during_wait≈0 "
                "because DRAM and uncore remain active for streaming buffer management. "
                "Explains why E_orchestration is non-trivial for remote providers. "
                "Falls back to time-fraction when timestamps unavailable (pre-migration-038). "
                "Fallback: (non_local_ms / task_duration_ms) × attributed_energy_uj."
            ),
            "formula_latex": (
                r"E_{network} = \sum_{i \in \text{interactions}}"
                r"\sum_{s \in [t^i_{req}, t^i_{first}]} \Delta pkg_s \times \alpha_{cpu}"
                r"\quad \text{(AXIS 3A signal — not a conservation partition)}"
            ),
            "parameters":    {
                "primary_source":   "RAPL energy_samples sliced by request_start_ns→first_token_time_ns",
                "fallback":         "(non_local_ms / task_duration_ms) × attributed_energy_uj",
                "fallback_trigger": "request_start_ns IS NULL (pre-migration-038 runs)",
                "axis":             "AXIS 3A — Physical Observable",
                "conservation_role": "NONE — diagnostic signal, not part of D1 partition",
                "literature":       "Hähnel et al. 2012 — RAPL accuracy for short windows",
            },
            "doc":           "25-energy-attribution-guide.md",
            "section":       "Section 11.1 — network_wait_energy_uj",
        },
{
            "id":            "network_wait_rapl_slice_v2",
            "name":          "Network Wait Energy — Raw RAPL Slice v2 (No alpha_cpu)",
            "provenance":    "MEASURED",
            "layer":         "application",
            "confidence":    0.93,
            "description":   (
                "SPEC_03 Strategy A: Sum RAPL pkg energy within LLM blocking windows "
                "[request_start_ns, first_token_time_ns]. "
                "Fixes alpha_cpu=0 bug in network_wait_energy_v1: during network wait "
                "CPU cores are idle but pkg is non-zero due to NIC DMA, PCH activity, "
                "DRAM refresh, uncore fabric. AX201 at PCI 00:14.3 is PCH-integrated "
                "and inside RAPL uncore domain. No cpu_fraction multiplication. "
                "Applies to: UBUNTU2505 (Intel i7-1165G7, AX201 WiFi, x86_64)."
            ),
            "formula_latex": (
                r"E_{network} = \sum_{i \in \text{interactions}}"
                r"\sum_{s \in [t^i_{req}, t^i_{first}]} (pkg\_end\_uj_s - pkg\_start\_uj_s)"
                r"\quad \text{(no } \alpha_{cpu} \text{ — fixes SPEC\_03 bug)}"
            ),
            "parameters":    {
                "primary_source":    "RAPL energy_samples pkg_end_uj - pkg_start_uj in blocking windows",
                "nic_topology":      "pch_integrated (Intel AX201, PCI bus 0, inside RAPL uncore)",
                "alpha_cpu":         "NOT applied — key fix over v1",
                "platform":          "x86_64 Linux, Intel PCH-integrated NIC",
                "confidence_basis":  "C_source=1.0, C_method=0.95, C_validation=0.80, C_platform=0.90",
                "replaces":          "network_wait_energy_v1 for Strategy A platforms",
            },
            "doc":           "28-network-energy-cross-platform-methodology.md",
            "section":       "Section 3.1 — Strategy A: RAPL Slice",
        },
        {
            "id":            "network_wait_spbm_fraction_v1",
            "name":          "Network Wait Energy — SPBM DC_INPUT Fraction (GN100)",
            "provenance":    "INFERRED",
            "layer":         "application",
            "confidence":    0.70,
            "description":   (
                "SPEC_03 Strategy B: Sum SPBM domain energy within LLM blocking windows. "
                "Primary: DC_INPUT (domain_id=28) total board input power (v76+ runs). "
                "Fallback: GPU_SPBM (domain_id=7) broad GPU rail (pre-v76 groq runs). "
                "Known overestimate: GPU idle draw included. Conservative upper bound. "
                "Applies to: GN100 (NVIDIA Grace GB10, aarch64, no RAPL)."
            ),
            "formula_latex": (
                r"E_{network} = \sum_{i \in \text{interactions}}"
                r"\sum_{s \in [t^i_{req}, t^i_{first}]} E_{DC\_INPUT,s}"
                r"\quad \text{(domain\_id=28, conservative upper bound)}"
            ),
            "parameters":    {
                "primary_domain":   "DC_INPUT (domain_id=28) — v76+ runs",
                "fallback_domain":  "GPU_SPBM (domain_id=7) — pre-v76 groq runs",
                "known_bias":       "Overestimate: GPU idle power included during blocking",
                "platform":         "aarch64 Linux, NVIDIA Grace GB10 (GN100)",
                "confidence_basis": "C_source=0.90, C_method=0.75, C_validation=0.60, C_platform=0.60",
                "future_fix":       "Subtract GPU_DCGM (domain_id=6) energy in v2",
            },
            "doc":           "28-network-energy-cross-platform-methodology.md",
            "section":       "Section 3.2 — Strategy B: SPBM DC_INPUT",
        },
        {
            "id":            "nic_sysfs_reader_v1",
            "name":          "NIC Byte Counter Reader — Linux sysfs",
            "provenance":    "MEASURED",
            "layer":         "silicon",
            "confidence":    0.99,
            "description":   (
                "SPEC_03A: Reads cumulative NIC byte/packet counters from "
                "/sys/class/net/<iface>/statistics/ at 100Hz. "
                "Detects active non-loopback interface via operstate sysfs. "
                "No subprocess calls. Counters are kernel-maintained, monotonic. "
                "Applies to: Linux platforms with sysfs (UBUNTU2505, GN100)."
            ),
            "formula_latex": (
                r"bytes\_delta = tx\_bytes_{t1} + rx\_bytes_{t1}"
                r"- tx\_bytes_{t0} - rx\_bytes_{t0}"
            ),
            "parameters":    {
                "source":    "/sys/class/net/<iface>/statistics/",
                "fields":    "tx_bytes, rx_bytes, tx_packets, rx_packets",
                "cadence":   "100Hz",
                "platform":  "Linux x86_64 and aarch64",
            },
            "doc":           "31-network-energy-cross-platform-methodology.md",
            "section":       "Section 4 — SPEC_03A NIC Observability",
        },
        {
            "id":            "nic_window_validator_v1",
            "name":          "NIC Activity Window Validator",
            "provenance":    "CALCULATED",
            "layer":         "application",
            "confidence":    0.90,
            "description":   (
                "SPEC_03A: Validates SPEC_03 network energy attribution windows "
                "using NIC byte counter deltas from nic_samples. "
                "Adjusts confidence score down by 0.75x penalty for windows "
                "where NIC shows no byte movement during LLM blocking period. "
                "Returns base confidence unmodified if nic_samples unavailable."
            ),
            "formula_latex": (
                r"conf_{adj} = conf_{base} \times "
                r"(f_{active} + (1 - f_{active}) \times 0.75)"
            ),
            "parameters":    {
                "penalty":   "0.75 for inactive windows",
                "signal":    "delta(tx_bytes + rx_bytes) per blocking window",
                "fallback":  "returns base_confidence if nic_samples absent",
            },
            "doc":           "31-network-energy-cross-platform-methodology.md",
            "section":       "Section 4 — SPEC_03A NIC Observability",
        },        
        {
            "id":            "network_wait_time_fraction_v1",
            "name":          "Network Wait Energy — Time Fraction Fallback (Universal)",
            "provenance":    "INFERRED",
            "layer":         "application",
            "confidence":    0.50,
            "description":   (
                "SPEC_03 Strategy C: Time fraction of dynamic_energy_uj during "
                "network blocking windows. Universal fallback when RAPL and SPBM "
                "are unavailable. Uses dynamic_energy_uj NOT attributed_energy_uj — "
                "attributed has alpha_cpu baked in which would double-suppress. "
                "Conservative lower bound. Applies to: Apple M1 Pro (IOKit stub), "
                "AMD without RAPL, VMs, unknown platforms."
            ),
            "formula_latex": (
                r"E_{network} = \frac{non\_local\_ms}{task\_duration\_ms}"
                r"\times E_{dynamic}"
                r"\quad \text{(lower bound — misses uncore/NIC activity)}"
            ),
            "parameters":    {
                "primary_source":   "runs.dynamic_energy_uj × time fraction",
                "base_energy":      "dynamic_energy_uj (L1 baseline-subtracted, NOT attributed)",
                "platform":         "All platforms — universal fallback",
                "confidence_basis": "C_source=0.70, C_method=0.50, C_validation=0.40, C_platform=0.50",
                "known_bias":       "Lower bound — CPU-proportional proxy misses NIC/uncore",
            },
            "doc":           "31-network-energy-cross-platform-methodology.md",
            "section":       "Section 3.3 — Strategy C: Time Fraction Fallback",
        },        
# ── v10: LLM Wait Energy Attribution ─────────────────────────────────────
        {
            "id":            "llm_wait_attribution_v1",
            "name":          "LLM Wait Energy — AXIS 3 Diagnostic Signal",
            "provenance":    "MODELED",
            "layer":         "application",
            "confidence":    0.85,
            "description":   (
                "Energy during LLM interaction windows that is wait-dominated. "
                "This is an AXIS 3 diagnostic signal — a named subset of "
                "E_orchestration for insight analysis only. "
                "It is NOT a conservation partition. It is NOT subtracted from "
                "E_attributed in D1. It is already inside E_orchestration. "
                "Key finding: this value is NON-ZERO even when cpu_percent_during_wait≈0 "
                "because DRAM and uncore remain active during remote API blocking. "
                "Formula: time-fraction proxy against attributed_energy_uj. "
                "Use for: AXIS 3B regression input, provider comparison, physics explanation."
            ),
            "formula_latex": (
                r"E_{llm\_wait} = E_{attr} \times \frac{t_{non\_local}}{t_{task}}"
                r"\quad \text{(AXIS 3 diagnostic — subset of } E_{orch} \text{, not a partition)}"
            ),
            "parameters":    {
                "source_column":    "llm_interactions.non_local_ms",
                "base_energy":      "attributed_energy_uj",
                "axis":             "AXIS 3A — System Dynamics Signal",
                "conservation_role": "NONE — diagnostic only, already inside E_orchestration",
                "key_insight":      "Non-zero at CPU≈0: DRAM/uncore active during remote blocking",
            },
            "doc":           "25-energy-attribution-guide.md",
            "section":       "Section 8.3 — llm_wait_energy_uj Diagnostic Subset",
        },
        {
            "id":            "llm_energy_sample_v2",
            "name":          "LLM Energy Attribution v2 (Direct RAPL Sample Measurement)",
            "provenance":    "MEASURED",
            "layer":         "application",
            "confidence":    0.97,
            "description":   (
                "LLM inference window energy measured directly from 100Hz RAPL samples "
                "using llm_interactions timestamp windows. "
                "E_llm_window = E_prefill + E_decode (two-term, AXIS 2A functional partition). "
                "E_prefill = SUM(samples in [request_start_ns..first_token_time_ns]) x cpu_frac "
                "= energy during prompt encoding (compute-dominated for local models). "
                "E_decode = SUM(samples in [first_token_time_ns..last_token_time_ns]) x cpu_frac "
                "= energy during token generation window. "
                "E_orchestration = E_attributed - E_llm_window (TWO-TERM residual — exact by construction). "
                "E_llm_wait stored separately as AXIS 3 diagnostic signal only — "
                "it is a subset of E_orchestration, NOT a conservation partition. "
                "Novel finding: DRAM and uncore remain active during remote API wait "
                "even when CPU≈0 — E_orchestration is non-trivial for remote providers. "
                "Fallback: time_fraction_fallback_v1 when timestamps NULL (confidence 0.70)."
            ),
            "formula_latex": (
                r"E_{prefill} = \sum_{s \in [t_{req}, t_{first}]} \Delta pkg_s \times \alpha_{cpu}"
                r",\quad E_{decode} = \sum_{s \in [t_{first}, t_{last}]} \Delta pkg_s \times \alpha_{cpu}"
                r",\quad E_{llm\_window} = E_{prefill} + E_{decode}"
                r",\quad E_{orch} = E_{attr} - E_{llm\_window}"
            ),
            "parameters":    {
                "source_timestamps":  "llm_interactions.request_start_ns, first_token_time_ns, last_token_time_ns",
                "energy_source":      "energy_samples.pkg_energy_uj delta per 100Hz interval",
                "cpu_attribution":    "runs.cpu_fraction applied to raw window energy",
                "fallback_method":    "time_fraction_fallback_v1 (confidence=0.70)",
                "d1_partition":       "TWO-TERM: E_attributed = E_llm_window + E_orchestration",
                "llm_wait_note":      "llm_wait_energy_uj = AXIS 3 diagnostic subset of E_orchestration",
                "novel_finding":      "DRAM/uncore non-zero during remote wait — E_orchestration non-trivial at CPU≈0",
            },
            "doc":           "15-llm-wait-energy-finding.md",
            "section":       "LLM Energy Attribution v2 — Sample-Based Measurement",
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
            "id":           "outlier_detection_v1",
            "name":         "Statistical and Domain-Rule Outlier Detection",
            "provenance":   "CALCULATED",
            "layer":        "orchestration",
            "output_metric":"run_outliers.severity",
            "output_unit":  "category",
            "applicable_on":["any"],
            "confidence":   0.85,
            "formula_latex": r"Z_{mod} = 0.6745 \cdot \frac{x_i - \mathrm{median}(X)}{\mathrm{MAD}(X)}, \quad \mathrm{MAD}(X) = \mathrm{median}(|x_i - \mathrm{median}(X)|)",
            "parameters":   {
                "config_table": "outlier_detection_config",
                "config_version": 1,
                "methods": "domain_rule, mad_zscore, iqr_fence",
                "z_threshold_suspect": 3.5,
                "z_threshold_extreme": 5.0,
                "iqr_multiplier": 2.5,
                "min_population_size": 10,
                "population_key": "task_name|workflow_type, computed within a single platform DB",
                "outlier_class_values": "data_quality_failure, statistical_anomaly (added migration v80)",
                "analysis_domains": "coverage (foundation), energy, gpu_energy, cpu_perf, thermal, llm_perf, orchestration, timing, system, identity (added migration v80)",
            },
            "description":  "Layer 3 of the three layer data selection model (experiments.is_valid is Layer 1, run_quality.experiment_valid is Layer 2). Three independent detection methods: domain rules (deterministic, zero cold start, e.g. overhead energy cannot exceed total energy), modified Z-score via median absolute deviation (robust to the extreme outliers it detects, primary statistical method, requires min_population_size runs), and IQR fence (cross check only, never escalates severity alone, only on agreement with MAD). Detector never auto-excludes: writes review_status='pending', a human must explicitly set 'confirmed' to remove a run from a clean view. Migration v80 added outlier_class (data_quality_failure vs statistical_anomaly) and purpose-conditional, domain-scoped filtering: 12 views (v_runs_clean_<domain> and v_runs_measured_<domain> for energy, cpu, thermal, llm, orchestration, system), plus the unchanged v1 blanket v_runs_clean and v_runs_unfiltered. clean tiers exclude confirmed outliers of either class; measured tiers exclude only confirmed data_quality_failure, retaining confirmed statistical_anomaly rows for distribution/tail/robustness analyses. See core/utils/outlier_detector.py, scripts/etl/compute_outliers.py, scripts/migrations/v80_outlier_v2_views.py.",
            "doc":          "32-outlier-detection-methodology.md",
            "section":      "Outlier Detection Methodology",
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
            "id":            "arm_pmu_v1",
            "name":          "ARM PMU Performance Counter Reader v1",
            "provenance":    "MEASURED",
            "layer":         "silicon",
            "confidence":    0.95,
            "description":   (
                "Reads ARM Neoverse V2 performance counters via Linux perf stat. "
                "Uses generic event names (instructions, cycles) for core IPC "
                "metrics and armv8_pmuv3/ prefixed events for cache hierarchy. "
                "Attaches to target process PID during measurement window. "
                "ARM PMU multiplexing may cause minor undercounting when more "
                "events are requested than PMU registers available — confidence 0.95."
            ),
            "formula_latex": r"\text{IPC} = \frac{\text{instructions}}{\text{cycles}}",
            "parameters":    {
                "sampling_mode": "pid-attach or system-wide",
                "events":        "instructions,cycles,armv8_pmuv3/l1d_cache_refill/,...",
                "platform":      "aarch64 ARMv8 PMUv3",
            },
            "doc":           "07-energy-readers-methodology.md",
            "section":       "ARM PMU Reader (arm_pmu_v1)",
            "fn":            None,
        },
        {
            "id":           "arm_thermal_sysfs_v1",
            "name":         "ARM Thermal sysfs Reader (acpitz zones)",
            "provenance":   "MEASURED",
            "layer":        "os",
            "confidence":   0.90,
            "description":  (
                "Reads thermal zone temperatures from /sys/class/thermal/thermal_zone*/temp "
                "on ARM Linux (GN100 Grace). All zones of type acpitz are discovered "
                "dynamically and averaged to produce package_temp_celsius. "
                "Used in place of SensorReader which requires x86-specific hwmon paths. "
                "Confidence 0.90: ACPI polling interval introduces ~100-200ms lag; "
                "averaging 7 zones obscures per-cluster variation."
            ),
            "formula_latex": r"T_{pkg} = \frac{1}{N}\sum_{i=1}^{N} T_i",
            "parameters":   {
                "source":           "/sys/class/thermal/thermal_zone*/temp",
                "unit":             "millidegrees Celsius (divided by 1000)",
                "zones_on_gn100":   7,
                "zone_type":        "acpitz",
                "platform":         "aarch64 Linux (GN100 Grace)",
            },
        }, 
        {
            "id":           "thermal_zone_sysfs_v2",
            "name":         "Normalized Per-Zone Thermal Reader V2",
            "provenance":   "MEASURED",
            "layer":        "os",
            "output_metric":"package_temp_celsius",
            "output_unit":  "°C",
            "applicable_on":["linux_x86_64", "linux_aarch64"],
            "formula_latex": r"T_{pkg} = f(\{T_i : \text{role}(i) \in \{\text{CPU\_PACKAGE, SOC}\}, \text{valid}(i)\})",
            "parameters":   {
                "source":        "/sys/class/thermal/thermal_zone*/temp",
                "unit":          "millidegrees Celsius / 1000",
                "valid_range":   "[-10.0, 125.0] Celsius",
                "quality_flags": "VALID | OUT_OF_RANGE | READ_FAILED | MISSING",
                "identity_key":  "(zone_type, zone_index) — stable across reboots",
            },
            "doc":          "08-thermal-subsystem.md",
            "section":      "Method Provenance",
        },
        {
            "id":           "cpuidle_sysfs_v1",
            "name":         "ARM cpuidle Sysfs Idle State Residency Reader V1",
            "provenance":   "MEASURED",
            "layer":        "os",
            "output_metric":"cpu_idle_states.residency_seconds",
            "output_unit":  "seconds (cumulative since boot)",
            "applicable_on":["linux_aarch64"],
            "formula_latex": r"\text{residency}_s = \frac{\sum_{t \in \text{states}} \text{time}_t[\mu s]}{10^6}",
            "parameters":   {
                "source":          "/sys/devices/system/cpu/cpu0/cpuidle/stateN/time",
                "unit":            "cumulative microseconds since boot, converted to seconds",
                "measurement_point":"end_of_run (single snapshot)",
                "residency_type":  "cumulative — not a per-run delta",
            },
            "doc":          "28-cpu-idle-states.md",
            "section":      "Method Provenance",
        },
        {
            "id":           "cooling_sysfs_v1",
            "name":         "Cooling Device State Reader V1",
            "provenance":   "MEASURED",
            "layer":        "os",
            "output_metric":"thermal_during_experiment",
            "output_unit":  "bool",
            "applicable_on":["linux_x86_64", "linux_aarch64"],
            "formula_latex": r"\text{throttled} = \exists i : \text{role}(i) \in \text{THROTTLE\_ROLES} \land \text{cur\_state}(i) > 0",
            "parameters":   {
                "source":          "/sys/class/thermal/cooling_device*/cur_state",
                "unit":            "kernel state enum (0=idle, max_state=full throttle)",
                "throttle_roles":  "CPU_FREQ_THROTTLE, POWER_CLAMP, TCC_OFFSET",
                "invalid_states":  "negative cur_state stored as OUT_OF_RANGE",
            },
            "doc":          "08-thermal-subsystem.md",
            "section":      "Method Provenance",
        },
        {
            "id":           "gpu_spbm_total_v1",
            "name":         "GPU SPBM Broad-Rail Total Energy",
            "provenance":   "MEASURED",
            "layer":        "silicon",
            "output_metric":"gpu_spbm_total_uj",
            "output_unit":  "µJ",
            "applicable_on":["linux_aarch64"],
            "formula_latex": r"E_{gpu,spbm} = \sum_i \Delta E_{gpu,spbm,i} \quad \text{(SPBM hwmon gpu rail, per-interval deltas, summed over run)}",
            "parameters":   {"domain_id": 7, "domain_name": "GPU", "source_table": "energy_sample_domains", "hwmon_channel": "gpu (energy4_input)"},
            "description":  "Total GPU energy from the SPBM broad rail (compute + GPU memory + NVLink-C2C + other on-package GPU consumers), distinct from DCGM's compute-only measurement. Sourced from SUM(energy_sample_domains.energy_uj) WHERE domain_id=7 for the run, where each row is a per-interval delta already computed by SPBMEnergyReader.read_energy()'s _delta('gpu') and written via the EnergyCollector/NormalizedWriter path. GN100/Grace platforms only — domain_id 7 has zero rows for any run on non-SPBM hardware (UBUNTU2505), correctly producing NULL per MIC-3, not an error. Verified 2026-06-21 against run_id=90: SPBM total 231040000 uJ vs DCGM (gpu_total_energy_uj) 174166000 uJ for the same run, SPBM > DCGM as expected since the broad rail includes hardware DCGM does not measure.",
            "doc":          "07-energy-readers-methodology.md",
            "section":      "GPU Dual-Channel Energy Measurement",
        },
        {
            "id":           "SPBM_INSTANTANEOUS_POWER_INTEGRATION_V1",
            "name":         "SPBM Power Rail Integration",
            "provenance":   "CALCULATED",
            "layer":        "silicon",
            "output_metric":"<rail>_energy_uj",
            "output_unit":  "µJ",
            "applicable_on":["linux_aarch64"],
            "formula_latex": r"E_{rail} = \sum_i P_{rail,i} \cdot \Delta t_i \quad \text{(numerical integration, rectangular)}",
            "parameters":   {"rail": "SOC_PKG | CPU_GPU | VCORE | DC_INPUT | PREREG | DLA", "sampling_rate_hz": 10, "integration_method": "rectangular"},
            "description":  "Energy for SPBM power channels with no hardware cumulative counter, estimated by numerical integration of sampled instantaneous power using the platform sampling interval. One parameterized method covers all 6 rails (soc_pkg, cpu_gpu, vcore, dc_input, prereg, dla) rather than near-duplicate per-rail entries, per SPEC_SPBM_FULL_TELEMETRY Section 8. Uncertainty model: raw sensor reading provenance is MEASURED with uncertainty_source sensor characteristics (vendor-defined, pending characterization — ADC resolution, firmware filtering, sensor latency, calibration). Integrated energy provenance is CALCULATED, uncertainty depends on raw sensor uncertainty plus sampling_interval plus integration_method. No numeric confidence value is asserted for either layer until a characterization pass against a known load is run (SPEC_SPBM_FULL_TELEMETRY Section 11, open item, not yet done). Rectangular integration chosen for implementation simplicity, matching the precedent in gpu_dynamic_run_local_v1; trapezoidal integration was considered and deferred, may be revisited if rectangular proves insufficiently accurate against the characterization pass.",
            "doc":          "07-energy-readers-methodology.md",
            "section":      "SPBM Full Power Telemetry",
        },
        {
            "id":           "spbm_conversion_loss_v1",
            "name":         "SPBM Conversion Loss (dc_input minus pkg)",
            "provenance":   "CALCULATED",
            "layer":        "silicon",
            "output_metric":"spbm_conversion_loss_uj",
            "output_unit":  "µJ",
            "applicable_on":["linux_aarch64"],
            "formula_latex": r"E_{loss} = E_{dc\_input} - E_{pkg}",
            "parameters":   {"depends_on": ["SPBM_INSTANTANEOUS_POWER_INTEGRATION_V1[dc_input]", "pkg energy counter (domain 1)"]},
            "description":  "Energy difference between the dc_input rail (outermost SPBM system boundary) and the pkg rail (package/silicon boundary). Hypothesized to represent conversion and voltage-regulation loss outside the package, but the physical measurement point of dc_input has not been verified against NVIDIA vendor documentation — see SPEC_SPBM_FULL_TELEMETRY Section 7b. This value must not be characterized in any paper as board power, wall power, or system input power until that verification is complete; until then it is documented only as the difference between two named SPBM rails. Inherits compound uncertainty from both inputs (dc_input's integration-derived uncertainty plus pkg's hardware-counter uncertainty).",
            "doc":          "07-energy-readers-methodology.md",
            "section":      "SPBM Full Power Telemetry",
        },
        {
            "id":           "spbm_conversion_efficiency_v1",
            "name":         "SPBM Conversion Efficiency (pkg / dc_input)",
            "provenance":   "CALCULATED",
            "layer":        "silicon",
            "output_metric":"spbm_conversion_efficiency",
            "output_unit":  "ratio",
            "applicable_on":["linux_aarch64"],
            "formula_latex": r"\eta = E_{pkg} / E_{dc\_input}",
            "parameters":   {"depends_on": ["SPBM_INSTANTANEOUS_POWER_INTEGRATION_V1[dc_input]", "pkg energy counter (domain 1)"], "range": "[0, 1] under normal operation, dimensionless"},
            "description":  "Dimensionless efficiency ratio, the normalized complement of spbm_conversion_loss_v1. Same dc_input semantic caution applies — see that entry and SPEC_SPBM_FULL_TELEMETRY Section 7b. Provided alongside the absolute loss metric because reviewers generally find percentage/ratio comparisons easier to evaluate across workloads of different duration and power draw than raw microjoule differences.",
            "doc":          "07-energy-readers-methodology.md",
            "section":      "SPBM Full Power Telemetry",
        },        
        {
            "id":           "gpu_spbm_dynamic_v1",
            "name":         "GPU SPBM Broad-Rail Dynamic Energy",
            "provenance":   "CALCULATED",
            "layer":        "silicon",
            "output_metric":"gpu_spbm_dynamic_uj",
            "output_unit":  "µJ",
            "applicable_on":["linux_aarch64"],
            "formula_latex": r"E_{gpu,spbm,dyn} = \max(0,\ E_{gpu,spbm,total} - E_{gpu,spbm,baseline})",
            "parameters":   {"baseline_domain_id": 7, "baseline_source": "idle_baseline_domains", "baseline_method": "most_recent_power_watts_times_duration", "depends_on": "gpu_spbm_total_v1"},
            "description":  "SPBM broad-rail dynamic energy, baseline-subtracted using the GPU/SPBM domain (domain_id 7) idle rate from idle_baseline_domains, the same rate-times-duration pattern already used for the existing gpu_baseline_energy_uj (DCGM-baselined) field. Clamped to zero — unlike gpu_residual_dynamic_uj, a negative SPBM dynamic value would indicate a baseline measurement problem rather than a meaningful diagnostic signal, so it is suppressed here.",
            "doc":          "07-energy-readers-methodology.md",
            "section":      "GPU Dual-Channel Energy Measurement",
        },
        {
            "id":           "gpu_residual_dynamic_v1",
            "name":         "GPU Residual Dynamic Energy (SPBM minus DCGM)",
            "provenance":   "CALCULATED",
            "layer":        "silicon",
            "output_metric":"gpu_residual_dynamic_uj",
            "output_unit":  "µJ",
            "applicable_on":["linux_aarch64"],
            "formula_latex": r"E_{gpu,residual} = E_{gpu,spbm,dyn} - E_{gpu,dyn}",
            "parameters":   {"depends_on": ["gpu_spbm_dynamic_v1", "gpu_dynamic_run_local_v1_or_gpu_dynamic_baseline_v1"], "clamped_to_zero": False},
            "description":  "Residual energy attributed to GPU subsystems outside compute: primarily GPU memory bandwidth and NVLink-C2C, hypothesized but not directly decomposable with current instrumentation (see SPEC_GPU_DUAL_CHANNEL Section 1). NOT clamped to zero — a negative residual is a valid diagnostic signal indicating baseline drift or measurement window misalignment between the two independent instruments (SPBM and DCGM), not an error to be suppressed. Derived from two other derived/baseline-subtracted quantities, so baseline measurement uncertainty compounds twice in this value; any paper using this metric must address confidence intervals explicitly, not just point estimates.",
            "doc":          "07-energy-readers-methodology.md",
            "section":      "GPU Dual-Channel Energy Measurement",
        },         
        {
            "id":            "arm_cpufreq_v1",
            "name":          "ARM cpufreq Sysfs Frequency Reader v1",
            "provenance":    "MEASURED",
            "layer":         "os",
            "confidence":    0.90,
            "description":   (
                "Reads CPU operating frequency from Linux cpufreq sysfs at 10 Hz "
                "during measurement window. Path: /sys/devices/system/cpu/cpu*/"
                "cpufreq/scaling_cur_freq (kHz, converted to MHz). "
                "Returns time-averaged frequency across all online CPUs. "
                "Confidence 0.90: sysfs polling has ~100ms granularity vs "
                "turbostat MSR timestamps at ~10ms on x86. ARM WFI/WFE idle "
                "states are not mapped to x86 c-states — c2/c3/c6/c7 are NULL."
            ),
            "formula_latex": r"\text{Avg\_MHz} = \frac{1}{N \cdot T} \sum_{t,i} f_{t,i}",
            "parameters":    {
                "sampling_hz":  10,
                "path_pattern": "/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq",
                "unit":         "kHz from sysfs, returned as MHz",
                "platform":     "aarch64 Linux",
            },
            "doc":           "07-energy-readers-methodology.md",
            "section":       "ARM cpufreq Reader (arm_cpufreq_v1)",
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
        {
            "id":            "failure_injection_v2",
            "name":          "Deterministic Failure Injector v2",
            "provenance":    "CALCULATED",
            "layer":         "orchestration",
            "confidence":    1.0,
            "output_metric": "tool_failure_events.error_message",
            "output_unit":   "flag",
            "applicable_on": ["tool_failure_events", "goal_attempt"],
            "formula_latex": r"rand = \frac{\text{SHA-256}(scenario\_id:rep:attempt:kind:tool)[0:8]_{uint64}}{2^{64}}",
            "parameters":    {
                "version":       2,
                "seeding":       "SHA-256 — stable across Python versions and process restarts",
                "modes":         ["deterministic_validation", "deterministic_stress", "statistical"],
                "slot_algorithm": "slot_i = round((i + 0.5) * N / K)",
                "supersedes":    "failure_injection_v1",
            },
            "doc":           "22-retry-tool-failure-methodology.md",
            "section":       "Failure Injection v2",
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

    # Formula from @formula decorator, fallback to class attribute
    # Formula from @formula decorator, fallback to per-reader hardcoded map
    _READER_FORMULAS = {
        "iokit_power_reader":   r"E = \sum_{i} \frac{P_i + P_{i+1}}{2} \cdot \Delta t_i \times 10^6",
        "iokit_thermal_reader": r"T_{die} = \max(T_{tdie0}, \ldots, T_{tdie10})",
    }
    formula_latex = ""
    for fn_name in ("get_energy_delta", "read_energy_uj"):
        fn = getattr(cls, fn_name, None)
        if fn and hasattr(fn, "_formula_latex"):
            formula_latex = fn._formula_latex
            break
    if not formula_latex:
        formula_latex = _READER_FORMULAS.get(cls.METHOD_ID, "")
    if not formula_latex:
        formula_latex = getattr(cls, "METHOD_FORMULA_LATEX", "")

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
        "confidence":        getattr(cls, "METHOD_CONFIDENCE", 1.0),
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
    parser.add_argument("--db",      default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.db:
        db_path = Path(args.db)
    else:
        from scripts.tools.path_loader import get_alems_db_path
        db_path = Path(get_alems_db_path())
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
