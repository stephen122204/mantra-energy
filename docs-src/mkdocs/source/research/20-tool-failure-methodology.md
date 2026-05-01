# Tool Failure and Energy Attribution Methodology

## Scope

This document covers energy attribution for failed tool calls and the ETL
pipeline that computes goal-level energy rollup. For failure injection design
see `22-retry-tool-failure-methodology.md`. For tool execution instrumentation
see `24-tool-instrumentation-methodology.md`.

---

## Tool Failure Wasted Energy
*method_id: `tool_failure_wasted_energy_v1` | confidence: 0.90*

### Definition

Energy consumed by a failed tool call from call initiation to failure detection.

Primary source: `orchestration_events.event_energy_uj` linked via
`tool_failure_events.orchestration_event_id`.
Fallback: inferred from attempt energy fraction when no orchestration event is linked.

### failure_phase Field

Records where in the orchestration pipeline the failure occurred:

| Phase | Meaning | Energy Signal |
|---|---|---|
| `selection` | Agent chose wrong tool | Planning energy wasted |
| `execution` | Tool call made but failed | Full execution energy wasted |
| `parsing` | Tool returned output but agent could not parse | Parsing overhead wasted |
| `post_processing` | Downstream processing failed | Integration energy wasted |

This field enables paper analysis: "which pipeline stage wastes the most energy?"

### Table Scope

`tool_failure_events` covers infrastructure failures only:
`timeout`, `api_error`, `rate_limit`, `context_overflow`, `tool_error`.

Quality failures go to separate tables:
- `output_quality` — normalized quality scores
- `hallucination_events` — hallucination classification

This separation keeps paper Figure 3 taxonomy clean: infrastructure waste
vs quality waste are distinct energy cost categories.

---

## Goal Execution ETL
*method_id: `goal_execution_rollup_v1` | confidence: 1.0*
*method_id: `goal_overhead_fraction_v1` | confidence: 1.0*

### Columns Computed

$$E_{total} = \sum_{k} E_{attempt_k}$$

$$E_{overhead} = E_{total} - E_{successful}$$

$$f_{overhead} = \frac{E_{overhead}}{E_{total}}$$

$$f_{orchestration} = \frac{E_{orchestration}}{E_{pkg}} \text{ (winning run only)}$$

For fully failed goals (no successful attempt): `overhead_fraction = 1.0`.

### Invariants

- Exactly one `is_winning = 1` per `goal_id`. Violation → skip, log error.
- `energy_attribution` must exist for `winning_run_id` before `orchestration_fraction`.
- `COUNT(DISTINCT goal_id)` for `normalization_factors.attempted_goals` — not `SUM`.

### Runs Architecture

`runs` = one row per workflow episode. `goal_attempt.energy_uj` holds per-attempt
snapshots. ETL sums `goal_attempt.energy_uj` for `goal_execution.total_energy_uj`.
Never recompute from `runs` — `runs.pkg_energy_uj` = terminal episode only.

---

## Attribution ETL
*method_id: `attribution_etl_v1` | confidence: 0.90*

### Five Stub Columns

| Column | Formula |
|---|---|
| `retry_energy_uj` | SUM of attempt energy where `attempt_number > 1` |
| `failed_tool_energy_uj` | SUM of `tool_failure_events.wasted_energy_uj` per run |
| `rejected_generation_energy_uj` | SUM of `hallucination_events.wasted_energy_uj_real` per run |
| `energy_per_accepted_answer_uj` | `pkg_energy / COUNT(accepted answers)` |
| `energy_per_solved_task_uj` | `SUM(successful_energy) / COUNT(solved goals)` |

### Accepted Answer Threshold

Accepted when `normalized_score >= 0.7` and `score_method != 'needs_review'`.
`ACCEPTANCE_THRESHOLD = 0.7` — tied to `output_quality_normalization_v1`.
Override by creating `attribution_etl_v2` with new threshold.

### ETL Chain Order

Phase attribution must run before energy attribution:
```
phase_attribution_etl → event_energy_uj per orchestration_event
energy_attribution_etl → reads event_energy_uj for tool_failure wasted energy
goal_execution_etl → reads energy_attribution for overhead_fraction
```
Running out of order produces NULL columns in downstream tables.

### ETL Invariant

`energy_attribution` row must exist for `run_id` before population.
Missing → log warning, skip, continue. Never silently propagate NULL.

---

## Research Views

### v_goal_energy_decomposition
Primary paper view — energy breakdown per goal by workflow type.
- `ge.total_energy_uj` is authoritative ground truth (ETL-populated)
- Orchestration fraction from winning run only
- Positive inclusion filter on `experiment_type` — never exclusion
- `had_retry` flag for stratified analysis

### v_failure_energy_taxonomy
Energy wasted per failure type across hallucination and tool failure events.
- `failure_domain` separates reasoning vs execution failures
- `corrected_by_retry` derived inline — not stored

### v_quality_energy_frontier
Quality vs energy per goal — supports quality-energy tradeoff figure.
- Uses `ge.total_energy_uj` (total including retries), not single attempt
- Excludes `needs_review` scores

---

## Provenance Summary

| Column | Method | Type |
|---|---|---|
| `tfe.wasted_energy_uj` | `tool_failure_wasted_energy_v1` | CALCULATED |
| `ea.retry_energy_uj` | `attribution_etl_v1` | CALCULATED |
| `ea.failed_tool_energy_uj` | `attribution_etl_v1` | CALCULATED |
| `ea.rejected_generation_energy_uj` | `attribution_etl_v1` | CALCULATED |
| `ea.energy_per_accepted_answer_uj` | `attribution_etl_v1` | CALCULATED |
| `ea.energy_per_solved_task_uj` | `attribution_etl_v1` | CALCULATED |
| `ge.total_energy_uj` | `goal_execution_rollup_v1` | CALCULATED |
| `ge.overhead_fraction` | `goal_overhead_fraction_v1` | CALCULATED |
| `ge.orchestration_fraction` | `goal_overhead_fraction_v1` | CALCULATED |
