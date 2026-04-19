# A-LEMS Developer Compliance Guide

**MANDATORY READING — Every developer and agent must read this before touching any code.**
**Location:** `compliance/COMPLIANCE.md`
**Last updated:** 2026

---

## 1. Platform Abstraction Compliance (PAC)
*Previously called "Chunk 1 rules"*

### Rule PAC-1: ABC First
Every new reader MUST inherit from an ABC defined in `core/readers/interfaces.py`.

```
New reader checklist:
✅ Inherits EnergyReaderABC / CPUReaderABC / DiskReaderABC / ThermalReaderABC
✅ Implements all abstract methods: is_available(), get_name(), read_*()
✅ is_available() returns False gracefully on unsupported platforms
✅ Never raises — always returns None/0 on failure
```

### Rule PAC-2: Factory Only
Platform-conditional imports ONLY in `core/readers/factory.py`. Never in:
- `core/energy_engine.py`
- `core/execution/harness.py`
- Any other file

```python
# WRONG — direct import in energy_engine.py
from core.readers.disk_reader import DiskReader

# RIGHT — get from factory
self.disk_reader = ReaderFactory.get_disk_reader(config)
```

### Rule PAC-3: Three Measurement Modes Only
```
MEASURED  = direct hardware/OS read, no math
INFERRED  = uses external constants or ML models
LIMITED   = hardware unavailable, returns zeros
```
No other modes. No DERIVED mode.

### Rule PAC-4: Graceful Degradation Chain
Every reader must have implementations for:
```
Linux x86  → real implementation
Linux ARM  → real or INFERRED fallback
macOS      → IOKit stub (returns None until implemented)
Unknown    → FallbackReader (returns None, never raises)
```

### Rule PAC-5: Platform Matrix
Before shipping any reader, document in `14-hardware-readers-developer-guide.md`:
```
| Reader | Linux x86 | Linux ARM | macOS | Notes |
```

---

## 2. Methodology & Provenance Compliance (MPC)
*Previously called "Chunk 9 rules"*

### Rule MPC-1: Every New runs Column Gets Provenance
ANY new column added to `runs` table MUST be added to `COLUMN_PROVENANCE` in `core/utils/provenance.py`:

```python
"new_column": ("method_id", "MEASURED|CALCULATED|INFERRED|SYSTEM"),
```

### Rule MPC-2: Every New Method Gets Seeded
ANY new reader or compute function MUST be added to `scripts/seed_methodology.py`:

```python
{
    "id":           "unique_snake_case_id",
    "name":         "Human Readable Name",
    "provenance":   "MEASURED|CALCULATED|INFERRED",
    "layer":        "silicon|os|application|orchestration",
    "confidence":   1.0,
    "description":  "...",
    "formula_latex": r"...",
    "parameters":   {},
}
```

### Rule MPC-3: Every New Method Gets References
Add YAML to `config/methodology_refs/<method_id>.yaml`:
```yaml
method_id: your_method_id
references:
  - title: "..."
    authors: "..."
    year: 2024
    ref_type: "manual|paper|internal"
    relevance: "..."
```

### Rule MPC-4: Every New Derived Metric Gets a Doc Section
Add to appropriate doc in `docs-src/mkdocs/source/research/`:
- Hardware readers → `07-energy-readers-methodology.md`
- OS/system → `08-system-measurement-methodology.md`
- Computed metrics → `09-derived-metrics-methodology.md`

### Rule MPC-5: Provenance Regression Must Pass
After ANY change:
```bash
bash scripts/test_provenance.sh   # MUST pass 22/22
```

### Rule MPC-6: METHOD_CONFIDENCE Must Be In Sync
Every `method_id` in `COLUMN_PROVENANCE` MUST have an entry in `METHOD_CONFIDENCE`:
```python
METHOD_CONFIDENCE = {
    "your_method_id": 1.0,   # add this
}
```
Validated at import time — will raise `ValueError` if missing.

---

## 3. Documentation Compliance (DC)

### Rule DC-1: 30% Inline Comments
Every new Python file must have ~30% inline comments.
Comments explain WHY, not WHAT.

```python
# WRONG
x = x + 1  # increment x

# RIGHT
x = x + 1  # offset by 1 because /proc/stat fields are 1-indexed
```

### Rule DC-2: Docstrings on Every Method
```python
def my_method(self, param: int) -> float:
    """
    One-line summary.

    Longer explanation if needed.

    Args:
        param: What it is and valid range.

    Returns:
        What the return value means.
    """
```

### Rule DC-3: No Silent Failures
```python
# WRONG
try:
    value = read_sensor()
except:
    pass

# RIGHT
try:
    value = read_sensor()
except Exception as e:
    logger.warning("Sensor read failed: %s", e)
    value = None   # explicit None, documented
```

### Rule DC-4: Early Return Pattern
```python
# WRONG — deep nesting
def process(data):
    if data:
        if data.valid:
            if data.value > 0:
                return compute(data.value)

# RIGHT — early return
def process(data):
    if not data or not data.valid:
        return None
    if data.value <= 0:
        return None
    return compute(data.value)
```

### Rule DC-5: Max 8 Space Indentation
Never exceed 2 levels of indentation (8 spaces). Refactor if deeper.

### Rule DC-6: New Doc Files Go in mkdocs.yml
Any new `.md` file in `docs-src/mkdocs/source/` MUST be added to `mkdocs.yml` nav section.

---

## 4. Schema Compliance (SC)

### Rule SC-1: schema.py is Single Source of Truth
`core/database/schema.py` CREATE TABLE statements MUST always match the live DB.
Fresh checkout → `create_tables()` → identical schema to production DB.

### Rule SC-2: Migration + Schema Must Be In Sync
Every `ALTER TABLE` migration MUST have a matching change in `schema.py`.

```
Migration adds column → schema.py adds same column
Migration creates table → schema.py adds CREATE TABLE
```

### Rule SC-3: Migration Naming
```
scripts/migrations/NNN_description.sql
```
Where NNN is sequential (015, 016, 017...). Never reuse numbers.

### Rule SC-4: ETL-Populated Columns Insert as NULL
Columns populated by ETL (not at INSERT time) must:
1. Be NULL in the INSERT statement params
2. Have a corresponding ETL function that does UPDATE
3. Be documented as "ETL populated" in schema.py comment

```python
# In runs.py INSERT params:
None,  # planning_energy_uj — ETL populated by phase_attribution_etl.py
```

### Rule SC-5: Backward Compat Always
Never DROP or RENAME columns in production migrations.
Old columns kept forever. New columns added alongside.

### Rule SC-6: sqlite_adapter.py Must Import New Tables
Any new CREATE TABLE in `schema.py` must be imported and called in `core/database/sqlite_adapter.py`:
```python
from .schema import (CREATE_RUNS, CREATE_IO_SAMPLES, ...)  # add import
self.conn.executescript(CREATE_IO_SAMPLES)                   # add call
```

---

## 5. Code Quality Compliance (CQC)

### Rule CQC-1: Grep Before Writing
NEVER assume file contents. Always grep first:
```bash
grep -n "relevant_term" path/to/file | head -10
```

### Rule CQC-2: Low Token Mode
- Surgical find/replace only — never rewrite whole files
- Grep surgically — never `cat` full files
- Give exact copy-paste commands — no manual work

### Rule CQC-3: Test After Every Change
```bash
# Minimum test suite after any change:
bash scripts/test_provenance.sh
python -m core.execution.tests.test_harness --task-id gsm8k_basic --repetitions 1 --provider local --verbose
bash scripts/test_runs_regression_extended.sh
```

### Rule CQC-4: No Debug Prints in Production
Replace all `print(f"🔍 DEBUG...")` with `logger.debug(...)`.
(Tracked in Chunk 11)

### Rule CQC-5: Modular Code
Functions do ONE thing. Max 50 lines per function.
If longer — split into helpers.

### Rule CQC-6: No Hardcoded Paths
Device names, file paths, thresholds come from `hw_config.json` or constants:
```python
# WRONG
device = "sda"

# RIGHT
device = config.get("hardware", {}).get("disk_device", "sda")
```

---

## 6. Must-Know Architecture

### Data Flow
```
Experiment runs
    → harness.py captures raw samples
    → experiment_runner.py inserts to DB
    → async ETL: phase_attribution_etl.py + aggregate_hardware_metrics.py
    → runs table fully populated
```

### Three-Layer Energy Model
```
Layer 1: raw          RawEnergyMeasurement (RAPL counters)
Layer 2: baseline     idle_baselines (subtract background power)
Layer 3: derived      DerivedEnergyMeasurement (attributed, normalized)
```

### Sample Tables (never compute at read time)
```
energy_samples    100Hz  RAPL cumulative counters
cpu_samples        10Hz  turbostat + perf cache
interrupt_samples  10Hz  /proc/stat ticks
io_samples         10Hz  /proc/diskstats deltas
thermal_samples     1Hz  hwmon sensors
```

### ETL Pattern
```
INSERT time: ETL columns = NULL
ETL runs async after save_pair()
ETL does UPDATE on runs table
Backfill: python scripts/etl/<etl_name>.py --backfill-all
```

### Machines
```
UBUNTU2505  x86_64  bare metal  MEASURED   RAPLReader  ← primary dev
alems-vnic  aarch64 KVM VM      INFERRED   EnergyEstimator (zeros)
macOS       any     —           MEASURED   IOKitPowerReader (stub)
```

---

## 7. Regression Tests — Always Run In This Order

```bash
python scripts/seed_methodology.py           # if readers/methods changed
python scripts/migrate_yaml_to_db.py         # if display config changed
bash scripts/test_provenance.sh              # MUST pass 22/22
bash scripts/test_runs_regression.sh         # core checks
bash scripts/test_runs_regression_extended.sh # all 110 columns
python scripts/validate_phase_attribution.py  # 5 phase checks
python scripts/etl/phase_attribution_etl.py --run-id $(sqlite3 data/experiments.db "SELECT MAX(run_id) FROM runs WHERE workflow_type='agentic';")
python scripts/etl/aggregate_hardware_metrics.py --run-id $(sqlite3 data/experiments.db "SELECT MAX(run_id) FROM runs;")
```

---

## 8. Known Pre-Existing Issues (Do Not Fix Without Chunk Assignment)

| Issue | Location | Assigned To |
|-------|----------|-------------|
| `frequency_mhz < 400` on idle runs | test_runs_regression_extended.sh | Chunk 11 |
| Debug prints throughout codebase | experiment_runner.py, harness.py | Chunk 11 |
| Duplicate backward-compat energy conversion | experiment_runner.py | Chunk 11 |
| aggregate_run_stats only runs inside thermal block | experiment_runner.py | Chunk 11 |
| DiskReader not routed via factory | energy_engine.py | Chunk 14 |
| DummyCPUReader on macOS | factory.py | Chunk 14 |
| IOKitPowerReader returns zeros | darwin/iokit_reader.py | Chunk 1.1 |
| EnergyEstimator returns zeros | fallback/estimator.py | Chunk 1.2 |
| synthesis_energy=0 local runs | phase_attribution_etl.py | Chunk 14 |
| voltage_vcore=NULL ThinkPad | sensor_reader.py | Expected behavior |
