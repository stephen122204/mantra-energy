# Retry and Tool Failure Methodology

## Overview

This document describes the methodology for retry policy management, failure
classification, and deterministic failure injection in A-LEMS. These mechanisms
serve the paper thesis by making wasted energy from failed attempts measurable,
reproducible, and attributable by failure type.

---

## Retry Policy (`retry_policy_v1`)

**Confidence: 0.90**

### Design

Four canonical policies cover all paper experiment types:

| Policy | max_retries | wrong_answer retry | backoff |
|---|---|---|---|
| `no_retry` | 0 | No | 0s |
| `default` | 1 | No | 0s |
| `aggressive` | 3 | Yes | 2s |
| `conservative` | 1 | No | 5s |

Policies are stored in the `retry_policy` table and loaded at runtime by
`RetryCoordinator`. Per-category overrides in `task_retry_override` can
replace `max_retries` only — failure-type flags remain from the template policy.
This keeps flag semantics consistent while allowing category-level retry tuning.

### Policy Resolution Order

1. Load template policy by name from experiment config
2. Check `task_retry_override` for the task's category
3. If override exists, replace `max_retries` only

### Energy Accounting

Wasted energy from failed attempts is captured via `goal_attempt.energy_uj`
snapshots at `finish_attempt()` time. The ETL rolls these into
`goal_execution.overhead_energy_uj = total_energy_uj - successful_energy_uj`.

### Confidence Rationale

0.90 — policy logic is deterministic; 0.10 uncertainty reflects that
`context_overflow` failures are never retried regardless of policy, which
assumes the prompt will not change between attempts.

---

## Failure Classification (`failure_classification_v1`)

**Confidence: 0.85**

### Canonical Failure Types

| Type | Source |
|---|---|
| `timeout` | TimeoutError, concurrent.futures.TimeoutError, httpx.TimeoutException |
| `api_error` | ConnectionError, ConnectError, APIError |
| `rate_limit` | RateLimitError from any provider |
| `context_overflow` | ContextLengthExceeded from any provider |
| `tool_error` | run_result.tool_error = True |
| `wrong_answer` | quality_score < 0.5 with no exception |
| `crashed` | Any unrecognised exception or unclassifiable result |

### Priority Order

Exception type is checked before run_result fields. This ensures infrastructure
failures (network, auth) are never misclassified as wrong_answer even when
the result dict is partially populated.

### Confidence Rationale

0.85 — exception name matching uses string checks rather than isinstance()
to avoid hard imports of provider SDKs. New provider exception names not
matching known patterns will fall through to `crashed`, which is safe but
loses specificity.

---

## Failure Injection (`failure_injection_v1`)

**Confidence: 1.0**

### Purpose

Controlled failure injection produces known failure rates for measuring
recovery energy cost without depending on organic provider failures.
Results feed Paper Figure 3 (wasted energy taxonomy).

### Determinism

Each injection decision uses `random.Random(seed)` with:

```
seed = hash(tool_name, run_id, attempt_number) & 0xFFFFFFFF
```

Same experiment inputs always produce the same injection pattern.
This makes failure injection study results fully reproducible.

### Safety Guards

- Only active when `failure_injection.enabled = True` in experiment config
- Only permitted for `experiment_type` in `{failure_injection, retry_study}`
- Injected failures are logged with `INJECTED:` prefix in `error_message`
  so downstream queries can separate real vs synthetic failure rates

### Confidence Rationale

1.0 — injection logic is pure deterministic arithmetic with no measurement
uncertainty. Whether a failure is injected is a binary decision with a known
seed; there is no approximation.

---

## Tool Failure Recording

All inserts to `tool_failure_events` go through `tool_failure_recorder.py`.
`wasted_energy_uj` is always NULL at insert time — `energy_attribution_etl`
populates it after the run completes (SC-4 ETL pattern).

The recorder normalises unknown `failure_type` values to `'other'` and
unknown `failure_phase` values to NULL rather than raising, so harness
execution continues even if a novel failure type is encountered.
