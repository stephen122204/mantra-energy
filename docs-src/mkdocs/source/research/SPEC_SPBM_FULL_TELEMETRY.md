# SPEC: SPBM Full Power Telemetry (GN100)

## Spec ID: SPEC_SPBM_FULL_TELEMETRY
## Status: DRAFT — FOR REVIEW
## Target: A-LEMS platform, GN100 (Grace+Blackwell GB10, aarch64) only
## Depends on: SPEC_GPU_DUAL_CHANNEL (shares energy_sample_domains write path)
## Read after: MASTER_SPEC_CHUNK16, SPEC_GPU_DUAL_CHANNEL, COMPLIANCE.md

---

## 1. Purpose

GN100's SPBM hwmon device (`spark_hwmon`, device `NVDA8800:00`) exposes 14
instantaneous power channels. Today only 4 are read by name
(`sys_total`, `cpu_p`, `cpu_e`, `gpu`). Ten are unread. Four of those ten
(`pl1`, `pl2`, `syspl1`, `syspl2`) are firmware power *limits*, not
consumption telemetry, and are explicitly out of scope for energy
accounting. The remaining six are real, unread consumption rails:

    soc_pkg, cpu_gpu, vcore, dc_input, prereg, dla

This spec adds continuous sampling, integration, and storage for these
six rails, plus the configuration-state table needed to keep limit
values out of the telemetry schema.

**Research motivation:** `dc_input` is the outermost SPBM measurement
boundary on this board. `pkg` (already captured) is the package/silicon
boundary. The gap between them — if `dc_input` is confirmed to sit
upstream of `pkg` in the power delivery chain — is conversion and
voltage-regulation loss currently invisible to the platform. A
"complete system energy" claim in any paper is incomplete without
addressing this gap or explicitly disclaiming it.

---

## 2. Hardware ground truth (verified 2026-06-21, GN100, hwmon7)

### Energy accumulators (cumulative, µJ) — complete, no change in this spec

| sysfs file | label | Status |
|---|---|---|
| energy1_input | pkg | Captured (existing) |
| energy2_input | cpu_e | Captured (existing) |
| energy3_input | cpu_p | Captured (existing) |
| energy4_input | gpu | Captured (existing) |

Only 4 energy accumulators exist on this hardware. This is complete
coverage of cumulative counters. No gap here.

### Power channels (instantaneous, mW) — 4 of 14 currently read

| sysfs file | label | Status | This spec |
|---|---|---|---|
| power1_input | sys_total | Captured (existing) | no change |
| power2_input | soc_pkg | **Not captured** | ADD |
| power3_input | cpu_gpu | **Not captured** | ADD |
| power4_input | cpu_p | Captured (existing) | no change |
| power5_input | cpu_e | Captured (existing) | no change |
| power6_input | vcore | **Not captured** | ADD |
| power7_input | dc_input | **Not captured** | ADD |
| power8_input | gpu | Captured (existing) | no change |
| power9_input | prereg | **Not captured** | ADD |
| power10_input | dla | **Not captured** | ADD |
| power11_input | pl1 | Not telemetry | EXCLUDE (limit) |
| power12_input | pl2 | Not telemetry | EXCLUDE (limit) |
| power13_input | syspl1 | Not telemetry | EXCLUDE (limit) |
| power14_input | syspl2 | Not telemetry | EXCLUDE (limit) |

---

## 3. Channel classification (authoritative)

| Tier | Channels | Purpose |
|---|---|---|
| Primary energy | pkg, cpu_p, cpu_e, gpu | Exact hardware counters. Unchanged by this spec. |
| System boundary | dc_input, sys_total | Outermost measurement point. Enables conversion-loss derivation. |
| Sub-rail diagnostic | soc_pkg, cpu_gpu, vcore, prereg, dla | Finer decomposition inside the package boundary. Attribution research, not top-line totals. |
| Configuration (not telemetry) | pl1, pl2, syspl1, syspl2 | Firmware-enforced limits. Never stored as energy/power samples. See Section 6. |

**Definition, locked for this schema:** `energy_domains` represents a
distinct physical measurement boundary or hardware rail. It does not
represent "anything energy-related." Configuration and limit values are
explicitly excluded from this table by definition, not by convention.

---

## 4. Uncertainty model (no invented numeric confidence)

Per-rail confidence values are **not** asserted in this spec. Instead,
the methodology registry entry declares the uncertainty model
structurally, to be populated with real numbers once characterized.

```
Raw SPBM rail (any of the 6 new power channels):
    provenance: MEASURED
    uncertainty_source: sensor characteristics (vendor-defined,
                         pending characterization — ADC resolution,
                         firmware filtering, sensor latency,
                         calibration)

Integrated energy per rail per run:
    provenance: CALCULATED
    uncertainty_depends_on:
        - raw sensor uncertainty (above)
        - sampling_interval
        - integration_method
```

No numeric confidence score is assigned to either layer until a
characterization pass is run against a known load. This spec does not
include that characterization — it is a prerequisite for any paper
claim using these rails, tracked as a separate open item (Section 11).

---

## 5. Methodology: numerical integration (doc wording, locked)

Methodology document language, to be used verbatim in
`07-energy-readers-methodology.md`:

> Energy for rails without a hardware cumulative counter is estimated
> by numerical integration of sampled instantaneous power using the
> platform sampling interval.

The specific integration algorithm (rectangular, trapezoidal, or
otherwise) is an implementation detail and must be documented only in
code comments and the IMPLEMENTATION_RECORD for this spec, never in the
methodology document itself. This keeps the methodology doc stable if
the algorithm is later improved.

**Implementation note (non-binding on the methodology doc):**
trapezoidal integration should be evaluated over the simple rectangular
`power_i * dt_i` pattern used for GPU dynamic energy, since these rails
may exhibit faster transients than GPU compute load. This decision is
deferred to implementation time.

---

## 6. Schema changes

### 6a. New telemetry domains (energy_domains table)

Add six new rows, consistent with the existing domain_id sequence
(verify next available id at implementation time — do not assume):

```sql
INSERT INTO energy_domains (name, parent_domain_id, is_leaf, is_cumulative, unit, reader_keys)
VALUES
    ('SOC_PKG',  1, 1, 0, 'mW', 'soc_pkg'),
    ('CPU_GPU',  1, 1, 0, 'mW', 'cpu_gpu'),
    ('VCORE',    1, 1, 0, 'mW', 'vcore'),
    ('DC_INPUT', NULL, 1, 0, 'mW', 'dc_input'),
    ('PREREG',   1, 1, 0, 'mW', 'prereg'),
    ('DLA',      1, 1, 0, 'mW', 'dla');
```

`is_cumulative = 0` for all six — these are power readings requiring
integration, unlike the existing cumulative energy domains. `DC_INPUT`
has no parent_domain_id (NULL) since it is a system boundary, not a
sub-rail of PACKAGE. Verify this parent/child structure against the
actual `energy_domains` schema before writing the migration — do not
assume the column accepts NULL without checking.

### 6b. New configuration table — `hardware_configuration`

Separate from telemetry by design (see Section 3). Stores firmware
power limits and any future static/rarely-changing hardware state
(governor, boost-enable, thermal mode, power profile). Snapshot
semantics: captured once per run or once per experiment session, not
sampled continuously.

```sql
CREATE TABLE IF NOT EXISTS hardware_configuration (
    config_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL,
    config_key      TEXT NOT NULL,      -- e.g. 'pl1', 'pl2', 'syspl1', 'syspl2'
    config_value    REAL,
    unit            TEXT,
    captured_at     REAL DEFAULT (unixepoch()),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
```

PL1/PL2/SYSPL1/SYSPL2 readings go here, not into
`energy_sample_domains`, regardless of how trivial it would be to treat
them identically to the telemetry rails. This is the structural fix
this spec exists partly to make.

### 6c. Sampling quality metadata

Required to defend any integration-derived energy value against the
question "how do you know missing samples didn't bias the integral."
Add to `runs` (verify exact table via the same grep discipline as
SPEC_GPU_DUAL_CHANNEL Section 9a — do not assume placement):

```sql
ALTER TABLE runs ADD COLUMN spbm_power_sampling_freq_hz REAL;
ALTER TABLE runs ADD COLUMN spbm_samples_expected INTEGER;
ALTER TABLE runs ADD COLUMN spbm_samples_observed INTEGER;
ALTER TABLE runs ADD COLUMN spbm_coverage_pct REAL;
ALTER TABLE runs ADD COLUMN spbm_integration_method TEXT;
```

`spbm_coverage_pct = spbm_samples_observed / spbm_samples_expected * 100`,
computed and stored at run-stop time, not derived later. If coverage
falls below a threshold (TBD — suggest flagging below 95% for review,
exact threshold to be set during implementation), the run's integrated
energy values for these rails should be flagged, not silently trusted.

---

## 7. Derived metrics

### 7a. Conversion loss and efficiency

Computed only when both `dc_input` and `pkg` totals are available for
a run:

```
conversion_loss_uj   = dc_input_total_uj - pkg_total_uj
conversion_efficiency = pkg_total_uj / dc_input_total_uj
```

Dependency graph (for provenance generation):

```
dc_input ──┐
           ├──> conversion_loss_uj
pkg ───────┘

dc_input ──┐
           ├──> conversion_efficiency
pkg ───────┘
```

Both are `CALCULATED`, both inherit the compound uncertainty of their
two inputs (raw sensor uncertainty + integration uncertainty, per
Section 4) — same compounding caution already documented for
`gpu_residual_dynamic_uj` in SPEC_GPU_DUAL_CHANNEL.

### 7b. `dc_input` semantic caution — binding on all paper text

`dc_input` must be referred to only as "the SPBM rail labeled
`dc_input` by the spark_hwmon driver." No claim about what this rail
physically measures (board input, module input, SoC input, regulator
input) may appear in any paper or doc until verified against NVIDIA's
GB10/spark_hwmon vendor documentation. This verification is a blocking
prerequisite for Section 7a's metrics to be used in any publication
context — the metrics may be computed and stored immediately, but not
written up as "board power" or "wall power" until confirmed.

---

## 8. Methodology registry — parameterized, not per-rail

One registry entry, not six near-duplicates:

```
id: SPBM_INSTANTANEOUS_POWER_INTEGRATION_V1
name: SPBM Power Rail Integration
parameters: { rail: <SOC_PKG|CPU_GPU|VCORE|DC_INPUT|PREREG|DLA> }
output_metric: <rail>_energy_uj
provenance: CALCULATED
```

`seed_methodology.py` calls this once per rail with the `rail`
parameter set, rather than maintaining six independent method
definitions that would drift out of sync with each other.

Two additional standalone entries for the derived metrics:

```
id: spbm_conversion_loss_v1       (CALCULATED, depends on dc_input + pkg)
id: spbm_conversion_efficiency_v1 (CALCULATED, depends on dc_input + pkg)
```

---

## 9. What does NOT change

- The 4 existing energy accumulators (pkg, cpu_p, cpu_e, gpu) and their
  read/write path — untouched.
- `SPBM_ENERGY_CHANNELS` list in spbm_energy_reader.py — untouched.
- GPU_DCGM domain, GPUCollector, DCGM read path — untouched, fully
  independent of this spec.
- SPEC_GPU_DUAL_CHANNEL's three fields (gpu_spbm_total_uj,
  gpu_spbm_dynamic_uj, gpu_residual_dynamic_uj) — this spec is
  additive to that one, not a replacement. Both write to
  energy_sample_domains using the same domain-id pattern.
- goal_attempt / goal_execution tables — no new columns. Same
  deferral rationale as SPEC_GPU_DUAL_CHANNEL Section 8: no analysis
  today requires sub-rail energy at goal granularity.

---

## 10. Prerequisite verification (run before any code)

Mirrors SPEC_GPU_DUAL_CHANNEL Section 4 discipline. Run on GN100, paste
results back, do not assume.

```bash
# 10a. Confirm SPBMEnergyReader's current read loop structure
grep -n "_read_mw\|power_channels\|POWER_CHANNELS" core/readers/spbm_energy_reader.py

# 10b. Confirm next available energy_domains domain_id
sqlite3 "$DB" "SELECT MAX(domain_id) FROM energy_domains;"

# 10c. Confirm energy_sample_domains can accept non-cumulative (power-derived) rows
#      without breaking any existing SUM()-based query that assumes all rows
#      in this table are pre-computed deltas
grep -rn "energy_sample_domains" core/ scripts/ --include="*.py" | grep -v ".pyc"

# 10d. Confirm runs table does not already have any spbm_* sampling columns
#      under a different name (avoid duplicate-purpose columns)
sqlite3 "$DB" "PRAGMA table_info(runs);" | grep -i "spbm\|coverage\|sampling"

# 10e. Confirm hardware_configuration table does not already exist under
#      a different name
sqlite3 "$DB" "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%config%';"
```

---

## 11. Open items, explicitly deferred (do not start without separate sign-off)

1. **Sensor characterization pass** — running a known/calibrated load
   against each of the 6 new rails to populate real confidence values.
   Required before any paper claim, not required to start
   implementation.
2. **`dc_input` vendor documentation check** — required before any
   paper wording per Section 7b. Not required to start implementation.
3. **Coverage threshold policy** — exact `spbm_coverage_pct` cutoff for
   flagging a run as integration-unreliable. Suggested 95%, not final.
4. **Trapezoidal vs rectangular integration decision** — implementation
   detail, deferred to coding time per Section 5.
5. **`hardware_configuration` table generalization** — this spec adds
   only PL1/PL2/SYSPL1/SYSPL2 rows. Governor, boost-enable, thermal
   mode, and power profile tracking are real future uses of this table
   but are out of scope here.

---

## 12. Scope boundary

### In scope
- 6 new power rails sampled, integrated, stored
- energy_domains schema extension (6 new rows)
- New hardware_configuration table, PL1/PL2/SYSPL1/SYSPL2 populated
- Sampling quality columns on runs
- Two new derived metrics (conversion_loss_uj, conversion_efficiency)
- One parameterized methodology entry plus two derived-metric entries
- GN100 only

### Out of scope (explicitly deferred)
- Sensor characterization / real confidence values (Section 11.1)
- Paper-text claims about dc_input's physical meaning (Section 11.2)
- Any cross-platform abstraction (UBUNTU2505, AMD, Apple have no
  equivalent rail exposure)
- goal_attempt / goal_execution propagation
- hardware_configuration generalization beyond power limits
- Migration system M3/M4
- COMPLIANCE.md updates
