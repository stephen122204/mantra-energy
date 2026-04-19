# Phase Energy Attribution — Developer Guide

**Chunk 5 | Method ID:** `phase_attribution_cpu_v1`
**Status:** Production
**Last updated:** 2026

---

## 1. Problem Statement

An agentic LLM run has three phases: planning, execution, synthesis.
The system measures total attributed energy for the whole run.
This guide explains how that total is split across phases with guaranteed accounting closure:

```
planning_energy_uj + execution_energy_uj + synthesis_energy_uj = attributed_energy_uj
```

---

## 2. Formula

### Step 1 — Raw phase energy (RAPL counter delta)

$$E_{raw,i} = \max(0,\ \max(pkg_{end}) - \min(pkg_{start}))$$

Source: `energy_samples` table, filtered to phase time window `[start_time_ns, end_time_ns]`.

### Step 2 — Phase CPU fraction (process tick delta)

$$f_i = \frac{\max(proc_{ticks,end}) - \min(proc_{ticks,start})}{\max(total_{ticks,end}) - \min(total_{ticks,start})}$$

Source: `interrupt_samples` table.
- Numerator: `/proc/[pid]/stat` utime+stime (workload process only)
- Denominator: `/proc/stat` sum(all fields) (system-wide)
- Method: MAX-MIN across phase window (not per-sample average)

### Step 3 — Phase signal score

$$S_i = f_i \times E_{raw,i}$$

Combines CPU activity and energy consumption into one signal per phase.

### Step 4 — Normalize to run total

$$w_i = \frac{S_i}{\sum_j S_j}, \qquad E_{phase,i} = w_i \times E_{attributed}$$

Where $E_{attributed}$ = `runs.attributed_energy_uj` (whole-run attribution).

### Accounting closure guarantee

$$\sum_i E_{phase,i} = E_{attributed}$$

Rounding residual (integer truncation) is added to the phase with the largest score.

---

## 3. Why Normalization (Not Direct Attribution)

### The problem with direct attribution

```
E_phase = cpu_fraction x raw_phase_energy
```

This fails because:
- `raw_phase_energy` uses absolute RAPL counter delta (not baseline-subtracted)
- `attributed_energy_uj` is baseline-subtracted (pkg minus idle)
- Different scales → phases don't sum to run total

### The normalization solution

Normalization uses phase scores as **relative weights** only.
The absolute value comes from the already-correct run total.
This gives physically sensible phase splits with exact accounting.

---

## 4. Data Flow

```
agentic.py
  _emit_event(phase="planning",  start, end)
  _emit_event(phase="execution", start, end)   ← added Chunk 5
  _emit_event(phase="synthesis", start, end)
        ↓
orchestration_events table
  (phase, start_time_ns, end_time_ns)
        ↓
experiment_runner.save_pair()
  → process_run_async(agentic_id)              ← non-blocking thread
        ↓
phase_attribution_etl.compute_phase_attribution(run_id)
  → energy_samples    → raw_energy per phase
  → interrupt_samples → cpu_fraction per phase
  → normalize scores  → allocated energy per phase
  → UPDATE orchestration_events (attributed_energy_uj per event)
  → UPDATE runs (planning/execution/synthesis_energy_uj)
```

---

## 5. Database Tables

### orchestration_events (per-event attribution)

| Column | Type | Description |
|---|---|---|
| `raw_energy_uj` | INTEGER | MAX(pkg_end) - MIN(pkg_start) in phase window |
| `cpu_fraction_per_phase` | REAL | proc_ticks_delta / total_ticks_delta |
| `attributed_energy_uj` | INTEGER | Normalized allocated energy for this event |
| `attribution_method` | TEXT | `cpu_counter_delta` or `fallback_run_level` |
| `quality_score` | REAL | 0.0–1.0 based on sample count in window |
| `proc_ticks_min/max` | INTEGER | Process tick bounds from interrupt_samples |
| `total_ticks_min/max` | INTEGER | System tick bounds from interrupt_samples |

### runs (pre-aggregated phase totals)

| Column | Type | Description |
|---|---|---|
| `planning_energy_uj` | INTEGER | Sum of planning event attributed energies |
| `execution_energy_uj` | INTEGER | Sum of execution event attributed energies |
| `synthesis_energy_uj` | INTEGER | Sum of synthesis event attributed energies |

---

## 6. Sampling Infrastructure

### Tick collection (scheduler_monitor.py)

Every 10th RAPL sample (~10Hz), `sample_interrupts()` reads:
- `/proc/stat` → `total_ticks` (system-wide, all fields summed)
- `/proc/[pid]/stat` → `proc_ticks` (workload PID, utime+stime)

Both stored in `interrupt_samples` as `*_start` (previous snapshot) and `*_end` (current).

### Why MAX-MIN not AVG

`/proc/stat` updates at USER_HZ = 100 ticks/second.
At 10ms sample interval, per-sample delta is often 0 (kernel quantisation).
MAX-MIN across the phase window gives the true cumulative delta.

### PID passing chain

```
harness.py: _pid = os.getpid()
  → energy_engine.set_workload_pid(_pid)
  → scheduler.start_interrupt_sampling(pid=_pid)
  → _read_proc_ticks(pid) called each sample
  → stored in interrupt_samples.proc_ticks_start/end
```

---

## 7. Fallback Handling

When phase-level proc ticks unavailable (old runs, missing data):
- `cpu_fraction_per_phase` = `runs.cpu_fraction` (whole-run value)
- `attribution_method` = `fallback_run_level`
- `quality_score` = 0.3

Normalization still applies → accounting closure maintained.

---

## 8. Running the ETL

### Automatic (per run)
Fires automatically after each agentic run via `experiment_runner.py`.
Non-blocking background thread — does not affect experiment timing.

### Manual single run
```bash
python scripts/etl/phase_attribution_etl.py --run-id 1849
```

### Backfill all agentic runs
```bash
python scripts/etl/phase_attribution_etl.py --backfill-all
```

---

## 9. Validation

```bash
python scripts/validate_phase_attribution.py
```

| Check | Description |
|---|---|
| 1 | `cpu_fraction_per_phase` in [0, 1] |
| 2 | `phase_sum <= dynamic_energy_uj` (physics) |
| 3 | `raw_phase_energy <= dynamic_energy_uj` |
| 4 | NULL rate < 5% |
| 5 | `attribution_method` populated |

---

## 10. Known Limitations

| Issue | Cause | Fix |
|---|---|---|
| `synthesis_energy = 0` for local runs | Local LLM responds in ~1ms, no samples in window | Time-proportional fallback (future) |
| Old runs have `phase_sum = 0` | No proc_ticks captured pre-Chunk 5 | Cannot backfill — document as NULL |
| Multi-process workloads | Only top-level PID tracked | Future: cgroup-based attribution |
| Sub-10ms phases | USER_HZ quantisation | Minimum 100ms for reliable measurement |

---

## 11. Methodology Query

```sql
SELECT formula_latex, description, parameters
FROM measurement_method_registry
WHERE id = 'phase_attribution_cpu_v1';
```

---

## 12. References

See `config/methodology_refs/phase_attribution.yaml`.
- Linux `proc(5)` — `/proc/[pid]/stat` field definitions
- Linux `proc_stat(5)` — `/proc/stat` aggregate CPU line
- A-LEMS paper Section 3.4 — Phase Energy Attribution
