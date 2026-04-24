# Tool Failure and Attribution ETL Methodology
*Chunk 8.4 | Schema Revision: 029–030*

---

## Overview

Chunk 8.4 completes the Chunk 8 research schema by adding:

- `tool_failure_events` — energy cost of failed tool calls per attempt
- Three research views — aggregation layer for paper queries
- `goal_execution_etl.py` — goal-level energy rollup
- Extended `energy_attribution_etl.py` — populates 5 attribution stubs

---

## Tool Failure Wasted Energy Methodology
*method_id: `tool_failure_wasted_energy_v1` | confidence: 0.90*

### Definition

Energy consumed by a failed tool call from call initiation to failure detection.

Primary source: `orchestration_events.event_energy_uj` where `orchestration_event_id` is set.
Fallback: inferred from attempt energy fraction when no orchestration event is linked.

### `failure_phase` Field

Records where in the orchestration pipeline the failure occurred:

| Phase | Meaning |
|---|---|
| `selection` | Agent chose wrong tool for the task |
| `execution` | Tool call was made but failed during execution |
| `parsing` | Tool returned output but agent could not parse it |
| `post_processing` | Parsing succeeded but downstream processing failed |

This field enables future papers to answer: "which pipeline stage wastes the most energy?"

---

## Goal Execution ETL Methodology
*method_id: `goal_execution_rollup_v1` | confidence: 1.0*
*method_id: `goal_overhead_fraction_v1` | confidence: 1.0*

### Columns Computed

$$E_{total} = \sum_{k} E_{attempt_k}$$

$$E_{overhead} = E_{total} - E_{successful}$$

$$f_{overhead} = \frac{E_{overhead}}{E_{total}}$$

$$f_{orchestration} = \frac{E_{orchestration}}{E_{pkg}} \text{ (from winning run only)}$$

### Invariants

- Exactly one `is_winning = 1` per `goal_id` in `goal_attempt`. Violation → skip goal, log error.
- `energy_attribution` row must exist for `winning_run_id` before `orchestration_fraction` can be set.
- `COUNT(DISTINCT goal_id)` used for `normalization_factors.attempted_goals` — not `SUM(total_attempts)`.

---

## Attribution ETL Methodology
*method_id: `attribution_etl_v1` | confidence: 0.90*

### Five Stub Columns Populated

| Column | Formula |
|---|---|
| `retry_energy_uj` | SUM of attempt energy where attempt_number > 1 |
| `failed_tool_energy_uj` | SUM of tool_failure_events.wasted_energy_uj per run |
| `rejected_generation_energy_uj` | SUM of hallucination_events.wasted_energy_uj_real per run |
| `energy_per_accepted_answer_uj` | pkg_energy / COUNT(accepted answers) |
| `energy_per_solved_task_uj` | SUM(successful_energy) / COUNT(solved goals) |

### Accepted Answer Threshold

An answer is "accepted" when `normalized_score >= 0.7` and `score_method != 'needs_review'`.

Threshold value: **0.7** — documented as `ACCEPTANCE_THRESHOLD` in `energy_attribution_etl.py`, tied to `output_quality_normalization_v1`.

Different domains may require different thresholds. Override by creating `attribution_etl_v2` with the new threshold and registering a new `method_id`.

### ETL Invariant

`energy_attribution` row must exist for `run_id` before any stub can be populated. Missing row → log warning, skip run, continue. Never silently propagate NULL.

---

## Research Views

### v_goal_energy_decomposition
Primary paper view. Energy breakdown per goal by workflow type.
- `ge.total_energy_uj` is authoritative ground truth (ETL-populated, not recomputed in view)
- Orchestration fraction from winning run only (rate metric, not summed)
- Positive inclusion filter on `experiment_type`
- `had_retry` flag for stratified analysis

### v_failure_energy_taxonomy
Energy wasted per failure type, unified across hallucination and tool failure events.
- `failure_domain` separates reasoning failures (`hallucination`) from execution failures (`tool_failure`)
- Required for cross-category paper comparisons
- `corrected_by_retry` derived inline from `goal_attempt` — not stored

### v_quality_energy_frontier
Quality vs energy per goal. Supports quality-energy tradeoff figure.
- Uses `ge.total_energy_uj` (total goal cost including retries) not `ga.energy_uj` (single attempt)
- Excludes `needs_review` scores
- `energy_per_quality_point_uj` = total_energy / normalized_score

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
