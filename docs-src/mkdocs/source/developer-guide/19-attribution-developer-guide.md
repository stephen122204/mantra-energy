# Chunk 6: Energy Attribution Developer Guide

**File:** `docs-src/mkdocs/source/developer-guide/19-chunk6-attribution-developer-guide.md`  
**Chunk:** 6  
**Status:** Complete  
**Tests:** 34/34 ✅

---

## Overview

Chunk 6 adds three major systems to A-LEMS:

1. **Multi-layer energy attribution** — decomposes pkg_energy_uj into L0-L5 layers
2. **Measurement boundary correction** — fixes systematic 50% duration inflation
3. **Normalization factors schema** — prepares for Chunk 8 outcome normalisation

---

## Part 1: Multi-Layer Energy Attribution

### What Problem Does This Solve?

Before Chunk 6, A-LEMS stored `pkg_energy_uj` — the total CPU package energy
measured by RAPL. This single number answers "how much energy was used?" but
not "where did that energy go?"

Chunk 6 adds `energy_attribution` table which answers:
- How much was idle background (would have happened anyway)?
- How much was actually our process vs other processes?
- How much was the LLM API call vs orchestration planning?
- How much energy is unaccounted for (quality indicator)?

### The Five-Layer Model

```
pkg_energy_uj (RAPL measurement — ground truth)
│
├── L0: Hardware domains (core, dram, uncore)
│
├── L1: Baseline isolation
│   baseline_energy_uj + dynamic_energy_uj = pkg_energy_uj
│   dynamic = what's above idle
│
├── L2: Process isolation (heuristic)
│   attributed_energy_uj = cpu_fraction × dynamic_energy_uj
│   other_process_energy_uj = dynamic - attributed
│
├── L3: Workflow phase decomposition (time proxy)
│   planning + execution + synthesis + gap = attributed
│   gap ≈ LLM API wait time
│
├── L4: Compute type (NULL — Chunk 4/8)
│   llm_inference + tool_execution + network_wait = execution
│
└── L5: Outcome normalisation
    energy_per_token = pkg / completion_tokens
    orchestration_tax = (planning + synthesis) / attributed
```

### The energy_attribution Table

Located in: `core/database/schema.py` → `CREATE_ENERGY_ATTRIBUTION`

One row per run. Populated by `scripts/etl/energy_attribution_etl.py`.

**Column groups:**

```sql
-- L0: Hardware (mirrors runs RAPL columns)
pkg_energy_uj, core_energy_uj, dram_energy_uj, uncore_energy_uj

-- L1: System overhead
background_energy_uj   -- energy not attributable to workload or OS services
interrupt_energy_uj    -- estimated from interrupt_rate × 0.5µJ
scheduler_energy_uj    -- estimated from context_switches × 1µJ

-- L2: Resource contention (all INFERRED via time-fraction)
network_wait_energy_uj  -- (non_local_ms / duration_ms) × pkg
io_wait_energy_uj       -- (io_block_time_ms / duration_ms) × pkg
disk_energy_uj          -- (disk_bytes / 1024) × 0.1µJ/KB
memory_pressure_energy_uj -- page_faults × 10µJ
cache_dram_energy_uj    -- dram × (l3_misses / l3_total)

-- L3: Workflow phases
orchestration_energy_uj  -- attributed - application
planning_energy_uj       -- from orchestration_events / runs table
execution_energy_uj      -- from orchestration_events / runs table
synthesis_energy_uj      -- from orchestration_events / runs table
tool_energy_uj           -- NULL (Chunk 8)
retry_energy_uj          -- NULL (Chunk 8)
failed_tool_energy_uj    -- NULL (Chunk 8)
rejected_generation_energy_uj -- NULL (Chunk 8)

-- L4: Model compute
llm_compute_energy_uj    -- attributed × UCR (utilisation compute ratio)
prefill_energy_uj        -- NULL (Chunk 4)
decode_energy_uj         -- NULL (Chunk 4)

-- L5: Outcome
energy_per_completion_token_uj  -- pkg / completion_tokens
energy_per_successful_step_uj   -- pkg / steps
energy_per_accepted_answer_uj   -- NULL (Chunk 8)
energy_per_solved_task_uj       -- NULL (Chunk 8)

-- Thermal
thermal_penalty_energy_uj  -- time-weighted throttle penalty
thermal_penalty_time_ms    -- ms above 85°C threshold

-- Residual + quality
unattributed_energy_uj    -- pkg - Σ all layers
attribution_coverage_pct  -- (pkg - unattributed) / pkg × 100
attribution_model_version -- 'v1'
```

### The ETL Script

**File:** `scripts/etl/energy_attribution_etl.py`

**Key functions:**

```python
compute_energy_attribution(run_id, db_path)
    → fetches run row
    → computes all L0-L5 values
    → INSERT OR REPLACE into energy_attribution

backfill_all(db_path)
    → runs compute_energy_attribution for every run_id in runs table

attribution_async(run_id, db_path)
    → async wrapper for experiment_runner.py save_pair()
```

**UCR (Utilisation Compute Ratio):**
```python
ucr = compute_time_ms / duration_ms
# compute_time_ms = time process was doing CPU compute (from runs table)
# ucr is clamped to [0, 1]

application_energy = attributed × ucr     # LLM compute
orchestration_energy = attributed - application  # coordination overhead
```

**Thermal penalty (time-weighted):**
```python
throttle_ratio = Σ(interval_ns where cpu_temp > 85°C) / Σ(all interval_ns)
thermal_penalty = pkg × throttle_ratio × 0.20
# Source: thermal_samples table
```

**Running manually:**
```bash
python scripts/etl/energy_attribution_etl.py --run-id 1234
python scripts/etl/energy_attribution_etl.py --backfill-all
```

---

## Part 2: Measurement Boundary Correction

### The Bug That Was Found

During Chunk 6 analysis, we discovered that `runs.duration_ns` was being
captured AFTER all post-processing (stop_measurement, ETL, sample processing).
For agentic runs, this added ~25 seconds of framework overhead to every run's
duration, making `avg_power_watts = pkg / duration` understate true power by ~50%.

### The Fix in harness.py

**Before (wrong):**
```python
exec_result = executor.execute(task)
raw_energy = self.energy_engine.stop_measurement()
run_end_perf = time.perf_counter()     ← captured too late
run_duration_sec = run_end_perf - run_start_perf  ← includes ETL overhead
```

**After (correct):**
```python
exec_result = executor.execute(task)
task_end_perf = time.perf_counter()   ← captured immediately after task
raw_energy = self.energy_engine.stop_measurement()
run_end_perf = time.perf_counter()
task_duration_sec = task_end_perf - run_start_perf   ← task only
framework_overhead_sec = run_end_perf - task_end_perf  ← ETL cost
```

**Also added:** RAPL capture before pre-task reads:
```python
_rapl_before_pretask = self.energy_engine.rapl.read_energy()  ← NEW
_pre_task_start_perf = time.perf_counter()                    ← NEW
# Then pre-task reads happen...
run_start_perf = time.perf_counter()
self.energy_engine.start_measurement()
```

This captures `pre_task_energy_uj` — energy during interrupt/temp/governor
reads. ~600µJ diagnostic value, NOT part of attribution model.

### New Columns in runs Table

```sql
task_duration_ns           -- canonical energy denominator
framework_overhead_ns      -- post-task processing cost
total_run_duration_ns      -- full wall clock (legacy compat)
duration_includes_overhead -- 1=historical, 0=new corrected run
energy_sample_coverage_pct -- C = sample_span/task_duration × 100
avg_task_power_watts       -- pkg / task_duration (corrected)
pre_task_energy_uj         -- RAPL delta during context reads (diagnostic)
pre_task_duration_ns       -- time of pre-task reads
```

### Coverage Metric

```
C = (last_sample_ns - first_sample_ns) / task_duration_ns × 100

gold:       C ≥ 95%  → reliable measurement
acceptable: C 80-95% → minor gaps at boundaries
poor:       C < 80%  → excluded from research queries
```

For historical runs: C ≈ 48-50% (energy sampler stopped when executor
returned, but duration included 25s of ETL).
For new runs after fix: C > 95%.

### The Duration Fix ETL

**File:** `scripts/etl/duration_fix_etl.py`

**Key functions:**

```python
fix_run(run_id, db_path)
    → for historical runs: estimates task_duration from energy_samples span
    → computes coverage, power, framework overhead
    → UPDATE runs SET task_duration_ns = ...

fix_run_with_pretask(run_id, rapl_before, pre_task_sec, db_path)
    → for NEW runs: uses actual RAPL capture
    → computes pre_task_energy_uj from rapl_before - rapl_start

duration_fix_async(run_id, rapl_before, pre_task_sec, db_path)
    → async wrapper for experiment_runner.py
```

**Running manually:**
```bash
python scripts/etl/duration_fix_etl.py --run-id 1234
python scripts/etl/duration_fix_etl.py --backfill-all
```

---

## Part 3: Normalization Factors

### What It Is

`normalization_factors` table stores per-run context for fair energy comparison.
Without this, comparing energy across tasks of different difficulty is meaningless.

### Current State

**Schema:** Created ✅  
**Data:** Empty ✅ (intentional — Chunk 8 dependency)

### Why Empty Now

Behavioural factors (successful_goals, total_retries, hallucination_rate)
require Chunk 8 tables:
- `query_execution` — tracks goal completion
- `query_attempt` — tracks retry depth
- `hallucination_events` — tracks hallucination detection

### Column Groups

```sql
-- Structural (from task config + orchestration_events)
difficulty_score, difficulty_bucket, task_category, workload_type
max_step_depth, branching_factor, input_tokens, output_tokens
context_window_size, total_work_units

-- Behavioural (NULL until Chunk 8)
successful_goals, attempted_goals, failed_attempts
retry_depth, total_retries, total_failures
total_tool_calls, failed_tool_calls
hallucination_count, hallucination_rate

-- Resource
rss_memory_gb, cache_miss_rate, io_wait_ratio, stall_time_ms
sla_violations
```

---

## Part 4: Views

### How to Use Views

All views are created in `scripts/migrations/v8_normalization_views.sql`
and registered in `core/database/schema.py` → `CREATE_NORMALIZATION_VIEWS`.

They are created automatically when `sqlite_adapter.py` initialises.

### v_energy_normalized — Primary Research View

```sql
SELECT run_id, workflow_type,
       total_energy_j, compute_energy_j, memory_energy_j,
       foreground_energy_j,        -- pkg - background (computed inline)
       energy_per_token_uj,        -- µJ per token
       avg_power_watts,            -- CORRECTED power (uses task_duration)
       orchestration_ratio,        -- orchestration/pkg (0-1)
       unattributed_ratio,         -- research quality metric
       attribution_coverage_pct
FROM v_energy_normalized
WHERE workflow_type = 'agentic'
ORDER BY run_id DESC;
```

**Key design:** `foreground_energy_j` is NOT stored in the table —
it's computed inline as `(pkg - background) / 1e6`.
This avoids stale data if background is re-computed.

### v_attribution_summary — Dashboard View

```sql
SELECT run_id, workflow_type,
       total_j, compute_j, memory_j, background_j,
       orchestration_j, planning_j, execution_j, synthesis_j,
       llm_compute_j, unattributed_j,
       compute_pct, orchestration_pct, application_pct,
       unattributed_pct, attribution_coverage_pct
FROM v_attribution_summary;
```

**pct columns** are computed inline:
```sql
ROUND(core_energy_uj * 100.0 / NULLIF(pkg_energy_uj, 0), 2) AS compute_pct
```
Never stored — always fresh from underlying data.

### v_orchestration_overhead — Research Comparison View

```sql
SELECT run_id, workflow_type,
       orchestration_j, total_j,
       ooi_time,          -- orchestration_cpu_ms / duration_ms
       planning_j, execution_j, synthesis_j,
       planning_time_ms, execution_time_ms, synthesis_time_ms,
       llm_calls, tool_calls, steps
FROM v_orchestration_overhead;
```

### v_outcome_efficiency — Outcome View (mostly NULL until Chunk 8)

```sql
SELECT run_id, workflow_type,
       energy_per_completion_token_uj,
       energy_per_successful_step_uj,
       energy_per_accepted_answer_uj,   -- NULL until Chunk 8
       energy_per_solved_task_uj,       -- NULL until Chunk 8
       difficulty_score,                -- NULL until Chunk 8
       successful_goals,                -- NULL until Chunk 8
       attempt_efficiency_ratio         -- NULL until Chunk 8
FROM v_outcome_efficiency;
```

---

## Part 5: Provenance Compliance

### How energy_attribution Columns Are Tracked

Unlike `runs` table columns which flow through `record_run_provenance()`,
`energy_attribution` columns use the `ea.` prefix convention in `COLUMN_PROVENANCE`.

This was a deliberate design decision: `energy_attribution` is a satellite
table, not the main `runs` table. The `ea.` prefix distinguishes them.

**Important:** `record_run_provenance()` only covers `runs` table columns.
The `ea.*` entries in `COLUMN_PROVENANCE` are for documentation/audit purposes
and future provenance coverage extension.

### Method Confidence Values

```python
# In core/utils/provenance.py METHOD_CONFIDENCE:
"energy_attribution_v1":    0.95   # L0-L3 multi-layer model
"thermal_penalty_weighted": 0.85   # time-weighted penalty
"normalization_factors_v1": 0.90   # structural factors
"measurement_boundary_v1":  1.0    # perf_counter — all platforms
"measurement_coverage_v1":  1.0    # derived from timestamps
```

### Adding New Columns (future chunks)

When Chunk 8 populates `normalization_factors`:

1. The `nf.*` entries in `COLUMN_PROVENANCE` are already there
2. No new COLUMN_PROVENANCE entries needed
3. Just implement the ETL that fills the data
4. Run `bash scripts/test_provenance.sh` — should still pass 34/34

When Chunk 4 adds TTFT/TPOT for L4 decomposition:

1. Add `ea.prefill_energy_uj` and `ea.decode_energy_uj` entries to COLUMN_PROVENANCE
2. Add method to seed_methodology.py
3. Add METHOD_CONFIDENCE entry
4. Update ETL to compute from TTFT data

---

## Part 6: mkdocs.yml Updates Needed

Add to `docs-src/mkdocs/mkdocs.yml` nav section:

**Under `research:`** (after line 73, Phase Attribution):
```yaml
    - Energy Attribution: research/12-energy-attribution-methodology.md
    - Normalization Factors: research/13-normalization-factors-methodology.md
    - Measurement Boundary: research/14-measurement-boundary-methodology.md
```

**Under `developer-guide:`** (after existing entries):
```yaml
    - Chunk 6 Attribution Guide: developer-guide/19-chunk6-attribution-developer-guide.md
```

---

## Part 7: Compliance Checklist

| Rule | Status | Notes |
|------|--------|-------|
| PAC-2: No platform imports outside factory | ✅ | ETL uses no readers |
| MPC-1: All new runs columns in COLUMN_PROVENANCE | ✅ | 8 new columns added |
| MPC-1: energy_attribution columns in COLUMN_PROVENANCE | ✅ | 33 ea.* entries |
| MPC-1: normalization_factors columns in COLUMN_PROVENANCE | ✅ | 25 nf.* entries |
| MPC-2: All new methods seeded | ✅ | 5 new methods |
| MPC-3: YAML refs added | ✅ | energy_attribution.yaml, normalization_factors.yaml |
| MPC-4: Doc sections added | ✅ | research/12, 13, 14 |
| MPC-5: Provenance regression passes | ✅ | 34/34 |
| MPC-6: METHOD_CONFIDENCE in sync | ✅ | 5 new entries |
| SC-1: schema.py matches live DB | ✅ | All new tables + columns |
| SC-2: Migration + schema in sync | ✅ | v6, v7, v8, v9 migrations |
| SC-3: Migration naming | ✅ | v6_, v7_, v8_, v9_ |
| SC-4: ETL columns insert as NULL | ✅ | normalization_factors empty |
| SC-5: Backward compat | ✅ | No drops, no renames |
| SC-6: sqlite_adapter imports new tables | ✅ | 3 imports + 3 executescript |
| DC-1: 30% inline comments | ✅ | ETL well-commented |
| DC-2: Docstrings on every method | ✅ | All ETL functions |
| DC-3: No silent failures | ✅ | All except blocks log + return False |
| DC-4: Early return pattern | ✅ | _get_run returns None early |
| CQC-4: No debug prints | ✅ | logger.info/warning/error only |
| CQC-5: Max 50 lines/function | ✅ | _compute_attribution split into helpers |
| CQC-6: No hardcoded paths | ✅ | DEFAULT_DB constant, db_path param |

---

## Part 8: Known Gaps (Assigned to Future Chunks)

| Gap | Chunk | Description |
|-----|-------|-------------|
| L4 NULL columns | Chunk 4 | prefill/decode need TTFT data |
| L4 NULL columns | Chunk 8 | tool/retry/hallucination data |
| L5 NULL columns | Chunk 8 | per-goal efficiency needs outcomes |
| normalization_factors empty | Chunk 8 | behavioural factors need query_execution |
| synthesis_energy_uj = 0 | Chunk 14 | known pre-existing issue |
| event_energy_uj = NULL | Chunk 14 | orchestration_events need energy |
| v_outcome_efficiency mostly NULL | Chunk 8 | depends on normalization_factors |
| DiskReader not via factory | Chunk 14 | pre-existing compliance gap |

---

## Part 9: Useful Debug Queries

```sql
-- Check coverage for specific run
SELECT run_id, energy_sample_coverage_pct,
       task_duration_ns/1e6 AS task_ms,
       framework_overhead_ns/1e6 AS fw_ms,
       duration_includes_overhead
FROM runs WHERE run_id = :run_id;

-- Find runs with poor coverage
SELECT run_id, workflow_type, energy_sample_coverage_pct
FROM runs
WHERE energy_sample_coverage_pct < 80
  AND energy_sample_coverage_pct IS NOT NULL
ORDER BY energy_sample_coverage_pct ASC;

-- Check energy_attribution for a run
SELECT * FROM energy_attribution WHERE run_id = :run_id;

-- Check what's NULL in energy_attribution (L4 pending)
SELECT run_id,
       tool_energy_uj IS NULL AS tool_null,
       prefill_energy_uj IS NULL AS prefill_null,
       energy_per_accepted_answer_uj IS NULL AS answer_null
FROM energy_attribution ORDER BY run_id DESC LIMIT 5;

-- Verify attribution conservation (L1)
SELECT run_id,
       pkg_energy_uj,
       baseline_energy_uj,
       dynamic_energy_uj,
       pkg_energy_uj - baseline_energy_uj AS computed_dynamic,
       ABS(dynamic_energy_uj - (pkg_energy_uj - baseline_energy_uj)) AS delta
FROM runs
WHERE ABS(dynamic_energy_uj - (pkg_energy_uj - baseline_energy_uj)) > 1000
LIMIT 10;

-- View all methods in registry
SELECT id, name, provenance, layer
FROM measurement_method_registry
ORDER BY layer, provenance;
```
