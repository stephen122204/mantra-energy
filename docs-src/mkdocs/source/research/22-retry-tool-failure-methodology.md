# Retry and Tool Failure Methodology

## Overview

This document describes the methodology for retry policy management, failure
classification, and deterministic failure injection in A-LEMS. These mechanisms
serve the paper thesis by making wasted energy from failed attempts measurable,
reproducible, and attributable by failure type.

---

## Motivation — Why Retry Energy Matters

Production LLM API systems fail 15-30% of calls due to rate limits, timeouts,
context window overflow, and tool errors. Unlike traditional software benchmarks
that only measure successful inference, A-LEMS captures the full energy cost
of recovery — including every failed attempt before a successful result.

This matters because:
- A rate-limited call wastes energy waiting and retrying with no useful output
- A context overflow call completes its RAPL measurement window but produces nothing
- An agentic system making 3-5 tool calls per task has 3-5x the failure surface
  of a linear system making one call

The energy overhead of these failures is the core signal in paper Figure 3
(wasted energy taxonomy). Without retry tracking, this energy is invisible.

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

For fully failed goals (no successful attempt):
`overhead_fraction = 1.0` — all energy was wasted.

For partially successful goals (succeeded after retries):
`0 < overhead_fraction < 1.0` — fraction wasted on failed attempts.

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
| `rate_limit` | RateLimitError, HTTP 429, "Too Many Requests" |
| `context_overflow` | ContextLengthExceeded, "exceed context window", "context_length" |
| `tool_error` | run_result.tool_error = True |
| `wrong_answer` | quality_score < 0.5 with no exception |
| `crashed` | Any unrecognised exception or unclassifiable result |

### Classification Priority Order

1. Exception type check (`_classify_exception`) — infrastructure failures raised by harness
2. Result dict `execution.error_message` check (`_classify_result`) — provider errors
   caught internally by harness and returned in result dict rather than raised
3. `tool_error` flag in result dict
4. Quality score threshold check
5. `crashed` fallback

**Critical implementation note:** Many provider errors (HTTP 429, context overflow)
are caught inside the harness and returned as result dicts with `error_message`
set. The classifier must check `execution.error_message` — not just exception type.
This was a discovered bug fixed in 8.5-B.2.

### Retryable vs Non-Retryable

| Type | Retryable | Rationale |
|---|---|---|
| `rate_limit` | Yes (if policy allows) | Transient — backoff and retry |
| `timeout` | Yes (if policy allows) | Transient — may succeed on retry |
| `api_error` | Yes (if policy allows) | Transient network issue |
| `context_overflow` | No | Structural — same prompt will fail again |
| `tool_error` | Yes (if policy allows) | External tool may recover |
| `wrong_answer` | Yes (if policy allows) | Model may produce different answer |
| `crashed` | No | Unknown cause — unsafe to retry |

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

Real production systems fail unpredictably — injection lets us run exact
controlled experiments: "How much energy does a system waste when 30% of
tool calls fail?" with reproducible, citable results.

### Injection Types

| Type | Rate Config Key | Effect |
|---|---|---|
| Timeout | `timeout_rate` | Raises TimeoutError before harness call |
| Tool failure | `tool_failure_rate` | Raises tool error before harness call |

### Determinism

Each injection decision uses `random.Random(seed)` with:

```
seed = hash(failure_type, rep_num, attempt_number) & 0xFFFFFFFF
```

`rep_num` (repetition number, 1-indexed) varies per repetition so each rep
gets a different injection pattern. `attempt_number` varies per retry within
a rep. Same experiment inputs always produce the same injection pattern.

**Critical implementation note:** Early versions used `attempt_num` as the
seed's `run_id` component — this caused the same seed every rep (attempt_num
always 1 on first attempt). Fixed in 8.5-B.2 to use `rep_num`.

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

### Table Scope

`tool_failure_events` covers infrastructure failures only:
- timeout, api_error, rate_limit, context_overflow, tool_error

Quality failures (wrong_answer, hallucination) go to separate tables:
- `output_quality` — normalized quality scores
- `hallucination_events` — hallucination classification

This separation keeps paper Figure 3 taxonomy clean: infrastructure waste
vs quality waste are distinct energy cost categories.

---

## Two Execution Paths

A-LEMS has two execution paths that must never be merged:

**Normal path** (`save_pair()`/`save_single()`):
Used when `max_retries = 0`. Harness runs once, result saved directly.
No retry loop, no attempt tracking beyond single goal_attempt row.

**Retry path** (`execute_goal()` → `RunPersistenceService`):
Used when `max_retries > 0`. `execute_goal()` owns the full lifecycle:
harness execution + attempt tracking + retry decision + persistence.
The harness is NOT called from the rep loop in this path — execute_goal()
calls it internally per attempt.

Mixing these paths corrupts energy accounting and attempt numbering.

---

## Planned Experiments

### Retry Cost Curve
Vary `max_retries` = 0, 1, 2, 3.
Measure: success %, joules/goal, overhead_fraction.
Expected finding: diminishing returns beyond max_retries=2 for most failure types.

### Failure Type Sensitivity
Inject timeout vs rate_limit vs api_error independently.
Compare energy overhead per failure type.
Expected: rate_limit most expensive (backoff wait energy), timeout cheapest (fails fast).

### Local vs Cloud Failure Comparison
groq (cloud): organic 429 rate limits observed in development
llama_cpp (local): organic context overflow at 512-token TinyLlama limit
Expected: different failure type distributions, comparable overhead_fraction.
