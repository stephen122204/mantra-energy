# Provenance & Methodology Tables — Research Value Guide

This document explains the four provenance tables in A-LEMS, what research
questions they answer, and provides exact SQL queries for each use case.

A-LEMS is designed as a **world-class research platform** where every
measurement is auditable, every formula is verifiable, and every result
can be traced back to its hardware source.

---

## The Four Tables

### Table 1: `measurement_method_registry`

**Who writes it**: `seed_methodology.py` — once at deploy time.
**What it contains**: Static definition of HOW each measurement method works.
**Rows**: ~22 rows (one per method, never per run).

```
id                    TEXT  PRIMARY KEY   e.g. 'rapl_msr_pkg_energy'
name                  TEXT               Human-readable name
description           TEXT               PhD-quality prose methodology
formula_latex         TEXT               KaTeX formula for UI rendering
code_snapshot         TEXT               Actual Python implementation
parameters            TEXT  JSON         Default parameters
provenance            TEXT               MEASURED/CALCULATED/INFERRED/LIMITED
layer                 TEXT               silicon/os/application/orchestration
fallback_method_id    TEXT  FK           What to use if this method fails
```

**Research value**: Reviewer asks "How did you measure package energy?" →
one query returns the formula, the code, and the prose explanation.

---

### Table 2: `method_references`

**Who writes it**: `seed_methodology.py` — from `config/methodology_refs/*.yaml`.
**What it contains**: Academic citations justifying each method.
**Rows**: ~60 rows (3 citations per method on average).

```
method_id       TEXT  FK → measurement_method_registry.id
ref_type        TEXT  'paper'/'datasheet'/'standard'/'manual'
title           TEXT  Full paper title
authors         TEXT  Author list
year            INTEGER
doi             TEXT  DOI for permanent reference
relevance       TEXT  Why this paper justifies this method
cited_text      TEXT  Key sentence from the paper
```

**Research value**: Reviewer asks "What paper justifies your 2-sigma
baseline?" → one query returns Sangha 2025 with exact cited sentence.

---

### Table 3: `measurement_methodology`

**Who writes it**: `record_run_provenance()` — once per metric per run.
**What it contains**: Runtime record of WHAT VALUE each metric had THIS run.
**Rows**: ~85 rows per run × N runs (scales with experiments).

```
run_id            INTEGER  FK → runs.run_id
metric_id         TEXT     Column name e.g. 'pkg_energy_uj'
method_id         TEXT  FK → measurement_method_registry.id
value_raw         REAL     Actual value measured this run
value_unit        TEXT     'µJ', 'ms', '°C' etc.
provenance        TEXT     MEASURED/CALCULATED/INFERRED
confidence        REAL     0.0-1.0
parameters_used   TEXT  JSON  Actual inputs used for this calculation
captured_at       REAL     Unix timestamp
```

**Research value**: For any run, any metric — you can show exactly what
value was measured, how confident you are, and what inputs produced it.

---

### Table 4: `metric_display_registry`

**Who writes it**: `migrate_yaml_to_db.py` — from YAML config + runs table.
**What it contains**: How to display each metric in the UI.
**Rows**: 90+ rows (one per displayable metric).

```
id                TEXT  PRIMARY KEY  Metric name
label             TEXT               Human-readable label
category          TEXT               energy/performance/thermal/etc.
layer             TEXT               silicon/os/application
unit_default      TEXT               µJ/ms/°C etc.
method_id         TEXT  FK           Links to method registry
formula_latex     TEXT               KaTeX formula (from method registry)
color_token       TEXT               UI theme color
direction         TEXT               lower_is_better/higher_is_better
```

**Research value**: UI renders formula tooltips and drilldown panels
by JOINing this table with `measurement_method_registry`.

---

## Research Questions — Exact Queries

### Q1: How was dynamic_energy_uj calculated for run 1833?

```sql
SELECT
    mm.value_raw                    AS value_uj,
    mm.provenance,
    mm.confidence,
    mm.parameters_used,
    mmr.formula_latex,
    mmr.description,
    mmr.code_snapshot
FROM measurement_methodology mm
JOIN measurement_method_registry mmr ON mm.method_id = mmr.id
WHERE mm.run_id    = 1833
  AND mm.metric_id = 'dynamic_energy_uj';
```

**Returns**: Value, formula `E_dyn = max(0, E_pkg - E_idle)`, full prose
description, and the actual Python code that implements it.

---

### Q2: Why is pkg_energy_uj MEASURED but carbon_g INFERRED?

```sql
SELECT
    metric_id,
    provenance,
    confidence,
    method_id
FROM measurement_methodology
WHERE run_id    = 1833
  AND metric_id IN (
      'pkg_energy_uj',
      'dynamic_energy_uj',
      'ipc',
      'carbon_g',
      'water_ml'
  )
ORDER BY provenance, metric_id;
```

**Returns**:
```
pkg_energy_uj    MEASURED    1.0   rapl_msr_pkg_energy
dynamic_energy_uj CALCULATED  1.0   dynamic_energy_calculation
ipc              CALCULATED  1.0   ipc_calculation
carbon_g         INFERRED    0.7   carbon_calculation
water_ml         INFERRED    0.7   water_calculation
```

`pkg_energy_uj` is MEASURED because it comes directly from hardware MSR.
`carbon_g` is INFERRED because it uses an external grid intensity constant
(Ember 2026) that is not measured by A-LEMS hardware.

---

### Q3: What baseline method was used? Did you use CPU pinning?

```sql
SELECT
    mm.metric_id,
    mm.parameters_used,
    mmr.name            AS method_name,
    mmr.formula_latex,
    mmr.description
FROM measurement_methodology mm
JOIN measurement_method_registry mmr ON mm.method_id = mmr.id
WHERE mm.run_id    = 1833
  AND mm.metric_id = 'baseline_energy_uj';
```

**Returns**: `parameters_used` contains:
```json
{
    "pinned_cores":    [0, 1],
    "duration_seconds": 10,
    "num_samples":      10,
    "sigma_threshold":  2.0
}
```

Formula: $E_{idle} = \max(0, \bar{P} - 2\sigma) \times t_{duration}$

---

### Q4: Show me the actual code that calculates IPC

```sql
SELECT
    mmr.name,
    mmr.formula_latex,
    mmr.code_snapshot
FROM measurement_method_registry mmr
WHERE mmr.id = 'ipc_calculation';
```

**Returns**: Formula `IPC = N_instructions / N_cycles` plus the actual
Python function that computes it — reviewer can verify formula matches code.

---

### Q5: What papers justify the RAPL measurement method?

```sql
SELECT
    mr.ref_type,
    mr.title,
    mr.authors,
    mr.year,
    mr.doi,
    mr.relevance,
    mr.cited_text
FROM method_references mr
WHERE mr.method_id = 'rapl_msr_pkg_energy'
ORDER BY mr.year DESC;
```

**Returns**:
```
datasheet | Intel 64 and IA-32 SDM | Intel | 2023 | ...
          | Vol 3B Section 14.9 RAPL MSR registers
          | "MSR_PKG_ENERGY_STATUS 0x611 accumulates energy"

paper     | A-LEMS Measurement Platform | Sangha 2025 | ...
          | Section 3.2 RAPL direct measurement at 100Hz
          | "Package energy sampled at 100Hz via MSR 0x611"
```

---

### Q6: What is the confidence level of each metric in run 1833?

```sql
SELECT
    mm.metric_id,
    mm.provenance,
    mm.confidence,
    mmr.name AS method_name
FROM measurement_methodology mm
JOIN measurement_method_registry mmr ON mm.method_id = mmr.id
WHERE mm.run_id = 1833
ORDER BY mm.confidence ASC, mm.provenance;
```

**Returns**: Shows carbon_g and water_ml at 0.7 (external constants),
all hardware measurements at 1.0. Researcher can filter by confidence
threshold for analysis.

---

### Q7: Full forensic audit for run 1833 — every metric

```sql
SELECT
    mm.metric_id,
    mm.value_raw,
    mm.value_unit,
    mm.provenance,
    mm.confidence,
    mm.parameters_used,
    mmr.name            AS method_name,
    mmr.formula_latex,
    mmr.layer,
    COALESCE(mdr.label, mm.metric_id) AS display_label,
    COALESCE(mdr.category, mmr.layer) AS category
FROM measurement_methodology mm
JOIN measurement_method_registry mmr ON mm.method_id = mmr.id
LEFT JOIN metric_display_registry mdr ON mm.metric_id = mdr.id
WHERE mm.run_id = 1833
ORDER BY mmr.layer, mm.metric_id;
```

**Returns**: All ~85 metrics with values, formulas, method names,
and display labels. Complete forensic audit in one query.

---

### Q8: Compare confidence across two runs (different machines)

```sql
SELECT
    a.metric_id,
    a.value_raw          AS value_x86,
    a.confidence         AS confidence_x86,
    a.provenance         AS provenance_x86,
    b.value_raw          AS value_arm,
    b.confidence         AS confidence_arm,
    b.provenance         AS provenance_arm
FROM measurement_methodology a
JOIN measurement_methodology b
    ON  a.metric_id = b.metric_id
WHERE a.run_id = 1833   -- x86 bare metal run
  AND b.run_id = 1834   -- ARM VM run
  AND a.metric_id IN (
      'pkg_energy_uj', 'dynamic_energy_uj', 'carbon_g'
  );
```

**Returns**: Side-by-side comparison showing x86 at confidence=1.0
(RAPL) vs ARM at confidence=0.0 (stub estimator). Researcher knows
to exclude ARM energy data from analysis.

---

### Q9: Which runs have low-confidence energy measurements?

```sql
SELECT
    mm.run_id,
    mm.metric_id,
    mm.confidence,
    mm.provenance,
    r.workflow_type,
    r.experiment_valid
FROM measurement_methodology mm
JOIN runs r ON mm.run_id = r.run_id
WHERE mm.metric_id  = 'pkg_energy_uj'
  AND mm.confidence < 1.0
ORDER BY mm.confidence ASC;
```

**Returns**: All runs where energy measurement is not fully trusted —
ARM VMs (confidence=0.0), IOKit stubs (confidence=0.5). Researcher
can automatically exclude these from thesis analysis.

---

### Q10: Network researcher — how was bytes_sent measured?

```sql
SELECT
    mm.value_raw,
    mm.value_unit,
    mm.provenance,
    mmr.formula_latex,
    mmr.description,
    mmr.code_snapshot,
    mmr.parameters
FROM measurement_methodology mm
JOIN measurement_method_registry mmr ON mm.method_id = mmr.id
WHERE mm.run_id    = 1833
  AND mm.metric_id = 'bytes_sent';
```

**Returns**: Value in bytes, formula `ΔB = B_end - B_start`,
description of psutil.net_io_counters() interface, actual code,
and parameters `{"source": "psutil.net_io_counters()"}`.

---

### Q11: Thermal researcher — what caused thermal throttling?

```sql
SELECT
    mm.metric_id,
    mm.value_raw,
    mm.provenance,
    mm.parameters_used
FROM measurement_methodology mm
WHERE mm.run_id    = 1833
  AND mm.metric_id IN (
      'package_temp_celsius',
      'max_temp_c',
      'thermal_delta_c',
      'thermal_during_experiment',
      'thermal_throttle_flag',
      'c6_time_seconds',
      'c7_time_seconds'
  )
ORDER BY mm.metric_id;
```

**Returns**: Complete thermal picture — peak temperature, delta,
throttling flags, and C-state residency showing how CPU responded.

---

### Q12: Memory researcher — memory pressure during experiment

```sql
SELECT
    mm.metric_id,
    mm.value_raw,
    mm.value_unit,
    mmr.formula_latex,
    mm.parameters_used
FROM measurement_methodology mm
JOIN measurement_method_registry mmr ON mm.method_id = mmr.id
WHERE mm.run_id    = 1833
  AND mm.metric_id IN (
      'rss_memory_mb',
      'vms_memory_mb',
      'swap_end_used_mb',
      'swap_end_percent',
      'cache_miss_rate'
  );
```

---

## Regression Test Suite

Run after every code change to verify provenance integrity:

```bash
#!/bin/bash
# scripts/test_provenance.sh

DB="data/experiments.db"
RUN_ID=$(sqlite3 $DB "SELECT MAX(run_id) FROM measurement_methodology;")

echo "Testing provenance for run_id=$RUN_ID"

# Test 1: Row count — should be ~85 per run
COUNT=$(sqlite3 $DB "SELECT COUNT(*) FROM measurement_methodology WHERE run_id=$RUN_ID;")
echo "T1 Row count: $COUNT (expected ~85)"
[ "$COUNT" -gt 60 ] && echo "✅ PASS" || echo "❌ FAIL"

# Test 2: No NULL method_ids
NULL_COUNT=$(sqlite3 $DB "
    SELECT COUNT(*) FROM measurement_methodology
    WHERE run_id=$RUN_ID AND method_id IS NULL;")
echo "T2 NULL method_ids: $NULL_COUNT (expected 0)"
[ "$NULL_COUNT" -eq 0 ] && echo "✅ PASS" || echo "❌ FAIL"

# Test 3: Key metrics present
for metric in pkg_energy_uj ipc carbon_g api_latency_ms; do
    EXISTS=$(sqlite3 $DB "
        SELECT COUNT(*) FROM measurement_methodology
        WHERE run_id=$RUN_ID AND metric_id='$metric';")
    [ "$EXISTS" -gt 0 ] && echo "✅ $metric present" || echo "❌ $metric MISSING"
done

# Test 4: JOIN works — formula available for all rows
NO_FORMULA=$(sqlite3 $DB "
    SELECT COUNT(*) FROM measurement_methodology mm
    JOIN measurement_method_registry mmr ON mm.method_id = mmr.id
    WHERE mm.run_id=$RUN_ID
    AND (mmr.formula_latex IS NULL OR mmr.formula_latex = '');")
echo "T4 Missing formulas: $NO_FORMULA (expected 0)"
[ "$NO_FORMULA" -eq 0 ] && echo "✅ PASS" || echo "❌ FAIL"

# Test 5: INFERRED metrics have confidence < 1.0
INFERRED_CONF=$(sqlite3 $DB "
    SELECT COUNT(*) FROM measurement_methodology
    WHERE run_id=$RUN_ID
    AND provenance='INFERRED'
    AND confidence >= 1.0;")
echo "T5 INFERRED with confidence=1.0: $INFERRED_CONF (expected 0)"
[ "$INFERRED_CONF" -eq 0 ] && echo "✅ PASS" || echo "❌ FAIL"

# Test 6: Method registry completeness — 22 methods
METHOD_COUNT=$(sqlite3 $DB "SELECT COUNT(*) FROM measurement_method_registry;")
echo "T6 Method registry rows: $METHOD_COUNT (expected 22)"
[ "$METHOD_COUNT" -ge 22 ] && echo "✅ PASS" || echo "❌ FAIL"

# Test 7: References present
REF_COUNT=$(sqlite3 $DB "SELECT COUNT(*) FROM method_references;")
echo "T7 Reference rows: $REF_COUNT (expected >4)"
[ "$REF_COUNT" -gt 4 ] && echo "✅ PASS" || echo "❌ FAIL"

echo ""
echo "Provenance regression complete."
```

---

## Design Principles

### Why These Four Tables?

```
Two static tables (seeded once):
    measurement_method_registry  — WHAT the method is
    method_references            — WHO said it's valid

Two dynamic tables (written per run):
    measurement_methodology      — WHAT happened this run
    metric_display_registry      — HOW to show it in UI
```

### Single Source of Truth

```
formula_latex lives in measurement_method_registry ONLY
    → metric_display_registry reads it via JOIN
    → UI renders it via KaTeX
    → Never duplicated, never drifts

code_snapshot extracted live from .py files at seed time
    → Formula decorator @formula proves code matches formula
    → PhD reviewer can audit formula = implementation

description extracted from dedicated .md docs (07, 08, 09)
    → Stable headings, never broken by general doc edits
    → mkdocs serves same docs to users
```

### Scalability

```
New measurement method added:
    1. Create reader class with METHOD_* attributes
    2. Add @formula decorator on compute function
    3. Add entry to config/methodology_docs.yaml
    4. python scripts/seed_methodology.py
    → Automatically appears in all 4 tables

New runs table column added:
    1. Add ONE line to COLUMN_PROVENANCE in provenance.py
    2. Add ONE line to METHOD_CONFIDENCE
    → Next run automatically gets provenance row
    → UI automatically shows it in deep dive
```

---

## For PhD Thesis Writers

The provenance tables directly support thesis methodology sections:

**"Section 3.1 — Energy Measurement"**
→ Query `measurement_method_registry` for `rapl_msr_pkg_energy`
→ Use `description` as basis for methodology prose
→ Use `formula_latex` in equations section
→ Use `method_references` for citations

**"Section 3.2 — Baseline Methodology"**  
→ Query `idle_baseline_cpu_pinning_2sigma`
→ `parameters` field documents: pinned_cores, duration, sigma_threshold
→ Reproducible — any researcher can replicate exactly

**"Section 4 — Results Validity"**
→ Query confidence scores across all runs
→ Exclude runs where `confidence < 1.0` for energy metrics
→ Document exclusion criteria with provenance evidence

**"Appendix A — Measurement Reproducibility"**
→ Export full `measurement_methodology` table for supplementary materials
→ Every value traceable to hardware interface
→ Meets open science reproducibility standards

---

## Additional Research Questions — Advanced Queries

### Q13: Which runs should be excluded from energy analysis?

```sql
-- Runs with low-confidence energy OR noisy environment
SELECT
    r.run_id,
    r.workflow_type,
    r.experiment_valid,
    mm.confidence         AS energy_confidence,
    mm.provenance         AS energy_provenance,
    r.background_cpu_percent,
    r.context_switches_involuntary
FROM runs r
JOIN measurement_methodology mm
    ON  r.run_id    = mm.run_id
    AND mm.metric_id = 'pkg_energy_uj'
WHERE mm.confidence < 1.0
   OR r.experiment_valid = 0
   OR r.background_cpu_percent > 10
ORDER BY mm.confidence ASC, r.run_id DESC;
```

**Research value**: Automated exclusion criteria backed by measurement
confidence data — not subjective manual filtering.

---

### Q14: Compare energy efficiency across LLM providers

```sql
SELECT
    r.workflow_type,
    AVG(mm_energy.value_raw)   AS avg_pkg_energy_uj,
    AVG(mm_token.value_raw)    AS avg_total_tokens,
    AVG(mm_energy.value_raw / NULLIF(mm_token.value_raw, 0))
                               AS avg_energy_per_token_uj,
    AVG(mm_energy.confidence)  AS measurement_confidence,
    COUNT(*)                   AS run_count
FROM runs r
JOIN measurement_methodology mm_energy
    ON  r.run_id    = mm_energy.run_id
    AND mm_energy.metric_id = 'pkg_energy_uj'
JOIN measurement_methodology mm_token
    ON  r.run_id    = mm_token.run_id
    AND mm_token.metric_id = 'total_tokens'
WHERE r.experiment_valid = 1
  AND mm_energy.confidence = 1.0
GROUP BY r.workflow_type
ORDER BY avg_energy_per_token_uj ASC;
```

**Research value**: Fair comparison using only MEASURED confidence=1.0
energy data — INFERRED ARM runs automatically excluded.

---

### Q15: What is the orchestration tax distribution?

```sql
SELECT
    mm_tax.value_raw          AS orchestration_tax_uj,
    mm_pkg.value_raw          AS pkg_energy_uj,
    ROUND(mm_tax.value_raw * 100.0 /
        NULLIF(mm_pkg.value_raw, 0), 2) AS tax_percent,
    mm_complexity.value_raw   AS complexity_score,
    r.llm_calls,
    r.tool_calls
FROM runs r
JOIN measurement_methodology mm_tax
    ON  r.run_id    = mm_tax.run_id
    AND mm_tax.metric_id = 'orchestration_tax_uj'
JOIN measurement_methodology mm_pkg
    ON  r.run_id    = mm_pkg.run_id
    AND mm_pkg.metric_id = 'pkg_energy_uj'
JOIN measurement_methodology mm_complexity
    ON  r.run_id    = mm_complexity.run_id
    AND mm_complexity.metric_id = 'complexity_score'
WHERE r.workflow_type   = 'agentic'
  AND r.experiment_valid = 1
ORDER BY tax_percent DESC;
```

---

### Q16: Carbon footprint trend over time

```sql
SELECT
    DATE(r.start_time_ns / 1e9, 'unixepoch') AS experiment_date,
    SUM(mm.value_raw)   AS total_carbon_g,
    COUNT(*)            AS runs,
    AVG(mm.confidence)  AS avg_confidence,
    -- Show the grid intensity used (from parameters_used JSON)
    json_extract(mm.parameters_used, '$.grid_intensity') AS grid_intensity
FROM runs r
JOIN measurement_methodology mm
    ON  r.run_id    = mm.run_id
    AND mm.metric_id = 'carbon_g'
WHERE r.experiment_valid = 1
GROUP BY experiment_date
ORDER BY experiment_date;
```

**Research value**: Carbon accounting with provenance — shows which
grid intensity constant was used each day, enabling reproducibility
when grid intensity changes between experiment batches.

---

### Q17: Method reliability — how often does primary method fail?

```sql
SELECT
    method_id,
    COUNT(*)                                    AS total_uses,
    SUM(primary_method_failed)                  AS failures,
    ROUND(AVG(confidence), 3)                   AS avg_confidence,
    ROUND(SUM(primary_method_failed) * 100.0
        / COUNT(*), 2)                          AS failure_rate_pct
FROM measurement_methodology
GROUP BY method_id
ORDER BY failure_rate_pct DESC;
```

**Research value**: Identifies unreliable measurement methods.
High failure rate → method needs improvement before publication.

---

### Q18: Full reproducibility export for one experiment

```sql
-- Export everything needed to reproduce one experiment
SELECT
    e.experiment_id,
    e.task_id,
    r.run_id,
    r.workflow_type,
    mm.metric_id,
    mm.value_raw,
    mm.value_unit,
    mm.provenance,
    mm.confidence,
    mm.parameters_used,
    mmr.formula_latex,
    mmr.name         AS method_name,
    mr.title         AS reference_title,
    mr.doi           AS reference_doi,
    mr.cited_text    AS reference_cited
FROM experiments e
JOIN runs r          ON r.exp_id     = e.exp_id
JOIN measurement_methodology mm
                     ON mm.run_id    = r.run_id
JOIN measurement_method_registry mmr
                     ON mmr.id       = mm.method_id
LEFT JOIN method_references mr
                     ON mr.method_id = mmr.id
WHERE e.experiment_id = :experiment_id
ORDER BY r.run_id, mm.metric_id, mr.year DESC;
```

**Research value**: Single query exports complete methodology audit
for supplementary materials — meets open science reproducibility standards.

---

### Q19: Scheduler noise analysis

```sql
SELECT
    r.run_id,
    r.workflow_type,
    mm_inv.value_raw          AS involuntary_switches,
    mm_mig.value_raw          AS thread_migrations,
    mm_bg.value_raw           AS background_cpu_pct,
    mm_rq.value_raw           AS run_queue_length,
    mm_pkg.value_raw          AS pkg_energy_uj,
    -- Flag runs with high scheduler noise
    CASE WHEN mm_inv.value_raw > 100
          OR mm_bg.value_raw > 5
         THEN 'NOISY' ELSE 'CLEAN' END AS noise_level
FROM runs r
JOIN measurement_methodology mm_inv
    ON r.run_id = mm_inv.run_id AND mm_inv.metric_id = 'context_switches_involuntary'
JOIN measurement_methodology mm_mig
    ON r.run_id = mm_mig.run_id AND mm_mig.metric_id = 'thread_migrations'
JOIN measurement_methodology mm_bg
    ON r.run_id = mm_bg.run_id AND mm_bg.metric_id = 'background_cpu_percent'
JOIN measurement_methodology mm_rq
    ON r.run_id = mm_rq.run_id AND mm_rq.metric_id = 'run_queue_length'
JOIN measurement_methodology mm_pkg
    ON r.run_id = mm_pkg.run_id AND mm_pkg.metric_id = 'pkg_energy_uj'
WHERE r.experiment_valid = 1
ORDER BY mm_inv.value_raw DESC;
```

**Research value**: Identifies runs contaminated by OS scheduler
interference — critical for PhD thesis validity claims.

---

### Q20: Thermal throttling impact on energy

```sql
SELECT
    r.run_id,
    mm_throttle.value_raw     AS throttled,
    mm_temp.value_raw         AS max_temp_c,
    mm_delta.value_raw        AS thermal_delta_c,
    mm_c6.value_raw           AS c6_time_seconds,
    mm_pkg.value_raw          AS pkg_energy_uj,
    mm_ipc.value_raw          AS ipc
FROM runs r
JOIN measurement_methodology mm_throttle
    ON r.run_id = mm_throttle.run_id
    AND mm_throttle.metric_id = 'thermal_during_experiment'
JOIN measurement_methodology mm_temp
    ON r.run_id = mm_temp.run_id AND mm_temp.metric_id = 'max_temp_c'
JOIN measurement_methodology mm_delta
    ON r.run_id = mm_delta.run_id AND mm_delta.metric_id = 'thermal_delta_c'
JOIN measurement_methodology mm_c6
    ON r.run_id = mm_c6.run_id AND mm_c6.metric_id = 'c6_time_seconds'
JOIN measurement_methodology mm_pkg
    ON r.run_id = mm_pkg.run_id AND mm_pkg.metric_id = 'pkg_energy_uj'
JOIN measurement_methodology mm_ipc
    ON r.run_id = mm_ipc.run_id AND mm_ipc.metric_id = 'ipc'
WHERE r.experiment_valid = 1
ORDER BY mm_throttle.value_raw DESC, mm_temp.value_raw DESC;
```

**Research value**: Correlates thermal throttling with energy and
IPC measurements — allows thesis to address thermal effects on results.

---

### Q21: Memory pressure and cache miss correlation

```sql
SELECT
    r.run_id,
    mm_rss.value_raw          AS rss_mb,
    mm_swap.value_raw         AS swap_used_mb,
    mm_cache.value_raw        AS cache_miss_rate_pct,
    mm_ipc.value_raw          AS ipc,
    mm_energy.value_raw       AS pkg_energy_uj,
    -- High swap = memory pressure = likely energy inflation
    CASE WHEN mm_swap.value_raw > 1000
         THEN 'HIGH_PRESSURE' ELSE 'NORMAL' END AS memory_state
FROM runs r
JOIN measurement_methodology mm_rss
    ON r.run_id = mm_rss.run_id AND mm_rss.metric_id = 'rss_memory_mb'
JOIN measurement_methodology mm_swap
    ON r.run_id = mm_swap.run_id AND mm_swap.metric_id = 'swap_end_used_mb'
JOIN measurement_methodology mm_cache
    ON r.run_id = mm_cache.run_id AND mm_cache.metric_id = 'cache_miss_rate'
JOIN measurement_methodology mm_ipc
    ON r.run_id = mm_ipc.run_id AND mm_ipc.metric_id = 'ipc'
JOIN measurement_methodology mm_energy
    ON r.run_id = mm_energy.run_id AND mm_energy.metric_id = 'pkg_energy_uj'
WHERE r.experiment_valid = 1
ORDER BY mm_swap.value_raw DESC;
```

---

### Q22: Network overhead in cloud vs local LLM

```sql
SELECT
    r.workflow_type,
    mm_api.value_raw          AS api_latency_ms,
    mm_bytes.value_raw        AS bytes_sent,
    mm_recv.value_raw         AS bytes_recv,
    mm_tcp.value_raw          AS tcp_retransmits,
    mm_energy.value_raw       AS pkg_energy_uj,
    -- Network as fraction of total latency
    ROUND(mm_api.value_raw * 100.0 /
        NULLIF(r.duration_ns / 1e6, 0), 2) AS network_pct_of_duration
FROM runs r
JOIN measurement_methodology mm_api
    ON r.run_id = mm_api.run_id AND mm_api.metric_id = 'api_latency_ms'
JOIN measurement_methodology mm_bytes
    ON r.run_id = mm_bytes.run_id AND mm_bytes.metric_id = 'bytes_sent'
JOIN measurement_methodology mm_recv
    ON r.run_id = mm_recv.run_id AND mm_recv.metric_id = 'bytes_recv'
JOIN measurement_methodology mm_tcp
    ON r.run_id = mm_tcp.run_id AND mm_tcp.metric_id = 'tcp_retransmits'
JOIN measurement_methodology mm_energy
    ON r.run_id = mm_energy.run_id AND mm_energy.metric_id = 'pkg_energy_uj'
WHERE r.experiment_valid = 1
ORDER BY network_pct_of_duration DESC;
```

**Research value**: Separates network overhead from compute overhead —
critical for fair comparison between local and cloud LLM deployments.
