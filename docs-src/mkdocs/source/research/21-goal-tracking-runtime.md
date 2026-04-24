# Goal Tracking Runtime

## Overview

Goal tracking wires the `goal_execution` and `goal_attempt` tables to the live
experiment runner. Every call to `save_pair()` or `save_single()` now produces
exactly one `goal_execution` row per workflow side and one `goal_attempt` row
per run.

## Why Goals, Not Runs

The paper's unit of analysis is a *goal* — a task attempted by the system,
possibly across multiple runs if retries occur. A single goal may span several
runs. Energy columns on `goal_execution` aggregate across all attempts, making
`overhead_fraction` and `orchestration_fraction` meaningful at the task level
rather than the hardware-measurement level.

## Lifecycle

```
experiment_runner.save_pair()
    → _record_goal_pair(workflow_type='linear')
        → GoalTracker.start_goal()      INSERT goal_execution status='running'
        → GoalTracker.start_attempt()   INSERT goal_attempt   status='running'
        → GoalTracker.finish_attempt()  UPDATE goal_attempt   status=terminal
        → GoalTracker.finish_goal()     UPDATE goal_execution status=solved|failed
    → _record_goal_pair(workflow_type='agentic')   [same sequence]
    → goal_execution_etl.process_one(linear_goal_id)
    → goal_execution_etl.process_one(agentic_goal_id)
    → energy_attribution_etl.populate_attribution_stubs(linear_run_id)
    → energy_attribution_etl.populate_attribution_stubs(agentic_run_id)
```

All steps are synchronous. No threads. No daemons.

## workflow_type Rules

`goal_execution.workflow_type` is always `'linear'` or `'agentic'`. Never
`'comparison'`. A comparison experiment produces two `goal_execution` rows —
one per side. The runner sets `workflow_type` explicitly; it is never derived
from the parent experiment.

## ETL Columns

The following columns are NULL at INSERT time and populated by ETL:

| Column | Set by | Formula |
|---|---|---|
| `total_energy_uj` | `goal_execution_etl` | SUM of all attempt energies |
| `successful_energy_uj` | `goal_execution_etl` | Winning attempt energy |
| `overhead_energy_uj` | `goal_execution_etl` | total − successful |
| `overhead_fraction` | `goal_execution_etl` | overhead / total |
| `orchestration_fraction` | `goal_execution_etl` | From `energy_attribution` of winning run |

## ETL Queue

After ETL runs, `GoalTracker.queue_etl()` records the completion in `etl_queue`.
This table-backed queue allows ETL reruns without rerunning experiments and
provides an audit trail of which ETL processed which entity.

## first_run_id Placeholder

At `start_goal()` time the run does not yet exist. `first_run_id = -1` is
inserted as a placeholder. `finish_goal()` resolves the minimum `run_id` across
all `goal_attempt` rows and updates `first_run_id` to the real value.

## Paper Core Query

After this module is wired, the following query returns results:

```sql
SELECT
    ge.workflow_type,
    AVG(ge.overhead_fraction)        AS avg_overhead_fraction,
    AVG(ge.orchestration_fraction)   AS avg_orchestration_fraction,
    AVG(ge.successful_energy_uj)/1e6 AS avg_energy_per_goal_j,
    COUNT(*)                         AS goals
FROM goal_execution ge
JOIN experiments e ON ge.exp_id = e.exp_id
WHERE e.experiment_type IN (
    'normal','overhead_study','retry_study',
    'failure_injection','quality_sweep','ablation'
)
GROUP BY ge.workflow_type;
```

## Provenance

| Column group | method_id | confidence |
|---|---|---|
| `ge.task_id`, `ge.status`, timestamps | `goal_tracking_runtime_v1` | 1.0 |
| `eq.*` (etl_queue columns) | `etl_queue_management_v1` | 1.0 |
