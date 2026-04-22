# Run Quality Methodology

**Method ID:** `quality_scorer_v1`  
**Provenance:** `CALCULATED`  
**Layer:** `system`  
**Confidence:** `0.95`  
**Scorer version constant:** `QualityScorer.VERSION = 1`  
**Table:** `run_quality`

---

## Overview

Every experiment run is automatically scored for measurement quality immediately after it is inserted into the `runs` table. Scores are stored in the `run_quality` table (one row per run, keyed by `run_id`).

Quality assessment has two stages:

1. **Hard failure check** — any failure immediately marks the run invalid (`experiment_valid = 0`, `quality_score = 0.0`)
2. **Soft penalty scoring** — valid runs receive a score in `[0.0, 1.0]` based on thermal, CPU, interrupt, and sample conditions

All thresholds, weights, and null-handling rules are driven by `config/quality.yaml` — nothing is hardcoded in the scorer.

---

## Columns

### `experiment_valid`

| Property | Value |
|----------|-------|
| Type | `INTEGER` (0 or 1) |
| Provenance | `CALCULATED` |
| Method | `quality_scorer_v1` |

**Formula:**

$$
\text{experiment\_valid} =
\begin{cases}
0 & \text{if } |\text{hard\_failures}| > 0 \\
1 & \text{otherwise}
\end{cases}
$$

Hard failure conditions (any one → `experiment_valid = 0`):

| Condition | Key in `rejection_reason` |
|-----------|--------------------------|
| `runs.status = 'failed'` | `execution_failed` |
| `runs.baseline_id IS NULL` | `missing_baseline` |
| `runs.dynamic_energy_uj = 0` | `zero_energy` |
| `duration_ms < min_duration_ms` | `duration_too_short` |
| `duration_ms > max_duration_sec × 1000` | `duration_too_long` |

---

### `quality_score`

| Property | Value |
|----------|-------|
| Type | `REAL` in `[0.0, 1.0]` |
| Provenance | `CALCULATED` |
| Method | `quality_scorer_v1` |

Only computed when `experiment_valid = 1`. If `experiment_valid = 0`, score is forced to `0.0`.

**Formula:**

$$
\text{quality\_score} = \max\!\left(0.0,\; 1.0 - \sum_{i} w_i \cdot p_i\right)
$$

Where:

- $w_i$ = weight for dimension $i$, loaded from `config/quality.yaml`
- $p_i \in \{0.0,\; 0.5,\; 1.0\}$ = penalty multiplier (0 = clean, 0.5 = warning, 1.0 = critical)

**Penalty dimensions and weights (default profile):**

| Dimension | Weight $w_i$ | Warning threshold | Critical threshold |
|-----------|-------------|-------------------|--------------------|
| Thermal absolute (`max_temp_c`) | 0.20 | > 80 °C | > 85 °C |
| Thermal delta (`max_temp_c − start_temp_c`) | 0.15 | > 15 °C | > 25 °C |
| Background CPU (`background_cpu_percent`) | 0.20 | > 10 % | > 20 % |
| Interrupt rate (`interrupts_per_second`) | 0.15 | > 15,000 | > 50,000 |
| Energy sample count | 0.10 | — | < 20 samples |

Warning → $p_i = 0.5$. Critical → $p_i = 1.0$.

**Worked example — score = 0.90:**

Run has `energy_sample_count = NULL` → treated as 0 → triggers `low_energy_samples` (critical):

$$
\text{quality\_score} = 1.0 - (0.10 \times 1.0) = \mathbf{0.90}
$$

**Worked example — score = 0.525:**

Run has `temperature_too_high` + `thermal_delta_elevated` + `elevated_background_cpu` + `low_energy_samples`:

$$
\text{quality\_score} = 1.0 - 0.20 - (0.15 \times 0.5) - (0.20 \times 0.5) - 0.10 = \mathbf{0.525}
$$

**Null handling** (fields absent in telemetry):

| Field | Null handling | Reason |
|-------|--------------|--------|
| `max_temp_c` | `skip_penalty` — no penalty, logged in `missing_telemetry` | ARM VM may not expose temps |
| `start_temp_c` | `skip_delta` — delta not computed | Same |
| `background_cpu_percent` | `assume_zero` — no penalty | Expected on ARM VM |
| `interrupts_per_second` | `assume_zero` — no penalty | Expected on ARM VM |

---

### `rejection_reason`

| Property | Value |
|----------|-------|
| Type | `TEXT` (JSON) |
| Provenance | `CALCULATED` |
| Method | `quality_scorer_v1` |

Always populated regardless of valid/invalid. Full audit trail for every scoring decision.

**Schema:**

```json
{
  "version": 1,
  "hard_failures":      [],
  "soft_issues":        ["low_energy_samples"],
  "missing_telemetry":  [],
  "metrics": {
    "max_temp_c":             49.0,
    "start_temp_c":           48.0,
    "delta_c":                1.0,
    "background_cpu_percent": 4.9,
    "interrupts_per_second":  6201.84,
    "energy_sample_count":    null,
    "duration_ms":            1634.67
  }
}
```

---

## Hardware Profiles

Thresholds are profile-specific. Profiles defined in `config/quality.yaml`, single-level inheritance supported.

| Profile | `max_temp_critical` | `thermal_delta_critical` | Use case |
|---------|--------------------|--------------------------|-|
| `default` | 85 °C | 25 °C | UBUNTU2505 bare metal |
| `laptop_intel` | 90 °C | 30 °C | Higher thermal tolerance |
| `arm_oracle_vm` | 75 °C | 10 °C | Stricter (VM thermal noise) |

Profile selected via `hash_map` section in `quality.yaml`. Unknown hashes fall back to `default`.

---

## Diagnostic Queries

**Why did a run score what it scored?**

```sql
SELECT
    rq.run_id,
    rq.experiment_valid,
    rq.quality_score,
    json_extract(rq.rejection_reason, '$.hard_failures')               AS hard_failures,
    json_extract(rq.rejection_reason, '$.soft_issues')                 AS soft_issues,
    json_extract(rq.rejection_reason, '$.missing_telemetry')           AS missing_telemetry,
    json_extract(rq.rejection_reason, '$.metrics.max_temp_c')          AS temp_c,
    json_extract(rq.rejection_reason, '$.metrics.background_cpu_percent') AS bg_cpu,
    json_extract(rq.rejection_reason, '$.metrics.energy_sample_count') AS samples,
    json_extract(rq.rejection_reason, '$.metrics.duration_ms')         AS duration_ms
FROM run_quality rq
ORDER BY rq.run_id DESC LIMIT 5;
```

**Score distribution across all runs:**

```sql
SELECT
    CASE
        WHEN experiment_valid = 0        THEN 'invalid (hard fail)'
        WHEN quality_score >= 0.9        THEN 'excellent (>=0.9)'
        WHEN quality_score >= 0.7        THEN 'good (0.7-0.9)'
        WHEN quality_score >= 0.5        THEN 'marginal (0.5-0.7)'
        ELSE                                  'poor (<0.5)'
    END AS band,
    COUNT(*) AS runs
FROM run_quality
GROUP BY band
ORDER BY MIN(quality_score) DESC;
```

**Valid high-quality runs only (for analysis):**

```sql
SELECT r.run_id, r.workflow_type, rq.quality_score
FROM runs r
JOIN run_quality rq ON rq.run_id = r.run_id
WHERE rq.experiment_valid = 1
  AND rq.quality_score >= 0.8
ORDER BY rq.quality_score DESC;
```

**Runs failing due to specific hard failure:**

```sql
SELECT run_id FROM run_quality
WHERE json_extract(rejection_reason, '$.hard_failures') LIKE '%zero_energy%';
```

**Runs with temperature issues:**

```sql
SELECT run_id, quality_score FROM run_quality
WHERE json_extract(rejection_reason, '$.soft_issues') LIKE '%temperature%';
```

**Verify methodology seeded correctly:**

```sql
SELECT id, name, provenance, confidence
FROM measurement_method_registry
WHERE id = 'quality_scorer_v1';

SELECT * FROM method_references
WHERE method_id = 'quality_scorer_v1';
```

---

## Implementation Files

| File | Purpose |
|------|---------|
| `config/quality.yaml` | All thresholds, weights, null handling, hash→profile map |
| `core/utils/quality_scorer.py` | `QualityScorer.compute()` — pure Python, no I/O |
| `scripts/migrations/025_run_quality.sql` | Table + indexes |
| `scripts/etl/backfill_run_quality.py` | Score all existing runs |
| `core/execution/experiment_runner.py` | `_validate_run()` — inline after each run INSERT |
| `config/methodology_refs/quality_scorer.yaml` | MPC-3 reference entry |

---

## References

- Panigrahy, D. (2026). *A-LEMS Quality Scoring Methodology*. Internal. Section 5 — Run quality assessment.
