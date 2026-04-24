# Experiment Classification Methodology

## Overview

Experiment metadata columns classify each experiment by study intent (`experiment_type`) and optional free-text descriptors (`experiment_goal`, `experiment_notes`). These are administrative classification fields — no computation is performed.

## Method: `system_metadata_v1`

**Provenance:** SYSTEM
**Confidence:** 1.0
**Layer:** orchestration

### experiment_type

Describes *why* an experiment was run — the study intent. This is distinct from `workflow_type`, which describes the AI architecture under test.

| Value | Study Intent | Paper Role |
|---|---|---|
| `normal` | Standard benchmark run | Primary data |
| `overhead_study` | Measuring orchestration_fraction directly | Direct thesis proof |
| `retry_study` | Forced retries, measuring retry_energy_uj | Populates energy_attribution stub |
| `failure_injection` | Injected failures, measuring recovery cost | Populates failed_tool_energy_uj |
| `quality_sweep` | Varying difficulty vs quality-adjusted energy | Paper Figure 3 |
| `calibration` | Idle baseline measurement | Excluded from analysis |
| `ablation` | Component removal studies | Supplementary |
| `pilot` | Early feasibility runs | Excluded from main analysis |
| `debug` | Development only | Always excluded |

### Query Pattern

Always use positive inclusion filter — never exclude by negation:

```sql
WHERE experiment_type IN ('normal','overhead_study','retry_study',
                          'failure_injection','quality_sweep','ablation','pilot')
```

### experiment_goal

Free-text field describing what the experiment is measuring. Not used in queries — for human readability and audit trail only.

### experiment_notes

Free-text operational notes. Not used in queries — for human readability and audit trail only.

## Enforcement

A SQLite trigger (`trg_exp_type_insert`, `trg_exp_type_update`) enforces valid values at the DB layer. Application layer uses `VALID_EXPERIMENT_TYPES` constant in `core/database/schema.py` as single source of truth.
