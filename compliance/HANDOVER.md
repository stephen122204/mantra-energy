# A-LEMS Development Handover — Chunks 1,2,3,5,9,1.3,12 Complete

---

## MUST READ FIRST

```
compliance/COMPLIANCE.md    ← mandatory rules every agent must follow
compliance/IMPROVEMENTS.md  ← all known issues and tech debt
```

---

## Project State

```
Repo:    ~/mydrive/alems-platform
DB:      data/experiments.db (SQLite)
Venv:    source venv/bin/activate
Python:  3.13.7
```

---

## Completed Chunks

```
Chunk 1    ✅  Platform detection + ReaderFactory
Chunk 2    ✅  Sample tables raw start/end schema
Chunk 9    ✅  Methodology & Provenance
Chunk 3    ✅  CPU Fraction Attribution
Chunk 1.3  ✅  DB: energy_measurement_mode column
Chunk 5    ✅  Phase Energy Attribution (normalized)
Chunk 12   ✅  Hardware Telemetry (cache, disk, voltage, fan)
Chunk 1.1  ⏸  IOKit macOS (needs Mac hardware)
Chunk 1.2  ⏸  ARM ML estimation (needs Chunk 7 model)
```

---

## Chunk 12 — What Was Built

### New Tables
```
io_samples   — disk I/O at 10Hz (/proc/diskstats delta)
```

### New Columns
```
cpu_samples:     l1d_cache_misses, l2_cache_misses, l3_cache_hits, l3_cache_misses
thermal_samples: voltage_vcore, fan_rpm
runs:            l1d_cache_misses_total, l2_cache_misses_total, l3_cache_hits_total,
                 l3_cache_misses_total, disk_read_bytes_total, disk_write_bytes_total,
                 voltage_vcore_avg
```

### New Files
```
core/readers/disk_reader.py                ← Linux /proc/diskstats reader
core/readers/darwin/disk_reader.py         ← macOS IOKit stub (returns None)
core/readers/fallback/disk_reader.py       ← fallback stub (returns None)
scripts/migrations/019_hardware_telemetry.sql
scripts/etl/aggregate_hardware_metrics.py  ← ETL: sample tables → runs aggregates
config/methodology_refs/hardware_telemetry.yaml
docs-src/.../14-hardware-readers-developer-guide.md
compliance/COMPLIANCE.md
compliance/IMPROVEMENTS.md
```

### Known Hardware Behavior (UBUNTU2505 ThinkPad)
```
l1d_cache_misses = 0      ← PMU event not available on this Intel CPU
voltage_vcore    = NULL   ← Vcore not exposed via hwmon on ThinkPad
disk_read_bytes  = 0      ← NVMe page cache absorbs I/O in normal runs
fan_rpm          = 1800   ← working ✅
```

---

## Current Sample Table Status

```
energy_samples    100Hz  ✅ pkg/core/dram/uncore start+end cumulative
cpu_samples        10Hz  ✅ turbostat + perf cache (l2/l3 populated)
interrupt_samples  10Hz  ✅ /proc/stat ticks (total + proc)
io_samples         10Hz  ✅ /proc/diskstats deltas
thermal_samples     1Hz  ✅ hwmon temp + fan (voltage NULL on ThinkPad)
```

---

## ETL Pipeline

```
save_pair() completes
    → process_run_async(agentic_id)        ← phase attribution
    → aggregate_async(agentic_id)          ← hardware metrics
    → aggregate_async(linear_id)           ← hardware metrics

Manual run:
    python scripts/etl/phase_attribution_etl.py --run-id <id>
    python scripts/etl/aggregate_hardware_metrics.py --run-id <id>

Backfill:
    python scripts/etl/phase_attribution_etl.py --backfill-all
    python scripts/etl/aggregate_hardware_metrics.py --backfill-all
```

---

## Regression Suite

```bash
bash scripts/test_provenance.sh                   # 22/22
bash scripts/test_runs_regression.sh              # 20/21 (frequency pre-existing)
bash scripts/test_runs_regression_extended.sh     # 61/63 (2 pre-existing)
python scripts/validate_phase_attribution.py      # 5/5
```

---

## Key File Map (Updated)

```
core/readers/interfaces.py          ABCs: EnergyReaderABC, CPUReaderABC, DiskReaderABC
core/readers/factory.py             ReaderFactory — platform routing
core/readers/disk_reader.py         NEW — Linux /proc/diskstats
core/readers/darwin/disk_reader.py  NEW — macOS stub
core/readers/fallback/disk_reader.py NEW — fallback stub
core/readers/perf_reader.py         + L1d/L2/L3 cache events
core/readers/sensor_reader.py       + read_fan_rpm()
core/readers/proc_reader.py         Chunk 3 — process tick reader
core/readers/scheduler_monitor.py   + total_ticks + proc_ticks per sample
core/energy_engine.py               + DiskReader + io_samples collection
core/execution/harness.py           + io_samples in result dict
core/execution/sample_processor.py  + perf cache → cpu_samples
core/execution/experiment_runner.py + insert_io_samples + aggregate_async
core/database/schema.py             + io_samples table + all new columns
core/database/repositories/samples.py + insert_io_samples + cache columns
core/database/manager.py            + insert_io_samples delegation
core/models/raw_energy_measurement.py + io_samples field
core/models/performance_counters.py + l1d/l2/l3 fields
core/utils/provenance.py            + 10 new column entries
scripts/seed_methodology.py         + 3 new hardware methods (25 total)
scripts/etl/aggregate_hardware_metrics.py NEW
scripts/migrations/019_hardware_telemetry.sql NEW
compliance/COMPLIANCE.md            NEW — mandatory rules
compliance/IMPROVEMENTS.md          NEW — tech debt register
```

---

## Next Chunks (Recommended Order)

```
Chunk 14  — Platform readers cleanup (factory routing, docs, comments)
Chunk 6   — Attribution views + normalization (depends on sample data)
Chunk 4   — TTFT/TPOT capture
Chunk 7   — Model factory + 8 adapters
Chunk 1.2 — ARM ML estimation (after Chunk 7)
Chunk 1.1 — IOKit real implementation (needs Mac hardware)
Chunk 8   — Hallucination & retry tables
Chunk 10  — experiment_valid enhancement
Chunk 11  — Code quality & logging
Chunk 13  — run_metrics_agg (if needed after Chunk 6 analysis)
```

---

## Before Starting Any Chunk

```bash
# 1. Read compliance docs
cat compliance/COMPLIANCE.md
cat compliance/IMPROVEMENTS.md

# 2. Verify baseline
bash scripts/test_provenance.sh
bash scripts/test_runs_regression_extended.sh

# 3. Grep before writing — never assume
grep -n "term" path/to/file | head -10
```

---

## Interaction Rules for Next Agent

```
1. ALWAYS grep before writing — never assume file contents
2. Read schema.py before ANY DB change
3. Check COLUMN_PROVENANCE + METHOD_CONFIDENCE for every new runs column
4. Give real runnable code — not comment-only patch files
5. 30% inline comments, docstrings on every method
6. Max 8 space indentation, early return pattern
7. After each change: grep to verify, then run test suite
8. User runs commands, pastes output — agent writes code
9. Low token mode — grep surgically, never cat full files
10. Give flat copy commands: cp /home/dpani/Downloads/chunkN/file.py path/
11. Surgical find/replace — never rewrite whole files
12. No debug prints — use logger.debug()
13. PAC compliance: ABC → Factory → Reader chain always
14. MPC compliance: provenance + seed + yaml + doc always
```

---

## Test Command

```bash
python -m core.execution.tests.test_harness \
    --task-id gsm8k_basic --repetitions 1 \
    --provider local --verbose
```
