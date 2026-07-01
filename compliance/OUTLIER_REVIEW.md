# Outlier Detection and Review Process

**Document:** OUTLIER_REVIEW.md
**Location:** compliance/
**Status:** ACTIVE
**Applies to:** All A-LEMS machines running schema v79+

---

## 1. Design Principles

Three components, three responsibilities. They never overlap:

```
Experiment Runner     measures experiments
Outlier ETL           analyzes completed data
Views                 consume results
```

The experiment runner never analyzes data. The outlier ETL never
measures anything. The views never write anything.

Outlier detection is NOT wired into the experiment runner. It is a
researcher-triggered analysis step, not an automated pipeline stage.
The reason: the bottleneck is human review, not detection. Auto-running
detection without reviewing the results produces nothing useful.
Detection is fast. Review is the work.

---

## 2. When to Run Detection

Run detection **before any paper query** against `v_runs_clean_*` or
`v_runs_measured_*`. Not on a schedule, not after every run, not after
every batch. Before you use the data for something that matters.

```bash
# Resolve DB path correctly (never hardcode)
DB=$(python3 -c "
import sys
sys.path.insert(0, 'scripts/tools')
from path_loader import get_alems_db_path
print(get_alems_db_path())
")

# Run detection
python3 scripts/etl/compute_outliers.py --db "$DB"

# Check for extreme pending rows (must be zero before paper queries)
sqlite3 "$DB" "
SELECT COUNT(*) FROM run_outliers
WHERE review_status = 'pending' AND severity = 'extreme';
"
```

If the extreme count is zero, proceed. If not, review before querying.

Detection is idempotent: safe to run multiple times. Re-running never
overwrites confirmed or dismissed rows. It only adds new pending rows
for runs not yet seen, or updates pending rows if detection parameters
changed.

---

## 3. Population Grouping

Detection groups runs by:

```
(task_name, workflow_type, model_name, hardware hostname)
```

Example populations:
```
gsm8k_basic | agentic | TinyLlama 1B GGUF  | UBUNTU2505
gsm8k_basic | agentic | Llama 3.3 70B      | UBUNTU2505
gsm8k_basic | linear  | Llama 3.3 70B      | UBUNTU2505
```

Never compare across populations. A local model (TinyLlama, full
on-device inference) and a cloud model (Groq API, minimal local energy)
have fundamentally different energy profiles. Mixing them produces
meaningless z-scores. The four-part population key prevents this.

Cold start: MAD and IQR require min_population_size = 10 runs before
they activate. Domain rules (DR-01 through DR-06) always run regardless
of population size.

---

## 4. Review Cadence

### Rule OR-1: Review before paper queries

Before running any query against v_runs_clean_* or v_runs_measured_*
for paper results, verify zero extreme-severity pending rows exist:

```sql
SELECT COUNT(*) FROM run_outliers
WHERE review_status = 'pending' AND severity = 'extreme';
```

Zero = proceed. Non-zero = review first.

### Rule OR-2: Suspect rows

Suspect-severity pending rows (MAD z-score 3.5-5.0) should be reviewed
before paper submission. They do not block analysis immediately but
must not be ignored indefinitely.

### Rule OR-3: Informational rows

IQR-only informational rows may be bulk-dismissed at any time. They
never warrant individual investigation unless they co-occur with a MAD
flag on the same run.

### Rule OR-4: Review must be documented

Every confirm or dismiss action MUST populate:
- reviewed_by: researcher name or identifier
- reviewed_at: timestamp (set automatically via datetime('now'))
- review_note: reason for decision in plain language

A confirm or dismiss without review_note is a compliance violation.

---

## 5. Review Decision Guide

### Confirm as data_quality_failure

These runs are excluded from ALL views including v_runs_measured_*:

- rapl_after_task_uj is orders of magnitude larger than total_energy_uj
  Bug 8: RAPL boundary capture outside run boundary
- attributed_energy_uj = 0 exactly while total_energy_uj is normal
  Attribution ETL failure
- framework_overhead_energy_uj > total_energy_uj
  DR-02 conservation violation, physically impossible
- Energy sample coverage below 50%
  DR-04/DR-05 coverage floor

### Confirm as statistical_anomaly

These runs are excluded from v_runs_clean_* but KEPT in
v_runs_measured_* (real data, use for tail/worst-case analysis):

- Duration AND energy metrics flagged together coherently
  Genuinely long experiment, not a broken measurement
- High avg_power_watts without elevated total_energy_uj
  High instantaneous power draw, real event
- Single metric at extreme z-score where raw value is plausible
  and RAPL boundary is clean

### Dismiss

- IQR-only informational flag, no MAD agreement
- Single metric MAD suspect, no correlated evidence, RAPL boundary clean
- gpu_dynamic_energy_uj single-metric flag where gpu_baseline = 0
  Baseline not captured, not a measurement failure

### Recalibrate

Set review_status = 'recalibrated' when the population itself is
the problem, e.g. a naturally bimodal distribution producing false
positives across many runs. Recalibrated rows stay in all views (same
as dismissed) but signal that detection config needs revisiting for
this population.

---

## 6. Known Real Findings (as of 2026-06)

### Bug 8: RAPL boundary capture (UBUNTU2505)

132 runs confirmed data_quality_failure. rapl_after_task_uj in the
50-170 billion uJ range while total_energy_uj is in the millions to
low billions. The RAPL counter accumulated energy across multiple runs
before the post-task read, attributing all of it to
framework_overhead_energy_uj of a single run.

DR-02 catches the worst cases (overhead > total). MAD catches the
subtler cases (overhead statistically extreme but below total).
Both classes confirmed as data_quality_failure on human review.

Fix tracked separately in KNOWN_GAPS.md. Outlier detection surfaces
affected runs automatically; it does not fix the underlying RAPL
boundary issue.

### Attribution ETL failures (UBUNTU2505)

18 runs with attributed_energy_uj = 0 exactly while total_energy_uj
is normal (4-94 million uJ). Hardware measurement was correct;
attribution ETL produced zero. Confirmed data_quality_failure.

---

## 7. SQL Reference for Reviewers

```sql
-- See all pending extreme rows before paper queries
SELECT run_id, metric_name, detection_method, severity,
       raw_value, population_key
FROM run_outliers
WHERE review_status = 'pending' AND severity = 'extreme'
ORDER BY run_id;

-- Summary counts for a paper methodology section
SELECT outlier_class, COUNT(DISTINCT run_id)
FROM run_outliers
WHERE review_status = 'confirmed'
GROUP BY outlier_class;

-- Confirm data quality failure
UPDATE run_outliers
SET review_status = 'confirmed',
    outlier_class = 'data_quality_failure',
    reviewed_by = 'dpani',
    reviewed_at = datetime('now'),
    review_note = '<reason>'
WHERE run_id = <id> AND review_status = 'pending';

-- Confirm statistical anomaly
UPDATE run_outliers
SET review_status = 'confirmed',
    reviewed_by = 'dpani',
    reviewed_at = datetime('now'),
    review_note = '<reason>'
WHERE run_id = <id> AND review_status = 'pending';

-- Dismiss
UPDATE run_outliers
SET review_status = 'dismissed',
    reviewed_by = 'dpani',
    reviewed_at = datetime('now'),
    review_note = '<reason>'
WHERE run_id = <id> AND review_status = 'pending';

-- Bulk dismiss IQR informational (safe anytime)
UPDATE run_outliers
SET review_status = 'dismissed',
    reviewed_by = 'dpani',
    reviewed_at = datetime('now'),
    review_note = 'IQR informational only, no MAD agreement, insufficient for exclusion'
WHERE detection_method = 'iqr_fence'
  AND severity = 'informational'
  AND review_status = 'pending';
```

---

## 8. Compliance Rules

Rule OR-1: Run detection before any paper query against clean/measured views.
Rule OR-2: Suspect rows reviewed before paper submission.
Rule OR-3: IQR informational rows may be bulk-dismissed anytime.
Rule OR-4: Every review action must have review_note populated.
Rule OR-5: Detection never auto-confirms. Only humans confirm.
Rule OR-6: Detection is not wired into the experiment runner.
           It is a researcher-triggered step, run before data use.
Rule OR-7: outlier_class on confirmed rows must reflect the true
           failure mode as determined by human review. If a
           MAD-flagged row is confirmed as data_quality_failure
           on human review (e.g. Bug 8 variant not caught by DR-02),
           update outlier_class explicitly before confirming.
Rule OR-8: Always resolve DB path via get_alems_db_path().
           Never hardcode data/experiments.db or any absolute path
           in detection commands.
