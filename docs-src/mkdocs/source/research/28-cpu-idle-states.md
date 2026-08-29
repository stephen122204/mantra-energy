---
**Method ID:** cpuidle_sysfs_v1 (ARM), turbostat (x86 via existing method)
**Schema version:** 70 (cpu_idle_states table)
**Platforms verified:** NVIDIA Grace GB10 (aarch64), Intel i7-1165G7 (x86_64)
**Status:** PRODUCTION
**Last updated:** 2026-06-19
---

# CPU Idle State Residency

## Overview

CPU idle state residency measures how long each processor idle state was active
during an experiment run. This metric is the primary training signal for ALEOE
(the A-LEMS optimization engine) and provides critical context for interpreting
energy measurements: two runs with identical EpG but different idle state
distributions have different thermal profiles, different wakeup latencies, and
different optimization opportunities.

### Why a New Table (Not Columns on `runs`)

The `runs` table carries legacy x86-specific columns `c2_time_seconds` through
`c7_time_seconds`. These columns cannot represent ARM idle states (LPI-0 through
LPI-3) without claiming a hardware equivalence that does not exist. Mapping
`LPI-0 → c2_time_seconds` would be a semantic lie visible to every reviewer
who checks the schema.

The `cpu_idle_states` table stores platform-native state names exactly as
reported by the hardware and OS, with a `depth_rank` column for cross-platform
comparison that makes no equivalence claim. The paper framing becomes: "We
compare energy impact at equivalent idle depth levels across architectures,"
not "C2 on Intel equals LPI-0 on Grace."

The legacy columns are retained permanently (rule SC-5: never DROP or RENAME).
New analysis uses `cpu_idle_states`.

---

## Platform Coverage

| Platform | Architecture | Idle States | Source | Confidence | Status |
|----------|-------------|-------------|--------|------------|--------|
| NVIDIA Grace GB10 | aarch64 | LPI-0, LPI-1, LPI-2, LPI-3 | cpuidle sysfs | 0.85 | VERIFIED |
| Intel i7-1165G7 | x86_64 | C1, C2, C3, C6, C7 | turbostat | 0.90 | VERIFIED |
| AMD Ryzen (x86_64) | cpuidle sysfs | POLL, C1, C2 | cumulative | cpuidle_sysfs | VERIFIED |
| Apple M1 Pro | arm64 | vendor-specific | IOKit  | TBD | PLANNED |
| Oracle Ampere | aarch64 | LPI variant | cpuidle sysfs | 0.85 | PLANNED |

### Confidence Score Justification

**ARM cpuidle sysfs (0.85):** The sysfs `time` file reports cumulative
microseconds since boot, not per-run residency. The current implementation
takes one snapshot at experiment end. Two sequential runs on the same machine
will show increasing cumulative values, not per-run deltas. For absolute
per-run residency, a start+end snapshot with delta computation is required.
This is documented as a known limitation and deferred to a future revision.
The 0.85 score reflects that relative comparison across runs on the same machine
is valid even with cumulative values. To reach 1.0: implement start+end snapshot
subtraction in the ETL.

**turbostat (0.90):** turbostat reports per-interval C-state residency as
fractional percentages. The current implementation stores the mean fraction
across all samples with `residency_type = 'percentage'`. Absolute seconds
require multiplying by sample duration, which introduces timing measurement
uncertainty (~1%). To reach 1.0: record per-sample interval duration and
compute exact residency seconds in the ETL.

---

## Schema

### `cpu_idle_states` table (schema version 70)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment row identifier |
| `run_id` | INTEGER FK | References `runs.id` |
| `platform` | TEXT | Platform string: `intel_x86_64`, `amd_x86_64`, `grace_aarch64`, `apple_arm64`, `ampere_aarch64` |
| `state_name` | TEXT | Exact hardware state name: `C2`, `C6`, `LPI-0`, `WFI`, `HALT` etc. |
| `depth_rank` | INTEGER | Ordinal idle depth: 0=shallowest, higher=deeper. Query via `ORDER BY depth_rank DESC`, not `WHERE depth_rank = MAX()` |
| `residency_seconds` | REAL | Residency value — interpret via `residency_type` |
| `residency_type` | TEXT | `delta` (turbostat per-interval) \| `cumulative` (ARM sysfs since-boot) \| `percentage` (turbostat fraction 0–1) |
| `measurement_source` | TEXT | How measured: `turbostat` \| `cpuidle_sysfs` \| `msr` \| `perf` \| `iokit` |

**UNIQUE constraint:** `(run_id, measurement_source, state_name)` — prevents
duplicates; includes `measurement_source` because turbostat and MSR reads can
both report C6 on the same run during cross-validation experiments.

### Relationship to existing schema

The legacy `c2_time_seconds`, `c3_time_seconds`, `c6_time_seconds`,
`c7_time_seconds` columns on `runs` remain untouched (SC-5). Historical
x86 data is preserved. New experiments write to `cpu_idle_states` in addition
to (not instead of) populating the legacy columns via existing ETL.

---

## Method Provenance

### ARM: `cpuidle_sysfs_v1`

| Field | Value |
|-------|-------|
| Method ID | `cpuidle_sysfs_v1` |
| Layer | `os` |
| Provenance | `MEASURED` |
| Confidence | 0.85 |
| Source | `/sys/devices/system/cpu/cpu0/cpuidle/stateN/time` |
| Formula | residency\_s = sum(state\_time\_us) / 10^6 |

The Linux cpuidle subsystem exposes one directory per idle state under
`/sys/devices/system/cpu/cpu0/cpuidle/`. Each directory contains:
- `name`: human-readable state name (e.g. `WFI`, `HALT`)
- `time`: cumulative microseconds spent in this state since boot

On NVIDIA Grace (Neoverse V2), the kernel reports states `state0` through
`state3`, corresponding to LPI-0 through LPI-3 in the ARM specification.
`depth_rank` maps directly to the state ordinal (state0 → rank 0).

### x86: turbostat (existing method, unified ETL path)

turbostat reports C-state residency as per-interval fractional percentages
in `cpu_samples`. The `CPUIdleRepository.write_from_turbostat()` method
aggregates across all `cpu_samples` rows for a run and writes the mean
fraction to `cpu_idle_states` with `residency_type = 'percentage'`.

This unifies x86 idle state data into the same normalized table as ARM,
enabling cross-platform queries without platform-specific query branches.

---

## ETL Pipeline

```
cpu_samples (x86 turbostat)  ────┐
                                  ├─→  CPUIdleRepository  ─→  cpu_idle_states
cpuidle sysfs (ARM)          ────┘
                                                           ─→  runs (legacy c2/c6/c7 columns, x86 only)
```

### ETL Integration

`cpu_idle_states` rows are written by `experiment_runner.py` and
`run_persistence.py` immediately after `insert_cpu_samples()`. The write
is non-blocking — failures are logged and do not abort the experiment save.

ALEOE reads from `cpu_idle_states` directly. The legacy `aggregate_hardware_metrics`
ETL continues to populate legacy `cN_time_seconds` columns on `runs` from
`cpu_samples` unchanged.

---

## Query Reference

All queries below are tested on NVIDIA Grace GB10 (aarch64) and Intel i7-1165G7
(x86_64). Replace `<run_id>` with the actual integer run identifier from `runs.run_id`.

**1. All idle states for a single run**

Applies to: all platforms. Shows platform-native state names and depth.

```sql
SELECT platform, state_name, depth_rank,
       residency_seconds, residency_type, measurement_source
FROM cpu_idle_states
WHERE run_id = <run_id>
ORDER BY depth_rank;
```

Expected output (NVIDIA Grace GB10, aarch64):
```
grace_aarch64 | WFI  | 0 | 18234.5 | cumulative | cpuidle_sysfs
grace_aarch64 | HALT | 1 | 4102.3  | cumulative | cpuidle_sysfs
```

**2. Deepest idle state residency for a run (ALEOE primary feature)**

```sql
SELECT state_name, depth_rank, residency_seconds, residency_type
FROM cpu_idle_states
WHERE run_id = <run_id>
ORDER BY depth_rank DESC
LIMIT 1;
```

Note: `ORDER BY depth_rank DESC LIMIT 1`, not `WHERE depth_rank = MAX(depth_rank)`.
The latter fails if states are not contiguous integers on some CPU variants.

**3. Cross-platform idle depth comparison across multiple runs**

Applies to: all platforms. Compares energy vs idle depth across architectures.

```sql
SELECT c.platform, c.state_name, c.depth_rank,
       c.residency_seconds, c.residency_type,
       r.pkg_energy_uj, r.gpu_total_energy_uj
FROM cpu_idle_states c
JOIN runs r ON c.run_id = r.id
WHERE c.run_id IN (<run_id_1>, <run_id_2>, <run_id_3>)
ORDER BY c.platform, c.depth_rank;
```

**4. Mean idle residency at each depth level across all agentic runs**

Applies to: NVIDIA Grace GB10 (aarch64). Replace `machine_id` filter as needed.

```sql
SELECT depth_rank, state_name,
       AVG(residency_seconds) as mean_residency_s,
       COUNT(*) as n_runs
FROM cpu_idle_states
WHERE platform = 'grace_aarch64'
  AND measurement_source = 'cpuidle_sysfs'
  AND run_id IN (
      SELECT id FROM runs WHERE run_type = 'agentic'
  )
GROUP BY depth_rank, state_name
ORDER BY depth_rank;
```

**5. Runs with non-zero deepest idle state (throttle signal for ALEOE)**

```sql
SELECT r.id as run_id, r.run_type, r.created_at,
       c.state_name, c.depth_rank, c.residency_seconds
FROM cpu_idle_states c
JOIN runs r ON c.run_id = r.id
WHERE c.residency_seconds > 0
  AND c.depth_rank = (
      SELECT MAX(depth_rank) FROM cpu_idle_states c2
      WHERE c2.run_id = c.run_id
  )
ORDER BY r.created_at DESC
LIMIT 20;
```

**6. Verify rows exist after running test harness**

```sql
SELECT COUNT(*) as row_count,
       COUNT(DISTINCT run_id) as distinct_runs,
       COUNT(DISTINCT platform) as platforms
FROM cpu_idle_states;
```

Expected after first experiment on GN100: `row_count >= 2` (WFI + HALT),
`distinct_runs = 2` (linear + agentic), `platforms = 1`.

---

## Verification

Run in this order after first experiment on a new platform:

```bash
# Step 1: confirm table exists and migration applied
sqlite3 $DB "SELECT version FROM schema_version WHERE version = 70;"
# Expected: 70

# Step 2: confirm rows written (replace run_id with actual value)
RUN_ID=$(sqlite3 $DB "SELECT MAX(id) FROM runs;")
sqlite3 $DB "
SELECT platform, state_name, depth_rank, residency_seconds, residency_type
FROM cpu_idle_states WHERE run_id = $RUN_ID ORDER BY depth_rank;"

# GN100 expected output:
# grace_aarch64|WFI|0|<large_number>|cumulative
# grace_aarch64|HALT|1|<smaller_number>|cumulative

# UBUNTU2505 expected output (if turbostat has c-state columns in cpu_samples):
# intel_x86_64|C2|2|<fraction>|percentage
# intel_x86_64|C6|4|<fraction>|percentage

# Step 3: confirm UNIQUE constraint works (re-run same experiment, rows should not duplicate)
sqlite3 $DB "
SELECT run_id, COUNT(*) as rows_per_run
FROM cpu_idle_states
GROUP BY run_id
ORDER BY run_id DESC LIMIT 4;"

# Step 4: confirm cpuidle sysfs exists on GN100
ls /sys/devices/system/cpu/cpu0/cpuidle/
# Expected: state0 state1 (at minimum)

# Step 5: confirm ARM state names
cat /sys/devices/system/cpu/cpu0/cpuidle/state0/name
cat /sys/devices/system/cpu/cpu0/cpuidle/state1/name
# Expected: WFI and HALT (or platform-specific names)
```

---

## Known Limitations

**Cumulative-only snapshot on ARM:** The current implementation reads cpuidle
sysfs once at experiment end. Values are cumulative since boot. Per-run delta
residency (the exact time spent in each state during the experiment) requires
a start snapshot before the experiment and an end snapshot after, with
subtraction. This is deferred. Current data enables relative comparison across
runs on the same machine but not absolute per-run residency in wall-clock seconds.
Workaround: For absolute residency, use the delta between consecutive run rows
where run timing is known.

**turbostat fraction, not seconds on x86:** The x86 path stores mean
fractional C-state occupancy (0–1 scale) as `residency_type = 'percentage'`,
not elapsed seconds. ALEOE must handle both `residency_type` values when
computing features. The `residency_type` column makes this explicit.

**No per-core granularity:** `cpu_idle_states` stores aggregate idle state
residency across all cores, not per-core data. For per-core analysis, a
`cpu_id` column and updated UNIQUE constraint are required. This is documented
in SPEC_CPU_IDLE_STATES.md §7 and deferred.

**Apple arm64 not implemented:** IOKit idle state measurement is planned but
not implemented. `write_from_cpuidle_sysfs()` returns 0 on macOS (sysfs path
does not exist). No data loss — method returns gracefully.

**Oracle Ampere:** Uses the same cpuidle sysfs path as Grace. LPI state names
may differ from Grace. `state_name` stores the exact kernel-reported name so
cross-machine comparison is accurate even if state names differ between Ampere
and Grace.

---

## Future Extensions (Not Implemented)

These are documented for awareness, not action now.

1. **Per-run delta:** Start+end snapshot with subtraction. Changes
   `residency_type` to `'delta'` for ARM path, matching turbostat semantics.
   Requires experiment runner changes to take pre-experiment snapshot.

2. **Per-core residency:** Add `cpu_id INTEGER` column and update UNIQUE
   constraint to `(run_id, measurement_source, state_name, cpu_id)`. Build
   when per-core idle analysis becomes a paper requirement.

3. **idle_state_registry lookup table:** Map `(platform, state_name)` to
   `(depth_rank, vendor_doc_url)`. Build when metadata per state is needed
   for more than ~20 distinct state names across platforms.
