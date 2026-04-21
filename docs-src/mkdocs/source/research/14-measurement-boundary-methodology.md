# Measurement Boundary Methodology

**Document:** `research/14-measurement-boundary-methodology.md`
**Version:** v1 (post v9 migration)
**Method IDs:** `measurement_boundary_v1`, `measurement_coverage_v1`

---

## Overview

This document describes A-LEMS's measurement boundary model — how the system
precisely defines what constitutes "task time" vs "framework overhead time",
and why this distinction is critical for accurate energy attribution.

This is not a minor implementation detail. It is a **fundamental methodological
contribution**: we show that naive energy benchmarks systematically conflate
workload runtime with measurement-system overhead, biasing power metrics by
up to 50% for agentic workloads.

---

## The Measurement Boundary Problem

### What Prior Systems Do (Wrong)

Most energy benchmarking systems capture timestamps like this:

```
t_start = now()
start_energy_monitor()
execute_workload()
stop_energy_monitor()
t_end = now()                    ← PROBLEM: includes cleanup overhead
duration = t_end - t_start
avg_power = energy / duration    ← understated
```

The `t_end` capture happens after monitoring cleanup, log flushing,
metric aggregation, and database persistence. For simple workloads this
overhead is negligible (~10ms). For structured agentic AI workloads,
this overhead can be **26,000ms** — equal to the task itself.

### What A-LEMS Does (Correct)

A-LEMS uses three explicit timestamps:

```
t0 = run_start_perf    ← before start_measurement()
     execute_workload()
t1 = task_end_perf     ← immediately after executor.execute() returns
     stop_measurement()
     post_process()
t2 = run_end_perf      ← after all post-processing
```

This produces:

| Metric | Formula | Meaning |
|--------|---------|---------|
| `task_duration_ns` | t1 - t0 | Task execution time (canonical) |
| `framework_overhead_ns` | t2 - t1 | A-LEMS instrumentation cost |
| `total_run_duration_ns` | t2 - t0 | Full wall clock |
| `avg_task_power_watts` | E_pkg / task_duration | Correct power denominator |

---

## Empirical Discovery

### The 50% Gap Finding

Analysis of 1873 historical runs revealed a consistent pattern:

```
energy_samples coverage ≈ 48-50% of runs.duration_ns

Run 1873 (agentic, 52,943ms):
  energy_samples span = 26,320ms  ← task time
  runs.duration_ns    = 52,943ms  ← task + framework
  gap                 = 26,623ms  ← framework overhead

Run 1871 (agentic, 4,924ms):
  energy_samples span = 2,370ms
  runs.duration_ns    = 4,924ms
  gap                 = 2,554ms   ← 51.9% overhead
```

**This is structural, not noise.** Every single agentic run shows ~50%
overhead ratio. The pattern is consistent across 941 agentic runs.

### Root Cause

The energy sampler stops exactly when `executor.execute()` returns
(confirmed by timestamp alignment with `orchestration_events`).
But `run_end_perf` was captured after:

1. `stop_measurement()` — thread join, queue drain (~50-200ms)
2. `process_energy_samples()` — sample processing
3. `process_cpu_samples()` — turbostat processing
4. `build_result_dict()` — metric aggregation
5. `_read_temperature()` — sensor reads
6. Provenance collection

For large agentic runs (run 1873: 52,943ms), these post-task operations
took **26,623ms** — equal to the task itself.

---

## Formulas

### Task Duration (Primary Metric)

$$t_{task} = t_1 - t_0$$

Where $t_0$ = `run_start_perf` (before `start_measurement()`),
$t_1$ = `task_end_perf` (immediately after `executor.execute()` returns).

### Framework Overhead

$$t_{framework} = t_2 - t_1$$

Where $t_2$ = `run_end_perf` (after all post-processing).

### Framework Overhead Tax

$$\tau_{framework} = \frac{t_{framework}}{t_{task}}$$

High $\tau_{framework}$ indicates measurement system cost is proportional
to task complexity — a potential scalability concern for very short tasks.

### Corrected Average Power

$$\bar{P}_{task} = \frac{E_{pkg}}{t_{task}}$$

The legacy formula used $t_{total}$ in the denominator, understating power.

### Measurement Coverage

$$C = \frac{t_{last\_sample} - t_{first\_sample}}{t_{task}} \times 100$$

| Grade | Threshold | Interpretation |
|-------|-----------|---------------|
| Gold | ≥ 95% | Full measurement coverage |
| Acceptable | 80–95% | Minor gaps at boundaries |
| Poor | < 80% | Significant measurement gap — exclude from research |

---

## Historical Data Correction

### The Backfill Strategy

For all 1873 pre-v9 runs, `task_duration_ns` is estimated as:

$$t_{task}^{est} = \max(sample\_end\_ns) - runs.start\_time\_ns$$

This works because energy sampler stops within one sample interval
(10ms at 100Hz) of `executor.execute()` returning.

**Estimation error:** < 1% for runs > 1,000ms. For very short runs
(< 200ms), error may reach 5%.

All historical runs carry `duration_includes_overhead = 1` to flag
that their `duration_ns` includes framework overhead.

### Coverage Distribution (Historical Runs)

Expected coverage for pre-v9 runs:

| Workflow | Expected Coverage | Reason |
|----------|-----------------|--------|
| Agentic | ~48-50% | Large post-task overhead |
| Linear | ~37-50% | Varies with API latency |

Post-v9 new runs:

| Workflow | Expected Coverage | Reason |
|----------|-----------------|--------|
| All | > 95% | Correct task boundary |

---

## Impact on Downstream Metrics

| Metric | Pre-v9 (wrong) | Post-v9 (correct) |
|--------|---------------|-------------------|
| `avg_power_watts` | `E / (task + framework)` | `E / task` |
| `ooi_time` | `orchestration_ms / total_ms` | `orchestration_ms / task_ms` |
| Phase percentages | deflated ~50% | correct |
| Energy per second | understated | correct |
| Cross-workflow comparison | biased | valid |

---

## Platform Compliance (PAC)

The fix uses `time.perf_counter()` — Python's highest-resolution
monotonic timer. Platform support:

| Platform | Timer | Resolution | PAC Status |
|----------|-------|-----------|-----------|
| Linux x86 | CLOCK_MONOTONIC | ~1ns | ✅ MEASURED |
| Linux ARM | CLOCK_MONOTONIC | ~1ns | ✅ MEASURED |
| macOS | mach_absolute_time | ~1ns | ✅ MEASURED |
| Windows | QueryPerformanceCounter | ~100ns | ✅ MEASURED |

No platform-specific code in `harness.py` — fully PAC compliant.

---

## Research Significance

This finding has three dimensions of research value:

### 1. Methodological Contribution

We demonstrate that a widely-used benchmarking pattern (capture `t_end`
after monitoring teardown) introduces systematic duration inflation.
For agentic AI workloads, this bias is **~50%** — not a rounding error.

### 2. Optimization Insight

The framework overhead is proportional to task complexity:
- Simple tasks: ~200ms overhead
- Complex agentic tasks: ~26,000ms overhead

This suggests the A-LEMS post-processing pipeline scales poorly for
complex workloads and is itself a target for optimization.

### 3. Benchmark Quality Claim

> Prior AI energy benchmarks that report `energy / wall_clock_time`
> as average power systematically understate workload power consumption
> by including measurement-system overhead in the denominator. A-LEMS
> explicitly separates these boundaries and provides both the corrected
> task power and the framework overhead tax as first-class metrics.

---

## Validation Queries

See `config/research_queries.sql`:
- `RQ-03`: Coverage distribution across all runs
- `RQ-04`: Framework overhead tax measurement
- `RQ-10`: Legacy vs corrected power comparison
- `VQ-01`: L1 conservation check
- `DQ-01`: Phase energy alignment check

---

## References

1. Intel Corporation. *RAPL Energy Reporting Interface*, 2023.
2. Python Software Foundation. `time.perf_counter()` documentation, 2024.
3. Panigrahy, D. *A-LEMS Measurement Boundary Model v1*, 2026.
