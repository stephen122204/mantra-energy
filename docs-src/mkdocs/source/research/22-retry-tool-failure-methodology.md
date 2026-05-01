# Retry and Tool Failure Methodology

## Scope

This document covers retry policy management, failure classification, and
deterministic failure injection. For energy attribution of failures see
`20-tool-failure-methodology.md`. For tool execution instrumentation see
`24-tool-instrumentation-methodology.md`.

---

## Motivation — Why Retry Energy Matters

Production LLM API systems fail 15-30% of calls due to rate limits, timeouts,
context window overflow, and tool errors. A-LEMS captures the full energy cost
of recovery — including every failed attempt before a successful result.

An agentic system making 3-5 tool calls per task has 3-5x the failure surface
of a linear system. The energy overhead of these failures is the core signal
in paper Figure 3 (wasted energy taxonomy). Without retry tracking, this
energy is invisible.

---

## Retry Policy
*method_id: `retry_policy_v1` | confidence: 0.90*

### Four Canonical Policies

| Policy | max_retries | wrong_answer retry | backoff |
|---|---|---|---|
| `no_retry` | 0 | No | 0s |
| `default` | 1 | No | 0s |
| `aggressive` | 3 | Yes | 2s |
| `conservative` | 1 | No | 5s |

Stored in `retry_policy` table. Per-category overrides in `task_retry_override`
replace `max_retries` only — failure-type flags remain from template policy.

### Policy Resolution Order

1. Load template policy by name from experiment config `retry_policy.name`
2. Check `task_retry_override` for task's category
3. If override exists, replace `max_retries` only

### Energy Accounting

Wasted energy from failed attempts is captured via `goal_attempt.energy_uj`
snapshots at `finish_attempt()` time. ETL rolls these into:
- `goal_execution.overhead_energy_uj = total_energy_uj - successful_energy_uj`
- `overhead_fraction = 1.0` for fully failed goals
- `0 < overhead_fraction < 1.0` for goals that succeeded after retries

### Confidence Rationale

0.90 — policy logic is deterministic. 0.10 uncertainty reflects that
`context_overflow` is never retried regardless of policy, assuming prompt
will not change between attempts (structural failure).

---

## Failure Classification
*method_id: `failure_classification_v1` | confidence: 0.85*

### Canonical Failure Types

| Type | Source |
|---|---|
| `timeout` | TimeoutError, concurrent.futures.TimeoutError, httpx.TimeoutException |
| `api_error` | ConnectionError, ConnectError, APIError |
| `rate_limit` | RateLimitError, HTTP 429, "Too Many Requests" |
| `context_overflow` | ContextLengthExceeded, "exceed context window", "context_length" |
| `tool_error` | run_result.tool_error = True |
| `wrong_answer` | quality_score < 0.5 with no exception |
| `crashed` | Any unrecognised exception |

### Four-Layer Classification Priority

Layer 1: Exception type check — infrastructure failures raised by harness.
Layer 2: `execution.error_type` — set by agentic structured detection (most reliable).
Layer 3: `execution.error_message` — provider errors caught internally by harness.
Layer 4: Scan `step_results[*].result` for "Error:" prefix strings.
Fallback: `execution.status == "failure"` → `api_error`.

**Critical:** Provider errors (HTTP 429, context overflow) are often caught
inside the harness and returned as result dicts with `error_message` set,
not raised as exceptions. All four layers must be checked in order.

**Conservative default:** `exec_dict.get("status", "failure")` — absent status
is treated as failure, not success. Prevents malformed results from silently
passing as successful runs.

### Structured Failure Detection

Agentic executor scans step results after the full execution loop:

```python
step_errors = [
    sr.get("result", "")
    for sr in step_results
    if isinstance(sr.get("result", ""), str)
    and sr.get("result", "").startswith("Error:")
]

if failed_steps == 0:
    execution_status = "success"
elif failed_steps < total_steps:
    execution_status = "partial_failure"   # some steps failed, synthesis continued
else:
    execution_status = "failure"           # all steps failed
```

`partial_failure` is treated as `failure` for goal tracking. Paper can filter
by `execution.failed_steps > 0` for finer analysis.

### Retryable vs Non-Retryable

| Type | Retryable | Rationale |
|---|---|---|
| `rate_limit` | Yes | Transient — backoff and retry |
| `timeout` | Yes | Transient — may succeed on retry |
| `api_error` | Yes | Transient network issue |
| `context_overflow` | No | Structural — same prompt fails again |
| `tool_error` | Yes | External tool may recover |
| `wrong_answer` | Yes (if policy allows) | Model may produce different answer |
| `crashed` | No | Unknown cause — unsafe to retry |

### Confidence Rationale

0.85 — exception name matching uses string checks to avoid hard imports of
provider SDKs. New provider exception names not matching known patterns fall
through to `crashed` — safe but loses classification specificity.

---

## Two Execution Paths

These paths must never be merged:

**Normal path** (`save_pair()`/`save_single()`):
`max_retries = 0`. Harness runs once, result saved directly.

**Retry path** (`execute_goal()` → `RunPersistenceService`):
`max_retries > 0`. `execute_goal()` owns full lifecycle. Harness is NOT
called from rep loop — `execute_goal()` calls it internally per attempt.
One `runs` row inserted after all attempts complete.

---

## Failure Injection v2
*method_id: `failure_injection_v2` | confidence: 1.0*
*Supersedes: `failure_injection_v1`*

### What Changed in v2

| Aspect | v1 | v2 |
|---|---|---|
| Seeding | `hash(tool, run_id, attempt) & 0xFFFFFFFF` — unstable across processes | `SHA-256(scenario_id:rep:attempt:kind:tool)` — stable everywhere |
| Modes | Single mode (probabilistic) | Three modes: deterministic_validation, deterministic_stress, statistical |
| Cross-provider | No shared schedule — different exp_ids → different injection | `scenario_id` enables shared schedule across providers |
| Clustering | Random — may cluster at start | Evenly-spaced slots — uniform distribution |
| Audit trail | None | Full per-decision log with seed values |
| Failure budget | Global count | Per-kind (timeout separate from tool_failure) |

### Stable SHA-256 Seeding

```
seed_input = f"{scenario_id}:{rep_num}:{attempt_num}:{kind}:{tool_name}"
digest     = SHA-256(seed_input)
rand       = first_8_bytes_as_uint64 / 2^64   → float in [0, 1)
```

Python `hash()` is PYTHONHASHSEED-randomised since Python 3.3 — different
every process. SHA-256 produces identical output across platforms, Python
versions, and process restarts. Reviewers can verify any injection decision
from the published audit log.

### Three Modes

**deterministic_validation** — Exact N failures at evenly-spaced draw positions.
Rates ignored. Same schedule every run. For CI and architecture validation.

**deterministic_stress** — Every attempt fails. For retry exhaustion testing.
Respects `max_retries` — never produces infinite loops.

**statistical** — SHA-256-seeded Bernoulli draws against configured rates.
For paper Figure 3 data collection. Requires 30+ repetitions.

### Evenly-Spaced Slot Algorithm

For N total draws and K required failures:

$$slot_i = \text{round}\left(\frac{(i + 0.5) \times N}{K}\right), \quad i = 0, 1, \ldots, K-1$$

Example: N=6, K=2 → slots {2, 4} not {1, 2}.

Avoids pathological clustering at experiment start which would conflate
injection warmup effects with real measurement signal.

### scenario_id — Cross-Provider Fairness

Without `scenario_id`: different providers get different `exp_id` → different
SHA-256 inputs → different injection slots. Comparison is invalid.

With `scenario_id = "failure_study_v1"`: all providers share identical slots.
Energy difference = provider efficiency, not scheduling artifact.

Rule: always set `scenario_id` for multi-provider studies. Bump version when
injection config changes.

### Post-Harness Injection Only

Every LLM execution consumes real RAPL energy regardless of logical outcome.
Injection modifies the result dict AFTER harness completes:

```
harness runs → RAPL captures energy
→ post-harness injection: result["execution"]["status"] = "failure"
→ goal_execution_manager reads status → outcome = "failure"
→ tool_failure_events row created with real energy data
→ retry_coordinator decides retry → attempt 2 → harness runs again
```

Pre-harness injection produces zero-energy records — invalid for paper claims.

### Workload-Aware Injection

| Workload | Valid Injection |
|---|---|
| Pure LLM tasks | timeout, rate_limit, api_error, context_overflow |
| Tool graph tasks | tool_error, timeout |

Tool failure injection on pure LLM tasks is invalid — `_dispatch_tool` is
never called so injection never fires.

### Validating the Injector

```python
from core.execution.failure_injector import FailureInjector, _evenly_spaced_slots

# Verify slot spacing
assert sorted(_evenly_spaced_slots(6, 2)) == [2, 4]

# Verify deterministic mode produces exact N failures
fi = FailureInjector(
    {'enabled': True, 'mode': 'deterministic_validation',
     'min_failures': 2, 'total_draws_estimate': 6},
    'failure_injection'
)
fi.set_exp_id(999, total_draws=6)
results = [fi.maybe_inject_timeout(r, a) for r in range(1, 4) for a in range(1, 3)]
summary = fi.injection_summary()
assert summary['by_kind']['timeout']['planned_failures'] == \
       summary['by_kind']['timeout']['realized_failures'], \
    "Injection schedule not met — increase repetitions or fix total_draws_estimate"
```

### Audit Trail

```python
fi.get_audit_log()
# Returns list of dicts:
# exp_id, scenario_id, rep_num, attempt_num, kind,
# tool_name, injected, seed_value, mode, draw_index
```

Publish as supplementary material — reviewers can verify the exact injection
schedule and reproduce any experiment.

### Confidence Rationale

1.0 — injection logic is pure deterministic arithmetic for deterministic modes,
SHA-256 for statistical mode. No measurement uncertainty in either case.

---

## Planned Experiments

### Retry Cost Curve
Vary `max_retries` = 0, 1, 2, 3 with `retry_study` experiment_type.
Measure: success %, joules/goal, overhead_fraction.
Expected: diminishing returns beyond max_retries=2 for most failure types.

### Failure Type Sensitivity
Inject timeout vs rate_limit vs api_error independently (separate YAMLs).
Compare energy overhead per failure type.
Expected: rate_limit most expensive (backoff wait), timeout cheapest (fails fast).

### Local vs Cloud Failure Comparison
groq (cloud): organic 429 rate limits.
llama_cpp (local): organic context overflow at 512-token TinyLlama limit.
Expected: different failure type distributions, comparable overhead_fraction.
Use `scenario_id` to ensure identical injection schedules across providers.
