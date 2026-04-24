# Goal Execution and Overhead Fraction Methodology

## Overview

`goal_execution` is the paper's fundamental unit of analysis. A goal represents one user intent that may require multiple measurement attempts to complete. Energy is measured per successful goal — not per run — because retries and failures consume real energy that must be accounted for in the total cost of agentic orchestration.

---

## Method: `goal_execution_rollup_v1`

**Provenance:** CALCULATED
**Confidence:** 1.0
**Layer:** orchestration

### Definition

A goal rollup aggregates all attempt energies into a single goal-level energy figure. Three values are computed:

**Total energy** — sum of energy across all attempts regardless of outcome:

$$E_{total} = \sum_{i=1}^{N} E_{attempt_i}$$

**Successful energy** — energy of the winning attempt only:

$$E_{success} = E_{attempt_{winning}}$$

**Overhead energy** — wasted energy from failed attempts:

$$E_{overhead} = E_{total} - E_{success}$$

### Column Ownership

| Column | Formula | Populated By |
|---|---|---|
| `total_energy_uj` | $\sum E_{attempt_i}$ | `chunk8_goal_etl.py` |
| `successful_energy_uj` | $E_{attempt_{winning}}$ | `chunk8_goal_etl.py` |
| `overhead_energy_uj` | $E_{total} - E_{success}$ | `chunk8_goal_etl.py` |

All three columns insert as NULL at run time and are populated asynchronously after all attempts complete.

### NULL Semantics

- NULL = ETL has not yet run for this goal
- 0 = ETL ran and computed zero (e.g. single successful attempt with zero overhead)

---

## Method: `goal_overhead_fraction_v1`

**Provenance:** CALCULATED
**Confidence:** 1.0
**Layer:** orchestration

### Definition

Two fractions characterise the energy efficiency of a goal execution:

**Overhead fraction** — proportion of total energy wasted on failed attempts:

$$f_{overhead} = \frac{E_{overhead}}{E_{total}} = \frac{E_{total} - E_{success}}{E_{total}}$$

**Orchestration fraction** — proportion of winning run energy spent on orchestration (planning, routing, tool calls) rather than direct LLM compute:

$$f_{orchestration} = \frac{E_{orchestration}}{E_{success}}$$

where $E_{orchestration}$ is sourced from `energy_attribution.orchestration_energy_uj` of the `winning_run_id`.

### Paper Significance

These two fractions are the headline metrics of the paper thesis:

> *Orchestration structure — not active compute — is the dominant driver of energy in agentic AI workloads.*

A high $f_{orchestration}$ across workflow types and goal types is the primary empirical evidence for this claim.

### Confound Control

`difficulty_level` on `goal_execution` controls for task difficulty when comparing $f_{orchestration}$ across workflow types. Without this control, reviewers may argue that agentic workflows use harder tasks, inflating apparent orchestration overhead.

### Column Ownership

| Column | Formula | Populated By |
|---|---|---|
| `overhead_fraction` | $E_{overhead} / E_{total}$ | `chunk8_goal_etl.py` |
| `orchestration_fraction` | $E_{orchestration} / E_{success}$ | `chunk8_goal_etl.py` |

---

## Core Paper Query

```sql
SELECT
    e.workflow_type,
    AVG(ge.overhead_fraction)        AS avg_overhead_fraction,
    AVG(ge.orchestration_fraction)   AS avg_orchestration_fraction,
    AVG(ge.successful_energy_uj)/1e6 AS avg_energy_per_goal_j,
    COUNT(*)                         AS total_goals,
    SUM(CASE WHEN ge.success=1 THEN 1 ELSE 0 END) AS successful_goals
FROM goal_execution ge
JOIN experiments e ON ge.exp_id = e.exp_id
WHERE e.experiment_type IN (
    'normal','overhead_study','retry_study',
    'failure_injection','quality_sweep','ablation','pilot'
)
GROUP BY e.workflow_type;
```

Note: `workflow_type` sourced from `experiments` via join — `goal_execution.workflow_type` is used for per-goal filtering, not grouping.
