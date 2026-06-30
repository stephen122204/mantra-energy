---
**Method ID:** outlier_detection_v1
**Schema version:** 79 (outlier_detection_config, run_outliers, v_runs_clean, v_runs_unfiltered)
**Platforms verified:** TBD, pending Phase 2/3 detection run on NVIDIA Grace GB10 (aarch64) and Intel platform (x86_64)
**Status:** DRAFT
---

# Outlier Detection Methodology

## Overview

A-LEMS applies a three layer data selection model to every analytical
query, paper build, and dashboard view. This document describes Layer 3:
statistical and deterministic outlier detection, distinct from Layer 1
(experimenter intent, `experiments.is_valid`) and Layer 2 (hardware and
sampling quality, `run_quality.experiment_valid`).

A run can pass both Layer 1 and Layer 2 and still be a statistical
outlier. For example, a run with a normal quality score can still show a
framework overhead percentage two orders of magnitude above its
population, because the energy denominator used to compute that
percentage happened to be near zero on that particular run. Outlier
detection exists to catch this class of problem, which neither intent
flags nor hardware quality checks are designed to catch.

Three detection methods are applied:

1. **Domain rules** (deterministic, zero cold start): encode physical or
   measurement facts, such as "overhead energy cannot exceed total
   energy" or "a near-zero energy denominator makes derived ratios
   meaningless."
2. **Modified Z-score (MAD-based)** (primary statistical detector):
   robust to the extreme outliers it is trying to detect, unlike a
   classic standard-deviation-based Z-score.
3. **IQR fence** (cross-check only): never escalates a run to suspect or
   extreme severity by itself; only raises confidence when it agrees with
   the MAD result on the same run.

No run is ever silently excluded. Detected outliers are written with
`review_status='pending'` and remain in `v_runs_clean` (the filtered
analytical view) until a human explicitly confirms exclusion.

## Platform Coverage

| Platform | Architecture | Source | Canonical Role | Confidence | Status |
|----------|-------------|--------|---------------|------------|--------|
| NVIDIA Grace GB10 | aarch64 | `runs` + `experiments` (any energy/thermal/coverage column) | Detection target | 0.85 | PENDING |
| Intel platform | x86_64 | `runs` + `experiments` (any energy/thermal/coverage column) | Detection target | 0.85 | PENDING |

Outlier detection itself is platform agnostic: it operates on whatever
columns are populated in the `runs` table for a given platform, and
population grouping (`population_key`) is always computed within a single
platform's database, never across platforms. A `gsm8k_basic|linear`
population on the Grace GB10 platform is never compared to the same task
on the Intel platform, since their baselines differ.

Status is PENDING rather than VERIFIED because, as of this document's
DRAFT status, the detection script has not yet been run against either
live platform database. This document must be updated to VERIFIED status,
with concrete counts substituted for "TBD" values throughout, once Phase
2/3 of the implementation (detection run, human review) completes.

## Schema

| Table / View | Column | Type | Semantics |
|---|---|---|---|
| `outlier_detection_config` | `config_version` | INTEGER | Version of the threshold set this row belongs to |
| | `method` | TEXT | `mad_zscore`, `iqr_fence`, or `domain_rule` |
| | `metric_name` | TEXT | Metric this parameter applies to, or `*` for all |
| | `parameter_name` | TEXT | e.g. `z_threshold_suspect`, `iqr_multiplier` |
| | `parameter_value` | REAL | The numeric threshold |
| | `effective_to` | TIMESTAMP | NULL if currently active; old configs are retained, never deleted |
| `run_outliers` | `run_id` | INTEGER | FK to `runs.run_id` |
| | `metric_name` | TEXT | Which column was flagged |
| | `detection_method` | TEXT | Which of the three methods produced this row |
| | `population_key` | TEXT | `task_name\|workflow_type`, or `n/a` for domain rules |
| | `raw_value` | REAL | The actual value that was flagged |
| | `z_score` | REAL | NULL unless `detection_method='mad_zscore'` |
| | `severity` | TEXT | `informational`, `suspect`, or `extreme` |
| | `review_status` | TEXT | `pending`, `dismissed`, `confirmed`, or `recalibrated` |
| `v_runs_clean` | (all `runs` columns) | — | All three layers applied: `is_valid=1 AND COALESCE(experiment_valid,1)=1 AND run_id NOT IN (confirmed outliers)` |
| `v_runs_unfiltered` | (all `runs` columns plus layer verdicts) | — | No filtering; shows every layer's verdict side by side for debugging |

## Method Provenance

| Field | Value |
|---|---|
| `method_id` | `outlier_detection_v1` |
| `confidence` | 0.85 |
| `layer` | `orchestration` (post-hoc analysis of already-measured data, not a hardware reader) |
| `formula` (MAD) | `Z_mod = 0.6745 * (x_i - median(X)) / MAD(X)`, `MAD(X) = median(\|x_i - median(X)\|)` |
| `formula` (IQR) | `lower = Q1 - 2.5*IQR`, `upper = Q3 + 2.5*IQR` |
| **Confidence justification (Rule PDS-6)** | (a) Not 1.0 because both MAD and IQR are population-statistic methods: their correctness depends on `min_population_size` (10) being a large enough sample for the median and MAD to be stable, and on `population_key` grouping (task_name + workflow_type) being the right granularity, which has not yet been empirically validated against the four Paper 2 symptoms this feature was built to explain. (b) Would reach 1.0 once Phase 3 verification (Section 8 of the implementation spec) confirms the post-exclusion within-class CV and max overhead percentage land in the expected ranges, and once at least one full detection cycle has been through human review without a high rate of dismissed false positives. (c) Quantitative effect on paper results is currently TBD; the spec's illustrative pre/post CV figures (136.9% to ~18.4%) are marked TBD pending an actual detection run, not measured fact. |

## Query Reference

**Find all currently confirmed exclusions, with reason** — answers: which
runs have been permanently removed from analysis, and why?
Applies to: any platform database with schema version 79+.
Expected output: zero rows on a freshly migrated database with no
detection run yet; after Phase 2/3, one row per confirmed exclusion.

```sql
SELECT run_id, metric_name, detection_method, severity,
       reviewed_by, review_note
FROM run_outliers
WHERE review_status = 'confirmed'
ORDER BY run_id;
```

**Outlier summary by severity** — answers: how many runs are flagged at
each severity level, and how many are still awaiting human review?
Applies to: any platform database with schema version 79+.
Expected output: one row per (severity, review_status) combination.

```sql
SELECT severity, review_status, COUNT(DISTINCT run_id) AS run_count
FROM run_outliers
GROUP BY severity, review_status
ORDER BY severity DESC, review_status;
```

**Compare a population's distribution before and after Layer 3 filtering**
— answers: does excluding confirmed outliers materially change a task
family's reported energy statistics? Compute the mean and count in SQL;
compute standard deviation and CV in Python, since SQLite has no native
STDEV function.
Applies to: any platform database with schema version 79+.

```sql
-- Run twice: once against `runs`, once against `v_runs_clean`.
-- Compare the two result sets in Python (pandas) for stdev/CV, not SQL.
SELECT e.task_name, r.workflow_type, COUNT(*) AS n,
       AVG(r.total_energy_uj) AS mean_energy_uj
FROM runs r  -- or: FROM v_runs_clean r
JOIN experiments e ON r.exp_id = e.exp_id
GROUP BY e.task_name, r.workflow_type;
```

## Verification

Step-by-step commands to confirm correct operation, in order:

```bash
# 1. Confirm the migration applied (schema_version should show 79)
sqlite3 "$DB" "SELECT version, description FROM schema_version WHERE version=79;"

# 2. Confirm seed config loaded (should return 13 rows: 3 mad_zscore +
#    2 iqr_fence + 6 domain_rule + ... see 044_outlier_detection_seed.sql
#    for the exact count)
sqlite3 "$DB" "SELECT COUNT(*) FROM outlier_detection_config WHERE config_version=1;"

# 3. Dry run detection, no writes, inspect summary
python scripts/etl/compute_outliers.py --db "$DB" --dry-run

# 4. Live detection run
python scripts/etl/compute_outliers.py --db "$DB"

# 5. Confirm v_runs_clean is queryable and returns fewer or equal rows
#    than the raw runs table (it can never return more)
sqlite3 "$DB" "SELECT COUNT(*) FROM runs;"
sqlite3 "$DB" "SELECT COUNT(*) FROM v_runs_clean;"

# 6. Run the integrity checker against the most recent experiment
python scripts/test_exp_integrity.py --latest
```

Expected output for step 6: a `run_outliers:` line in the integrity
report, either `ok()` (zero flagged or all reviewed) or `warn()` (extreme
severity rows pending review), never `fail()` on a correctly applied
migration.

## Known Limitations

- **Cold start populations**: task families with fewer than
  `min_population_size` (10) runs receive domain rule checking only; MAD
  and IQR detection silently do not run for that population until enough
  runs accumulate. This is by design, not a bug, but means a brand new
  task family's first 9 runs get less scrutiny than an established one.
  Workaround: none beyond accumulating more runs; domain rules still
  catch the deterministic failure modes (DR-01 through DR-06) regardless
  of population size.
- **MAD degenerate case (MAD = 0)**: when a population's values are
  identical or nearly so, the modified Z-score is mathematically
  undefined. The detector falls back to a 10% range check in this case,
  which is a coarser, less principled rule than the Z-score itself.
  Workaround: none — accept the coarser fallback; this case is expected
  to be rare given the continuous nature of energy measurements.
- **Population grouping granularity is fixed at task_name|workflow_type**:
  the detector does not currently support finer grouping (for example, by
  difficulty_level or complexity_score within a task family), which means
  a task family with genuinely bimodal energy use across difficulty
  levels could show inflated MAD and falsely suppress detection of real
  anomalies within one mode. Workaround: none currently implemented;
  flagged as a candidate refinement for a future config_version.
- **No cross-platform comparison**: detection never compares GN100 runs
  to Intel platform runs, by design, since their baselines genuinely
  differ. This means a systematic platform-wide measurement bug (for
  example, every run on one platform reading 2x too high) would not be
  caught by this feature, since the entire population would shift
  together and nothing would look anomalous relative to its own platform.
  Workaround: cross-platform sanity checks belong in a separate
  validation step (see `validate_energy_chain_v2.py`), not in outlier
  detection.
- **Illustrative figures pending verification**: any specific numeric
  outcome referenced in design discussion for this feature (post-exclusion
  CV, post-exclusion max overhead percentage) is TBD until Phase 2/3 of
  the implementation runs detection against the live database and a human
  completes review. None of those figures should be cited in a paper
  until confirmed by an actual query against `run_outliers` and
  `v_runs_clean`, per Rule PDS-4.
