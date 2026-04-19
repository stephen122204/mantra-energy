# A-LEMS Development Guidelines

**Version**: 1.0 (established Chunk 9)
**Mandatory for**: All chunks, all developers, all contributors

Every code change to A-LEMS must follow these guidelines.
No exceptions. The platform is a world-class research tool —
every measurement must be auditable, every formula verifiable.

---

## The Golden Rule

> **If you add a metric, you must document how it is measured.**

This means: every new runs table column must have a corresponding
entry in `COLUMN_PROVENANCE`, a method in `measurement_method_registry`,
and a description in the appropriate methodology doc.

---

## Checklist — New runs Table Column

When adding a column to the `runs` table:

```
[ ] Add to schema.py CREATE TABLE statement
[ ] Add migration in scripts/migrations/
[ ] Add to COLUMN_PROVENANCE in core/utils/provenance.py
[ ] Add to METHOD_CONFIDENCE if new method_id introduced
[ ] Add to PARAMETERS_MAP if inputs are calculable
[ ] Run: bash scripts/test_provenance.sh (must pass 22/22)
```

---

## Checklist — New Hardware Reader

When adding a reader class (e.g. new platform, new sensor):

```
[ ] Inherit EnergyReaderABC or CPUReaderABC
[ ] Add 7 class attributes:
    METHOD_ID          = "unique_snake_case"
    METHOD_NAME        = "Human Readable"
    METHOD_LAYER       = "silicon|os|application|orchestration"
    METHOD_CONFIDENCE  = 0.0 to 1.0
    METHOD_PARAMS      = {"key": "value"}
    FALLBACK_METHOD_ID = "fallback_id" or None
    METHOD_PROVENANCE  = "MEASURED|INFERRED|LIMITED"
[ ] Add @formula decorator on read_energy_uj() or compute function
[ ] Add to _load_readers() in scripts/seed_methodology.py
[ ] Add entry to config/methodology_docs.yaml
[ ] Write description section in appropriate doc:
    07-energy-readers-methodology.md  ← energy readers
    08-system-measurement-methodology.md ← system readers
[ ] Add references to config/methodology_refs/{METHOD_ID}.yaml
[ ] Add to ReaderFactory dispatch table
[ ] Run: python scripts/seed_methodology.py --dry-run
[ ] Run: python scripts/seed_methodology.py
[ ] Run: bash scripts/test_provenance.sh
```

---

## Checklist — New Derived Metric

When adding a computed metric to energy_analyzer.py,
sustainability/calculator.py, or any other analyzer:

```
[ ] Add to COLUMN_PROVENANCE in core/utils/provenance.py
[ ] Add to PARAMETERS_MAP if inputs are from result dict
[ ] Add to DERIVED_METHODS in scripts/seed_methodology.py:
    {
        "id":           "method_id",
        "name":         "Human Readable Name",
        "provenance":   "CALCULATED|INFERRED",
        "layer":        "silicon|os|application|orchestration",
        "formula_latex": r"your formula here",
        "fn":           specific_function,  # NOT a 200-line compute()
        "doc":          "09-derived-metrics-methodology.md",
        "section":      "Your Section Heading",
    }
[ ] Write description section in 09-derived-metrics-methodology.md
[ ] Run: python scripts/seed_methodology.py
[ ] Run: python scripts/migrate_yaml_to_db.py
[ ] Run: bash scripts/test_provenance.sh
```

---

## Checklist — After Any Code Change

```bash
# Always run in this order after any change:

# 1. If readers or methods changed:
python scripts/seed_methodology.py

# 2. If display config needed:
python scripts/migrate_yaml_to_db.py

# 3. Always:
bash scripts/test_provenance.sh        # MUST pass 22/22
bash scripts/test_runs_regression.sh   # MUST pass all

# 4. Full integration test:
python -m core.execution.tests.test_harness \
    --task-id gsm8k_basic --repetitions 1 \
    --provider local --verbose
```

---

## Provenance Types — Reference

```
MEASURED   — Direct hardware or OS read. No mathematics.
             Examples: pkg_energy_uj (RAPL), package_temp_celsius (sysfs),
                       api_latency_ms (wall clock), bytes_sent (psutil)

CALCULATED — Deterministic formula applied to MEASURED values.
             Formula fully specifies the computation.
             Examples: dynamic_energy_uj (pkg - idle),
                       ipc (instructions / cycles),
                       cache_miss_rate (misses / references × 100)

INFERRED   — Uses external constants, emission factors, or ML models.
             Result depends on inputs NOT measured by A-LEMS hardware.
             Examples: carbon_g (energy × grid_intensity),
                       water_ml (energy × WUE),
                       ml_energy_estimator (stub, pending Chunk 7)

SYSTEM     — Infrastructure metadata. No scientific meaning.
             NOT recorded in measurement_methodology.
             Examples: run_id, exp_id, sync_status, global_run_id
```

---

## Formula Guidelines

```
Simple ratio formula (IPC, cache_miss_rate):
    → formula_latex only, fn=None
    → Formula IS the complete specification

Complex multi-step function (dynamic_energy, orchestration_tax):
    → formula_latex + fn pointing to SPECIFIC function
    → NOT fn=EnergyAnalyzer.compute (too large, misleading)
    → Extract specific sub-function if needed

External constant formula (carbon, water):
    → formula_latex + fn=SustainabilityCalculator.calculate_from_raw
    → Document the constant source in description
    → confidence < 1.0 (0.7 for emission factors)

Auto-extraction via latexify:
    → Try automatically — use as fallback only
    → Manual formula_latex always wins over latexify
    → Only works for single-expression return functions
```

---

## Documentation Structure

```
docs-src/mkdocs/source/research/
    07-energy-readers-methodology.md
        → All hardware energy readers
        → RAPL, IOKit, Estimator, Dummy
        → Section per reader

    08-system-measurement-methodology.md
        → All system-level measurements
        → perf counters, thermal, MSR, turbostat,
          scheduler, memory, network, clock
        → Section per method

    09-derived-metrics-methodology.md
        → All computed metrics
        → dynamic energy, IPC, cache miss,
          efficiency, orchestration, carbon, water
        → Section per metric group

    10-provenance-research-value.md
        → 22 research queries documented
        → PhD thesis usage guide
        → Regression test documentation

Rule: Add new section to appropriate doc BEFORE seeding.
      Section heading must match methodology_docs.yaml exactly.
```

---

## Key Files Reference

```
core/utils/provenance.py
    COLUMN_PROVENANCE        ← add new column here
    METHOD_CONFIDENCE        ← add new method confidence here
    PARAMETERS_MAP           ← add input keys for new metric
    record_run_provenance()  ← called once per run

scripts/seed_methodology.py
    _load_readers()          ← add new reader here
    _load_derived_methods()  ← add new derived method here
    _load_measured_methods() ← add new measured method here

config/methodology_docs.yaml
    methods:                 ← add new method_id → doc + section

config/methodology_refs/
    {method_id}.yaml         ← add paper citations here

scripts/test_provenance.sh   ← regression test, run after changes
scripts/test_runs_regression.sh ← statistical regression
```

---

## Database Integrity Queries

Run these to verify system health:

```sql
-- All methods have formulas
SELECT id FROM measurement_method_registry
WHERE formula_latex IS NULL OR formula_latex = '';
-- Expected: 0 rows

-- All methods have descriptions
SELECT id FROM measurement_method_registry
WHERE LENGTH(description) < 50;
-- Expected: 0 rows

-- All methodology rows have method_id
SELECT COUNT(*) FROM measurement_methodology
WHERE method_id IS NULL;
-- Expected: 0

-- INFERRED metrics never have confidence=1.0
SELECT metric_id, confidence FROM measurement_methodology
WHERE provenance = 'INFERRED' AND confidence >= 1.0;
-- Expected: 0 rows

-- Display registry linked to methods
SELECT COUNT(*) FROM metric_display_registry
WHERE method_id IS NOT NULL;
-- Expected: 83+
```

---

## Anti-Patterns — Never Do These

```
❌ Hardcode formula strings in seed script
   → Use @formula decorator or DERIVED_METHODS dict

❌ Point fn to large general compute() function
   → Point to specific sub-function or use fn=None

❌ Add runs column without COLUMN_PROVENANCE entry
   → Every column must have provenance

❌ Duplicate formula_latex in metric_display_registry
   → It lives in measurement_method_registry only
   → Display registry reads it via JOIN

❌ Write methodology description inline in seed script
   → Description lives in .md doc files
   → Seed extracts from doc via section keyword

❌ Skip regression tests after a change
   → Always run test_provenance.sh and test_runs_regression.sh

❌ Use YAML for method metadata
   → Method metadata lives in reader class attributes
   → Only references live in YAML (methodology_refs/)
```
