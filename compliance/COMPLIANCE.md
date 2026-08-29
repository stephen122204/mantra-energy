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

**PAC-2 Extension: Cross-platform metrics must be computed inside readers, not scattered across harness/analyzer.**
Any metric that exists on all platforms (e.g. `cpu_active_ratio`, `frequency_mhz`) must be computed inside the platform's reader and returned in `stop_monitoring()` summary dict. The harness and energy_analyzer must read it generically via `summary.get("metric_name")` with no platform branching. Adding a metric to harness.py with `if platform == Darwin` or `or derived.cpu_active_ratio` is a PAC-2 violation. Every reader's `stop_monitoring()` summary is the single insertion point for new cross-platform metrics.

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

## 9. Experiment Integrity Compliance (EIC)

### Rule EIC-1: Run Integrity Check After Every Experiment
After any experiment that saves to DB, run:
```bash
python scripts/test_exp_integrity.py --latest
```
All checks must pass (0 failed) before declaring experiment complete.

### Rule EIC-2: Run Integrity Check Before Chunk Handoff
Before handing off to next chunk/agent, run integrity check on the last
experiment of each type that was run:
```bash
python scripts/test_exp_integrity.py --latest --experiment-type failure_injection
python scripts/test_exp_integrity.py --latest --experiment-type retry_study
python scripts/test_exp_integrity.py --latest --experiment-type normal
```

### Rule EIC-3: Warnings Are Not Failures But Must Be Documented
Warnings (⚠️) in integrity check must be documented in the implementation
record with a reason. Silent warnings are not acceptable.

### Rule EIC-4: New Tables Must Be Added to Integrity Checker
Any new table added in a chunk that receives data at runtime MUST be added
to `scripts/test_exp_integrity.py` before chunk handoff.
---

## 10. Turbostat Compliance (TC)
*Added after Bug 5: kernel upgrade regression, env_id 39->40, 2026-05-08*

### Rule TC-1: No Hardcoded Turbostat Binary Path
NEVER write or read `real_binary` in hw_config.json.
TurbostatReader resolves binary at runtime via `platform.release()`.
A static path breaks silently on every kernel upgrade.

```python
# WRONG — breaks on kernel upgrade
self.turbostat_path = config["turbostat"]["real_binary"]

# RIGHT — self-healing, always current kernel
self.turbostat_path = self._find_turbostat()  # uses platform.release()
```

### Rule TC-2: TURBOSTAT_COLUMNS is Single Source of Truth
Column mappings live ONLY in `core/readers/turbostat_resolver.py`.
Never in hw_config.json, turbostat_override.yaml, or any other file.
Changing a mapping = bump version suffix in downstream method_id.

```python
# WRONG — columns from config file, can drift
self.column_map = config.get("turbostat", {}).get("columns", {})

# RIGHT — from code constant, versioned in git
from core.readers.turbostat_resolver import TURBOSTAT_COLUMNS
self.column_map = TURBOSTAT_COLUMNS
```

### Rule TC-3: Always --select, Never --show
`--select` filters turbostat output to exactly the requested columns.
`--show` returns all columns — format varies across kernel versions.
Always use `--select` with `get_select_string()` from turbostat_resolver.

```bash
# WRONG — format varies across kernel versions
turbostat --show all

# RIGHT — deterministic output format
turbostat --Summary --select Busy%,PkgTmp,CPU%c6,...
```

### Rule TC-4: TurbostatReader via Factory Only (PAC-2)
TurbostatReader must only be instantiated via `ReaderFactory.get_turbostat_reader()`.
Never directly in energy_engine.py or anywhere else.
Factory handles platform conditional (Linux x86 vs macOS vs other).

```python
# WRONG — direct instantiation, PAC-2 violation
self.turbostat = TurbostatReader(config)

# RIGHT — factory, platform-aware
self.turbostat = ReaderFactory.get_turbostat_reader(config)
```

### Rule TC-5: detect_hardware.py Must Not Write real_binary
detect_hardware.py runs once at setup. It must not write `real_binary`
to hw_config.json — that path becomes stale on kernel upgrade.
detect_hardware.py writes hardware topology only (RAPL paths, CPU flags, etc).

---

## 11. Python Version Compatibility (PVC)
*Added after turbostat fix session — reproducibility requires broad Python compat*

### Rule PVC-1: Minimum Python Version is 3.9
All code must run on Python 3.9+.
Target: any machine a reviewer might use to reproduce results.

### Rule PVC-2: No 3.10+ Type Hint Syntax
```python
# WRONG — Python 3.10+ only
def foo(x: int | None) -> tuple[str, int]: ...

# RIGHT — Python 3.9 compatible
from typing import Optional, Tuple
def foo(x: Optional[int]) -> Tuple[str, int]: ...
```

### Rule PVC-3: Use # type: comments for inline hints in complex functions
```python
def resolve():
    # type: () -> Tuple[Optional[str], str]
    ...
```

### Rule PVC-4: No match/case Statements
`match/case` is Python 3.10+. Use `if/elif/else`.

### Rule PVC-5: Test on Python 3.9 Before Handoff
```bash
python3.9 -c "import core.readers.turbostat_resolver; print('OK')"
python3.9 -m core.execution.tests.test_harness \
  --task-id gsm8k_basic --repetitions 1 --provider local
```

---

## 12. Forensic Audit Design (FAD)
*Added after Bug 5 discovery — environment_config forensic tracing*

### Rule FAD-1: environment_config is the Forensic Anchor
Every experiment records kernel_version + git_commit + env_id.
When a measurement anomaly is detected, first query:
```sql
SELECT e.exp_id, ec.kernel_version, ec.git_commit, ec.created_at
FROM experiments e
JOIN environment_config ec ON ec.env_id = e.env_id
WHERE e.exp_id BETWEEN X AND Y
ORDER BY e.exp_id;
```
This identifies the exact infrastructure change that caused the anomaly.

### Rule FAD-2: Silent Zeros Are Bugs
Any measurement column returning 0.0 for ALL runs after a certain
experiment ID must be treated as a measurement bug, not a hardware result.
0.0 package_temp is thermally impossible. 0.0 C-state residency is
operationally impossible. Investigate immediately.

### Rule FAD-3: New Measurement Columns Must Have Sentinel Detection
Any new measurement column added to runs or cpu_samples must have a
corresponding check in `scripts/test_exp_integrity.py` that flags
all-zero values as a WARNING after 10+ consecutive runs.

---

## 10. Turbostat Compliance (TC)
*Added after Bug 5: kernel upgrade regression, env_id 39->40, 2026-05-08*

### Rule TC-1: No Hardcoded Turbostat Binary Path
NEVER write or read `real_binary` in hw_config.json.
TurbostatReader resolves binary at runtime via `platform.release()`.
A static path breaks silently on every kernel upgrade.

```python
# WRONG — breaks on kernel upgrade
self.turbostat_path = config["turbostat"]["real_binary"]

# RIGHT — self-healing, always current kernel
self.turbostat_path = self._find_turbostat()  # uses platform.release()
```

### Rule TC-2: TURBOSTAT_COLUMNS is Single Source of Truth
Column mappings live ONLY in `core/readers/turbostat_resolver.py`.
Never in hw_config.json, turbostat_override.yaml, or any other file.
Changing a mapping = bump version suffix in downstream method_id.

```python
# WRONG — columns from config file, can drift
self.column_map = config.get("turbostat", {}).get("columns", {})

# RIGHT — from code constant, versioned in git
from core.readers.turbostat_resolver import TURBOSTAT_COLUMNS
self.column_map = TURBOSTAT_COLUMNS
```

### Rule TC-3: Always --select, Never --show
`--select` filters turbostat output to exactly the requested columns.
`--show` returns all columns — format varies across kernel versions.
Always use `--select` with `get_select_string()` from turbostat_resolver.

```bash
# WRONG — format varies across kernel versions
turbostat --show all

# RIGHT — deterministic output format
turbostat --Summary --select Busy%,PkgTmp,CPU%c6,...
```

### Rule TC-4: TurbostatReader via Factory Only (PAC-2)
TurbostatReader must only be instantiated via `ReaderFactory.get_turbostat_reader()`.
Never directly in energy_engine.py or anywhere else.
Factory handles platform conditional (Linux x86 vs macOS vs other).

```python
# WRONG — direct instantiation, PAC-2 violation
self.turbostat = TurbostatReader(config)

# RIGHT — factory, platform-aware
self.turbostat = ReaderFactory.get_turbostat_reader(config)
```

### Rule TC-5: detect_hardware.py Must Not Write real_binary
detect_hardware.py runs once at setup. It must not write `real_binary`
to hw_config.json — that path becomes stale on kernel upgrade.
detect_hardware.py writes hardware topology only (RAPL paths, CPU flags, etc).

---

## 11. Python Version Compatibility (PVC)
*Added after turbostat fix session — reproducibility requires broad Python compat*

### Rule PVC-1: Minimum Python Version is 3.9
All code must run on Python 3.9+.
Target: any machine a reviewer might use to reproduce results.

### Rule PVC-2: No 3.10+ Type Hint Syntax
```python
# WRONG — Python 3.10+ only
def foo(x: int | None) -> tuple[str, int]: ...

# RIGHT — Python 3.9 compatible
from typing import Optional, Tuple
def foo(x: Optional[int]) -> Tuple[str, int]: ...
```

### Rule PVC-3: Use # type: comments for inline hints in complex functions
```python
def resolve():
    # type: () -> Tuple[Optional[str], str]
    ...
```

### Rule PVC-4: No match/case Statements
`match/case` is Python 3.10+. Use `if/elif/else`.

### Rule PVC-5: Test on Python 3.9 Before Handoff
```bash
python3.9 -c "import core.readers.turbostat_resolver; print('OK')"
python3.9 -m core.execution.tests.test_harness \
  --task-id gsm8k_basic --repetitions 1 --provider local
```

---

## 12. Forensic Audit Design (FAD)
*Added after Bug 5 discovery — environment_config forensic tracing*

### Rule FAD-1: environment_config is the Forensic Anchor
Every experiment records kernel_version + git_commit + env_id.
When a measurement anomaly is detected, first query:
```sql
SELECT e.exp_id, ec.kernel_version, ec.git_commit, ec.created_at
FROM experiments e
JOIN environment_config ec ON ec.env_id = e.env_id
WHERE e.exp_id BETWEEN X AND Y
ORDER BY e.exp_id;
```
This identifies the exact infrastructure change that caused the anomaly.

### Rule FAD-2: Silent Zeros Are Bugs
Any measurement column returning 0.0 for ALL runs after a certain
experiment ID must be treated as a measurement bug, not a hardware result.
0.0 package_temp is thermally impossible. 0.0 C-state residency is
operationally impossible. Investigate immediately.

### Rule FAD-3: New Measurement Columns Must Have Sentinel Detection
Any new measurement column added to runs or cpu_samples must have a
corresponding check in `scripts/test_exp_integrity.py` that flags
all-zero values as a WARNING after 10+ consecutive runs.
## 13. Measurement Integrity Compliance (MIC)
 
### Rule MIC-1: NULL != 0.0 — Never Store Missing as Zero
Any measurement column that could not be read MUST be stored as NULL.
0.0 is a valid scientific measurement. NULL means unavailable.
Storing missing data as 0.0 corrupts averages, regressions, and plots.
 
    # WRONG — silent corruption
    sample[metric] = 0.0  # when sensor unavailable
 
    # RIGHT — scientifically correct
    sample[metric] = None  # NULL in DB, excluded from AVG() automatically
 
### Rule MIC-2: ETL Must Propagate NULL
ETL functions must never coerce NULL to 0.0.
Use: value or None (not value or 0)
SQLite AVG(), MIN(), MAX() exclude NULL automatically — use this.
 
### Rule MIC-3: Sentinel Detection for All-Zero Columns
Any new measurement column must have a check in test_exp_integrity.py
that flags all-zero values as WARNING after 10+ consecutive runs.
All-zero in a REAL measurement column = likely measurement failure.

### Rule SC-7: Schema Changes Must Update schema_version Table
Every migration that changes DDL MUST insert into schema_version:
```sql
INSERT INTO schema_version (version, applied_at, description)
VALUES (<next_version>, datetime('now'), 'Description of change');
```
Data-only migrations (INSERT/UPDATE) do NOT get a schema_version entry.
After any DDL migration, re-run `scripts/detect_environment.py` to 
regenerate `env_hash` with new schema_version in `environment.json`.

## Rule: test_harness.py and run_experiment.py must stay in sync
Any change to core execution flow in `core/execution/tests/test_harness.py`
must be mirrored in `scripts/run_experiment.py` (and vice versa).
These serve different purposes (single vs multi task) but share the same
harness call patterns. Divergence causes silent measurement inconsistencies.
Applies to: run_agentic(), run_linear(), tool_graph wiring, save_pair(),
save_single(), goal_execution tracking, provider config.
## 14. Energy Engine Isolation (EEI)

### Rule EEI-1: EnergyEngine Never Touches the Database
EnergyEngine is a measurement component. It reads hardware. It never writes
to, queries, or opens a connection to any database. No sqlite3.connect(),
no db.conn, no DatabaseManager reference anywhere in energy_engine.py.

### Rule EEI-2: DB Connections Only in Repository Layer
All DB access goes through:
    DatabaseManager → SamplesRepository → self.db.conn.execute()
Never open sqlite3.connect() directly outside of sqlite_adapter.py.
Opening a second connection on the same SQLite file causes database locked
errors that are silent and hard to diagnose.

### Rule EEI-3: Writers Are Buffers Only
NormalizedWriter and LegacyWriter buffer samples during measurement.
They never open DB connections. They return buffers via flush().
experiment_runner inserts after insert_run() assigns run_id.
Pattern: measure → buffer → insert_run() → insert samples with run_id.

### Rule EEI-4: run_id Is Never Available at Measurement Time
run_id is assigned by insert_run() which happens AFTER stop_measurement().
Any code that tries to use run_id during or before stop_measurement() is wrong.
Writers receive run_id only via experiment_runner after insert_run() returns.

## 15. Publication-Grade Documentation Standards (PDS)

A-LEMS produces research papers targeting SIGMETRICS, ISPASS, SC, and AAAI.
Every document, guide, and methodology reference is a potential paper supplement
or reviewer artifact. Agents must write to that standard unconditionally.

### Rule PDS-1: No Internal Names in Public Documents

WRONG — exposes internal lab structure, student names, machine nicknames:
  "Alex's AMD machine", "Stephen's M1", "Deepak's GN100", "the Lenovo box"
  "Chunk 16", "chunk folder", "16D session", "today's run"

RIGHT — use canonical platform identifiers:
  "AMD Ryzen platform (RTX 2070 Super)", "Apple M1 Pro platform"
  "NVIDIA Grace GB10 (GN100, aarch64)", "Intel i7-1165G7 platform (x86_64)"

Rule: Every platform reference in a document uses the canonical ID from
the Platform Matrix in MASTER_SPEC_CHUNK16. Never use hostnames, student
names, or informal machine nicknames in any document visible outside the lab.

### Rule PDS-2: Every Methodology Document Has These Sections

All methodology documents (docs-src/mkdocs/source/research/*.md) must contain:

  1. ## Overview          — what the method measures, why it exists
  2. ## Platform Coverage — table: Platform | Source | Canonical Role | Confidence
  3. ## Schema            — table of all new columns/tables with types and semantics
  4. ## Method Provenance — method_id, confidence, layer, formula, justification
  5. ## Query Reference   — copy-paste SQL for every common analysis query
  6. ## Verification      — step-by-step commands to confirm correct operation
  7. ## Known Limitations — explicit statement of what this method cannot measure

Missing any section = document is incomplete. Agent must not submit a doc
without all 7 sections present.

### Rule PDS-3: No Chunk References in Documents

WRONG: "Added in Chunk 16D", "Chunk 7 factorization", "16B fix"
RIGHT: "Introduced in schema version 65", "Available since platform v2.1"

Documents are read by paper reviewers who have no context for internal
chunk numbering. Use schema versions and capability flags instead.

### Rule PDS-4: All SQL in Documents Must Be Tested

Every SQL query in a methodology document must be verified to run without
error on at least one platform DB before the document is committed.
Untested SQL in a document is a compliance violation (FAD-2 equivalent).

Verification command pattern:
  sqlite3 $DB "< paste query here >" 2>&1 | head -5
  # Must return rows or empty set, never an error.

### Rule PDS-5: Platform Coverage Table Is Mandatory

Every methodology document must include a platform coverage table:

| Platform | Architecture | Source | Canonical Role | Confidence | Status |
|----------|-------------|--------|---------------|------------|--------|
| NVIDIA Grace GB10 | aarch64 | acpitz sysfs | SOC | 0.92 | VERIFIED |
| Intel i7-1165G7 | x86_64 | x86_pkg_temp sysfs | CPU_PACKAGE | 0.92 | VERIFIED |
| AMD Ryzen | x86_64 | k10temp sysfs | CPU_PACKAGE | 0.92 | PENDING |
| Apple M1 Pro | arm64 | IOKit (future) | CPU_PACKAGE | TBD | PLANNED |

Status values: VERIFIED (tested on real hardware), PENDING (implemented not tested),
PLANNED (designed not implemented), NOT_SUPPORTED (explicitly excluded).

### Rule PDS-6: Confidence Scores Must Be Justified

Every confidence score in a methodology document must have an explicit
written justification explaining:
  (a) Why it is not 1.0 — what uncertainty exists
  (b) What would need to be true for it to reach 1.0
  (c) How the uncertainty affects paper results quantitatively if known

WRONG: "Confidence: 0.90 (polling lag)"
RIGHT: "Confidence 0.92: ACPI thermal zones poll at ~100ms intervals,
        introducing up to 100ms lag between true silicon temperature and
        reported value. Under sustained LLM inference (>10s runs) this
        averages out to <0.5°C error. For sub-second measurements this
        method should not be used. To reach 1.0 would require direct
        silicon temperature via MSR (unavailable on ARM)."

### Rule PDS-7: Query Reference Section Is for Researchers

The Query Reference section must be written for a researcher who has never
seen the codebase. Every query must include:
  - A plain-English description of what it answers
  - The exact SQL (tested per PDS-4)
  - Expected output format and typical values
  - Which platforms the query applies to

WRONG: "Query thermal data from v_thermal_cpu"
RIGHT:
  "**Cross-run thermal trend on GN100** — answers: does the SoC run hotter
   over time as the hardware ages?
   Applies to: NVIDIA Grace GB10 (aarch64) only (SOC role zones).
   Expected output: one row per run, avg_temp typically 40-55°C at load.
````sql
   SELECT r.run_id, r.created_at,
          AVG(ts.temp_celsius) as avg_soc_temp_c,
          MAX(ts.temp_celsius) as peak_soc_temp_c
   FROM thermal_samples_v2 ts
   JOIN runs r ON ts.run_id = r.run_id
   JOIN thermal_zones tz ON ts.zone_id = tz.zone_id
   WHERE tz.machine_id = 'gn100-2b96'
     AND tz.canonical_role = 'SOC'
     AND ts.quality_flag = 'VALID'
   GROUP BY r.run_id ORDER BY r.run_id;
```"

### Rule PDS-8: No Hardcoded Hostnames in Documents

WRONG: "WHERE machine_id = 'gn100-2b96'"
RIGHT: "WHERE machine_id = '<your-hostname>' -- replace with socket.gethostname()"

Exception: verified example output may show actual hostname as illustration,
clearly labelled as "Example output from NVIDIA Grace GB10 platform".

### Rule PDS-9: Known Limitations Must Be Honest

Every methodology document must explicitly state what the method CANNOT do.
Omitting known limitations is a scientific integrity violation.

Required format:
  ### Known Limitations
  - **<Limitation name>**: <what cannot be measured and why>
    Workaround: <alternative if any, or "None — accept NULL">

### Rule PDS-9b: Two-Document Rule — Methodology vs Explanatory

Every measurement method has exactly TWO documents:

  1. config/methodology_refs/<method_id>.yaml
     — machine-readable, compact
     — referenced by "doc" field in seed_methodology
     — contains ONLY: method_id, references, formula, parameters, confidence
     — NO prose, NO query examples, NO platform war stories
     — Max 50 lines

  2. docs-src/mkdocs/source/research/<NN>-<topic>.md
     — human-readable, full explanatory guide
     — contains: platform coverage, query reference, verification, limitations
     — written for paper reviewers and researchers unfamiliar with the codebase
     — NOT referenced by seed_methodology

The "doc" field in seed_methodology entries points to the explanatory .md
only for the section heading lookup. The YAML is the authoritative method spec.
A researcher querying the DB sees the YAML content — compact and precise.
The .md is for humans reading the docs site.

Every methodology document must start with a version header block:

  ---
  **Method ID:** thermal_zone_sysfs_v2
  **Schema version:** 65 (thermal_zones), 67 (thermal_samples_v2)
  **Platforms verified:** NVIDIA Grace GB10 (aarch64), Intel i7-1165G7 (x86_64)
  **Status:** PRODUCTION
  **Last updated:** <date>
  ---

Status values: DRAFT, REVIEW, PRODUCTION, DEPRECATED.

## Migration Source Control (MSC)
```

Apply this to `compliance/COMPLIANCE.md`, then commit. After that I produce the thermal methodology document correctly following all 10 PDS rules.

MSC-1: Every file in migrations/schema/ and migrations/seed/ is immutable
       after first commit. Fix forward with a new file. No exceptions.
       Violation = checksum mismatch detected by alems migrate --verify.

MSC-2: Every experiment run must record migration_set_hash from manifest.json
       in environment_config. NULL migration_set_hash is acceptable for
       historical rows only. Never acceptable for new rows after Chunk M3 ships.

MSC-3: Machine-specific scripts live only under scripts/machine_setup/<hostname>/.
       They are never placed in migrations/schema/ or migrations/seed/.
       Violation = GN100 test data silently applying to UBUNTU2505.

MSC-4: migrations/schema/ contains DDL only (CREATE, ALTER, DROP).
       migrations/seed/ contains data only (INSERT, UPDATE, DELETE).
       A schema/ file with INSERT is a violation. A seed/ file with
       ALTER TABLE is a violation.

## 16. Migration System (Database Changes)
Any DB schema change MUST follow compliance/MIGRATION_GUIDE.md before touching any migration file.
