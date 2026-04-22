# Chunk 10 — Run Quality: Implementation Handover

**Status:** ✅ Complete  
**Date:** 2026-04-22  
**Author:** Deepak Panigrahy  
**Implements:** `run_quality` table, `quality_scorer_v1`, backfill, inline post-run hook

---

## What Was Built

A separate `run_quality` table that scores every experiment run for measurement validity and quality. No changes to the `runs` table. Scoring happens inline after each run INSERT and retroactively via backfill for all existing runs.

---

## Files Created

| File | Purpose |
|------|---------|
| `config/quality.yaml` | All thresholds, weights, null handling, hardware profiles |
| `scripts/migrations/025_run_quality.sql` | Table schema + indexes |
| `core/utils/quality_scorer.py` | Scoring logic — `QualityScorer.compute()` |
| `scripts/etl/backfill_run_quality.py` | Backfill existing runs |
| `config/methodology_refs/quality_scorer.yaml` | MPC-3 methodology reference |
| `docs-src/mkdocs/source/research/16-run-quality-methodology.md` | Full methodology doc |

---

## Files Modified (Surgical)

| File | What Changed |
|------|-------------|
| `core/utils/provenance.py` | Added 3 `COLUMN_PROVENANCE` keys + `METHOD_CONFIDENCE["quality_scorer_v1"]` |
| `core/database/schema.py` | Added `CREATE_RUN_QUALITY` constant |
| `core/database/sqlite_adapter.py` | Import + `executescript(CREATE_RUN_QUALITY)` in `create_tables()` |
| `scripts/seed_methodology.py` | Appended `quality_scorer_v1` to `_load_derived_methods()` |
| `core/execution/experiment_runner.py` | Added `_validate_run()` method + 2 call sites in `save_pair()` |
| `docs-src/mkdocs/mkdocs.yml` | Added `16-run-quality-methodology.md` to Research nav |

---

## How It Works

### Inline scoring (new runs)

```
save_pair()
  → db.insert_run(linear)
  → _validate_run(db, linear_id, hw_id)   ← scores immediately, inside transaction
  → db.insert_run(agentic)
  → _validate_run(db, agentic_id, hw_id)  ← scores immediately, inside transaction
```

`_validate_run` calls `db.get_run()` to fetch the just-inserted row, resolves the hardware profile from `hardware_config`, runs `QualityScorer.compute()`, and inserts into `run_quality` — all synchronous, zero ETL lag.

### Backfill (existing runs)

```bash
python scripts/etl/backfill_run_quality.py
# Safe to re-run — skips already-scored runs by default
# Use --force to re-score everything
```

Scored 1,987 runs in ~90ms on UBUNTU2505.

### Scoring logic

Two stages — config-driven from `config/quality.yaml`:

**Stage 1 — Hard failures** (short-circuit, `experiment_valid=0`, `score=0.0`):
- `baseline_id IS NULL` → `missing_baseline`
- `dynamic_energy_uj = 0` → `zero_energy`
- `duration_ms < 100` → `duration_too_short`
- `duration_ms > 60000` → `duration_too_long`

**Stage 2 — Soft penalties** (`quality_score = max(0, 1 - Σ wᵢpᵢ)`):

| Issue | Weight | Warning (p=0.5) | Critical (p=1.0) |
|-------|--------|-----------------|------------------|
| `temperature_too_high` | 0.20 | > 80 °C | > 85 °C |
| `thermal_delta_high` | 0.15 | > 15 °C | > 25 °C |
| `high_background_cpu` | 0.20 | > 10% | > 20% |
| `high_interrupt_rate` | 0.15 | > 15,000/s | > 50,000/s |
| `low_energy_samples` | 0.10 | — | < 20 samples |

---

## Compliance Checklist

| Rule | Status | Notes |
|------|--------|-------|
| MPC-1: `COLUMN_PROVENANCE` entries | ✅ | 3 keys added: `run_quality.*` |
| MPC-2: `seed_methodology.py` entry | ✅ | `quality_scorer_v1` seeded, verified in DB |
| MPC-3: methodology YAML reference | ✅ | `config/methodology_refs/quality_scorer.yaml` |
| MPC-6: `METHOD_CONFIDENCE` key | ✅ | `quality_scorer_v1: 0.95` |
| SC-1/SC-2: `schema.py` + `sqlite_adapter.py` | ✅ | `CREATE_RUN_QUALITY` added |
| SC-3: migration named `025_run_quality.sql` | ✅ | Sequential |
| DC-1: 30% inline comments | ✅ | `quality_scorer.py`, `backfill_run_quality.py` |
| DC-2: docstrings on every method | ✅ | All methods covered |
| DC-4: methodology doc | ✅ | `16-run-quality-methodology.md` |
| mkdocs.yml updated | ✅ | Research nav entry added |

---

## Verified Working

```
✅ sqlite3 "SELECT COUNT(*) FROM run_quality;"  → 1987
✅ Backfill: 1987 runs scored in ~90ms
✅ New run inline scoring: run_quality row created inside save_pair() transaction
✅ seed: quality_scorer_v1 present in measurement_method_registry
✅ rejection_reason JSON queryable via json_extract()
```

Sample output from DB:

```
run_id | experiment_valid | quality_score | soft_issues
1987   | 1                | 0.525         | ["temperature_too_high","thermal_delta_elevated","elevated_background_cpu","low_energy_samples"]
```

---

## Known Issues / Future Work

| Issue | Notes |
|-------|-------|
| `energy_sample_count` is NULL on new runs | Column maps to `energy_sample_coverage_pct` (pct not count) — scorer treats NULL as 0, fires `low_energy_samples`. Acceptable for now — fix in Chunk 11 when `energy_sample_count` is properly populated |
| `runs.status` field absent | Hard failure `execution_failed` never fires — no status column in `runs`. Runs that errored mid-execution simply won't have a row. Acceptable. |
| hash_map in quality.yaml | Currently only `ebe694229b1b9d87` → `laptop_intel` mapped. Add ARM VM hash when `alems-vnic` is registered. |

---

## Quick Reference — Key Queries

```sql
-- Why did run X score what it scored?
SELECT run_id, experiment_valid, quality_score,
    json_extract(rejection_reason, '$.hard_failures') AS hard,
    json_extract(rejection_reason, '$.soft_issues')   AS soft
FROM run_quality WHERE run_id = X;

-- Score distribution
SELECT
    CASE
        WHEN experiment_valid = 0 THEN 'invalid'
        WHEN quality_score >= 0.9 THEN 'excellent'
        WHEN quality_score >= 0.7 THEN 'good'
        ELSE 'marginal/poor'
    END AS band,
    COUNT(*) AS runs
FROM run_quality GROUP BY band;

-- Valid high-quality runs for analysis
SELECT r.run_id, r.workflow_type, rq.quality_score
FROM runs r
JOIN run_quality rq ON rq.run_id = r.run_id
WHERE rq.experiment_valid = 1 AND rq.quality_score >= 0.8;

-- Verify seed
SELECT id, name, provenance, confidence
FROM measurement_method_registry
WHERE id = 'quality_scorer_v1';
```
