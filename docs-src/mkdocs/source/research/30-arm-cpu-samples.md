---
**Method ID:** arm_pmu_v1 (16C, existing), arm_cpu_sample_writer_v1 (16D3, new)
**Schema version:** cpu_samples table (existing, no new migration)
**Platforms verified:** NVIDIA Grace GB10 (aarch64)
**Status:** PRODUCTION
**Last updated:** 2026-06-19
---

# ARM PMU Cache Metrics in cpu_samples

## Overview

The `cpu_samples` table is the primary source for hardware performance counter
data aggregated by `aggregate_hardware_metrics` ETL into the `runs` table
columns `l1d_cache_misses_total`, `l2_cache_misses_total`, `l3_cache_hits_total`,
and `l3_cache_misses_total`. On x86, turbostat writes continuous per-second
rows to `cpu_samples` during measurement. On ARM (Grace aarch64), turbostat
is not available.

This document describes how ARM PMU (Performance Monitor Unit) counter data
from `ARMPMUReader` reaches `cpu_samples` so that the ETL pipeline produces
cache metric columns on ARM runs identically to x86 runs.

### The Gap This Fills

After 16C, `ARMPMUReader` returns a `PerformanceCounters` object with accurate
L1/L2/L3 cache miss counts and instruction/cycle counts for the full experiment
run. These values existed only in memory — nothing wrote them to `cpu_samples`.
The ETL found no rows and left cache columns NULL on every ARM run.

This implementation writes one summary row to `cpu_samples` at experiment end,
containing the full-run aggregate counts. One row is sufficient because the
ETL uses `SUM()` across rows: one row with total counts equals N rows summing
to the same total.

---

## Platform Coverage

| Platform | Architecture | PMU Source | cpu_samples Written By | Status |
|----------|-------------|-----------|----------------------|--------|
| NVIDIA Grace GB10 | aarch64 | `perf` ARM PMU events | `arm_cpu_sample_builder.py` (one summary row) | VERIFIED |
| Intel i7-1165G7 | x86_64 | turbostat | turbostat sampling loop (continuous rows) | VERIFIED |
| AMD Ryzen | x86_64 | turbostat | turbostat sampling loop (continuous rows) | PENDING |
| Apple M1 Pro | arm64 | IOKit (future) | Not yet implemented | PLANNED |

---

## Schema: `cpu_samples` Columns Used on ARM

No new schema migration. These columns already exist in `cpu_samples`:

| Column | ARM Source | ETL Destination |
|--------|-----------|-----------------|
| `run_id` | run_id parameter | FK |
| `timestamp_ns` | `time.time_ns()` at write | traceability |
| `cpu_avg_mhz` | `ARMCPUFreqReader` summary mean | `runs.frequency_mhz` |
| `cpu_busy_mhz` | same as `cpu_avg_mhz` (ARM has no separate busy freq) | `runs.cpu_avg_mhz` |
| `l1d_cache_misses` | `PerformanceCounters.l1d_cache_misses` | `runs.l1d_cache_misses_total` |
| `l2_cache_misses` | `PerformanceCounters.l2_cache_misses` | `runs.l2_cache_misses_total` |
| `l3_cache_hits` | `PerformanceCounters.l3_cache_hits` | `runs.l3_cache_hits_total` |
| `l3_cache_misses` | `PerformanceCounters.l3_cache_misses` | `runs.l3_cache_misses_total` |
| `instructions` | `PerformanceCounters.instructions_retired` | `runs.instructions` |
| `cycles` | `PerformanceCounters.cpu_cycles` | `runs.cycles` |
| `ipc` | `PerformanceCounters.instructions_per_cycle()` | `runs.ipc` |
| `package_temp` | NULL (thermal handled separately by ThermalAggregator) | N/A |

---

## Method Provenance

### ARM summary row

| Field | Value |
|-------|-------|
| Method | `arm_cpu_sample_writer_v1` |
| Layer | `os` |
| Provenance | `MEASURED` (PMU counters) |
| Confidence | 0.95 (inherited from `arm_pmu_v1` — see 16C methodology) |
| Source | `PerformanceCounters` from `ARMPMUReader` |

ARM PMU counters are read via `perf` system calls with ARM-specific event codes.
Confidence 0.95 reflects that ARM PMU event counts are accurate hardware
readings but have not yet been cross-validated against an independent ground
truth on the GN100 platform. When cross-validation is performed, this score
should be updated.

### ETL data flow

```
ARMPMUReader.stop_monitoring()
    → PerformanceCounters (in memory, in result dict)
        → _build_arm_cpu_sample_row()
            → db.insert_cpu_samples(run_id, [row])
                → aggregate_hardware_metrics(run_id)
                    → runs.l1d_cache_misses_total  (SUM of one row = row value)
                    → runs.l2_cache_misses_total
                    → runs.l3_cache_hits_total
                    → runs.l3_cache_misses_total
```

The `aggregate_hardware_metrics` ETL already runs automatically after each
pair save at lines 1032-1033 of `experiment_runner.py`. No additional ETL
call is needed.

---

## Query Reference

**1. Confirm ARM cpu_samples row exists after experiment**

```sql
SELECT run_id, cpu_avg_mhz, l1d_cache_misses, l2_cache_misses,
       l3_cache_hits, l3_cache_misses, instructions, cycles, ipc
FROM cpu_samples
ORDER BY rowid DESC
LIMIT 2;
```

Expected on GN100: one row per run with non-zero cache and instruction counts.

**2. Confirm ETL populated runs table cache columns**

```sql
SELECT id, run_type,
       l1d_cache_misses_total, l2_cache_misses_total,
       l3_cache_hits_total, l3_cache_misses_total,
       instructions, cycles, ipc
FROM runs
ORDER BY id DESC
LIMIT 2;
```

Expected: non-NULL, non-zero values on GN100 after this implementation.
Before this implementation: all NULL on aarch64 runs.

**3. Cache miss rate per run (derived metric for paper)**

```sql
SELECT id, run_type,
       ROUND(CAST(l1d_cache_misses_total AS REAL) / instructions * 100, 2) as l1_miss_pct,
       ROUND(CAST(l2_cache_misses_total  AS REAL) / instructions * 100, 2) as l2_miss_pct,
       ROUND(CAST(l3_cache_misses_total  AS REAL) / instructions * 100, 2) as l3_miss_pct
FROM runs
WHERE instructions > 0
ORDER BY id DESC
LIMIT 10;
```

**4. Cross-platform IPC comparison**

```sql
SELECT id, run_type,
       ROUND(ipc, 3) as ipc,
       ROUND(CAST(cycles AS REAL) / instructions, 3) as cpi,
       pkg_energy_uj
FROM runs
WHERE instructions > 0
ORDER BY id DESC
LIMIT 20;
```

---

## Verification

```bash
# Step 1: confirm ARM row written to cpu_samples on GN100
RUN_ID=$(sqlite3 /mnt/alems-data/$(hostname)/experiments.db \
  "SELECT MAX(id) FROM runs;")

sqlite3 /mnt/alems-data/$(hostname)/experiments.db "
SELECT run_id, l1d_cache_misses, l2_cache_misses,
       l3_cache_hits, l3_cache_misses, instructions, cycles, ipc
FROM cpu_samples WHERE run_id = $RUN_ID;"
# Expected: non-zero values for all columns

# Step 2: confirm ETL populated runs table
sqlite3 /mnt/alems-data/$(hostname)/experiments.db "
SELECT id, l1d_cache_misses_total, l2_cache_misses_total,
       l3_cache_hits_total, l3_cache_misses_total
FROM runs WHERE id = $RUN_ID;"
# Expected: same values as cpu_samples (ETL does SUM of one row = row value)

# Step 3: confirm x86 is unaffected — run existing test suite on UBUNTU2505
python3 -m pytest tests/ -q 2>&1 | tail -5
# Expected: all tests pass, no regressions

# Step 4: confirm no duplicate rows written (one per run, not multiple)
sqlite3 /mnt/alems-data/$(hostname)/experiments.db "
SELECT run_id, COUNT(*) as row_count
FROM cpu_samples
GROUP BY run_id
ORDER BY run_id DESC LIMIT 4;"
# GN100: exactly 1 row per run
# UBUNTU2505: N rows per run (one per turbostat sample interval) — unchanged
```

---

## Known Limitations

**One row vs continuous sampling:** x86 turbostat writes one row per second
during the experiment, enabling time-series analysis of frequency and cache
behavior within a run. The ARM summary row is a single aggregate for the full
run. Intra-run variation in cache miss rate is not captured. For LLM inference
runs where the dominant cost is the generation phase, this is acceptable.
For multi-phase workloads, per-phase breakdown would require phase-tagged
ARM PMU snapshots (deferred).

**cpu_busy_mhz approximation:** ARM has no separate busy vs total frequency
reporting at the same granularity as turbostat's `Bzy_MHz` column. Both
`cpu_busy_mhz` and `cpu_avg_mhz` are set to `ARMCPUFreqReader`'s mean
frequency. Downstream analysis that depends on busy/average ratio should note
this. The affected ETL computation (`frequency_mhz` in runs) uses `cpu_avg_mhz`
directly so there is no error in the paper metric.

**package_temp is NULL:** Temperature in the cpu_samples row is NULL on ARM.
The ThermalAggregator writes thermal columns to `runs` via a separate path
(from `thermal_samples_v2`). Having NULL in `cpu_samples.package_temp` does
not affect any ETL output.
