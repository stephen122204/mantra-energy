# Retry Study — Developer Design Guide

## Purpose

This document explains the architecture of retry execution in A-LEMS,
the design decisions made, and how to extend the retry system.
It lives in the developer guide because it documents implementation
decisions, not research methodology.

---

## Core Design Decision — Option A

One `goal_execution` row per task per workflow side.
One `goal_attempt` row per execution attempt (including retries).
Retry loop lives in `goal_execution_manager.execute_goal()`.

```
goal_execution (one row)
    ├── goal_attempt 1: outcome=timeout,    is_retry=0, failure_type=timeout
    ├── goal_attempt 2: outcome=api_error,  is_retry=1, failure_type=api_error
    └── goal_attempt 3: outcome=success,    is_retry=1, failure_type=NULL
```

**Why not one goal_execution per attempt?**
Energy accounting would be wrong. `overhead_fraction` would always be 0
because each "goal" would have only one attempt. The whole wasted-energy
signal would be lost.

**Why not store corrected_later as a column?**
Derivable via SQL join on goal_attempt. Storing it would create redundancy
and potential inconsistency.

---

## Data Flow — Retry Path

```
test_harness.py / run_experiment.py
    │
    ├── if max_retries > 0:
    │       execute_goal(workflow_type="linear", policy=aggressive)
    │           start_goal()
    │           for attempt in 1..max_retries+1:
    │               start_attempt(is_retry, retry_of_attempt_id)
    │               harness.run_linear()
    │               _insert_one_run() → run_id
    │               finish_attempt(run_id, outcome, failure_type)
    │               is_retryable()? → continue or break
    │           finish_goal(winning_run_id)
    │           goal_execution_etl.process_one()
    │
    └── else (max_retries=0, normal path):
            harness.run_linear()
            harness.run_agentic()
            save_pair() → _record_goal_pair() × 2
```

---

## Policy Resolution Order

```
1. Load template policy by name from retry_policy table
2. Check task_retry_override for task_category
3. If override exists → replace max_retries only
   (other flags unchanged — keeps failure-type semantics consistent)
```

Example: `aggressive` policy + task_category=`code` with override max_retries=5:
- retry_on_wrong_answer = True (from aggressive template)
- max_retries = 5 (from override, not template's 3)
- backoff_seconds = 2.0 (from aggressive template)

---

## Failure Classification Priority

```
Exception raised?
    → classify by exception type (TimeoutError, ConnectionError, etc.)
No exception, run_result present?
    → check run_result.tool_error flag
    → check quality_score < threshold
Neither?
    → 'crashed'
```

**Why exception type takes priority over run_result?**
Infrastructure failures (network, auth) must not be misclassified as
`wrong_answer` even when the result dict is partially populated.

**Why is 'crashed' never retryable?**
Unknown failures should not loop. Retrying an unknown failure wastes energy
with no signal about whether it will succeed.

**Why is 'context_overflow' never retryable?**
The prompt will not shrink between attempts. Retrying wastes energy with
guaranteed failure.

---

## Failure Injection — Determinism Guarantee

Seed formula:
```python
seed = hash((tool_name, run_id, attempt_number)) & 0xFFFFFFFF
rng  = random.Random(seed)
inject = rng.random() < rate
```

Same inputs → same injection decisions across all replays.
Tool name is part of the seed so different tools get independent draws.
Run ID ensures different experiments don't share injection patterns.

Injected failures are flagged with `INJECTED:` prefix in `error_message`
so downstream queries can separate real vs synthetic failure rates:

```sql
SELECT
    CASE WHEN error_message LIKE 'INJECTED:%' THEN 'injected' ELSE 'real' END AS source,
    failure_type,
    COUNT(*) AS occurrences
FROM tool_failure_events
GROUP BY source, failure_type;
```

---

## Energy Accounting Formulas

### Overhead energy (wasted on retries):
```
overhead_energy_uj = total_energy_uj - successful_energy_uj
```

### Overhead fraction (primary paper signal):
```
overhead_fraction = overhead_energy_uj / total_energy_uj
```

For goals where all attempts fail:
```
overhead_fraction = 1.0
successful_energy_uj = 0
```

### Orchestration fraction (thesis proof):
```
orchestration_fraction = orchestration_energy_uj / pkg_energy_uj
```
Where orchestration_energy_uj comes from energy_attribution of the winning run.

---

## Adding a New Retry Policy

1. Insert into retry_policy table:
```sql
INSERT INTO retry_policy
    (policy_name, max_retries, retry_on_timeout, retry_on_tool_error,
     retry_on_api_error, retry_on_wrong_answer, backoff_seconds)
VALUES ('my_policy', 2, 1, 1, 1, 0, 1.0);
```

2. Reference in experiment config:
```yaml
retry_policy:
  name: "my_policy"
```

3. No code changes needed — RetryCoordinator loads by name from DB.

---

## Adding a Per-Category Override

```sql
INSERT INTO task_retry_override (task_category, max_retries, policy_name)
VALUES ('code', 5, 'aggressive');
```

All `code` category tasks will now retry up to 5 times regardless of
template policy max_retries. Other policy flags unchanged.

---

## Extending FailureClassifier

To add a new failure type:

1. Add to `FAILURE_TYPES` frozenset in `failure_classifier.py`
2. Add classification rule in `_classify_exception()` or `_classify_result()`
3. Add to `is_retryable()` mapping in `retry_coordinator.py`
4. Add to `VALID_FAILURE_TYPES` in `tool_failure_recorder.py`
5. Document in `22-retry-tool-failure-methodology.md`

No DB migration needed — `failure_type` column is open TEXT governed by
application layer (same pattern as `hallucination_type`).

---

## Key Invariants — Never Violate

1. Exactly one `is_winning=1` per goal — enforced by goal_tracker.finish_goal()
2. `retry_of_attempt_id` is NULL for attempt_number=1 — always
3. `is_retry=0` for attempt_number=1 — always
4. `finish_goal()` always called — even on unrecoverable failure
5. ETL runs after finish_goal() — never before
6. Injection only active for experiment_type in {failure_injection, retry_study}
7. 'crashed' is never retryable — no exceptions to this rule
