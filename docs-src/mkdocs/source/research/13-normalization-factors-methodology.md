# Normalisation Factors Methodology

**Document:** `research/13-normalization-factors-methodology.md`  
**Chunk:** 6 (schema), 8 (population)  
**Method ID:** `normalization_factors_v1`  
**Confidence:** 0.90

---

## Overview

Raw energy measurements are incomparable across runs without normalisation.
A run on a hard task with deep planning depth and many retries will always
consume more energy than a trivial single-step task. The `normalization_factors`
table provides the per-run context required to make energy comparisons meaningful.

**Research question enabled:**  
*"Controlling for task difficulty and retry behaviour, does Model A use 30% more
energy than Model B — or does Model A just attempt harder tasks?"*

---

## Factor Taxonomy

Factors are divided into two groups:

### Structural Factors (static)

Describe the inherent properties of the task being evaluated. These are
determined by task configuration and can be computed from `orchestration_events`
and `llm_interactions` without Chunk 8.

| Factor | Source | Description |
|--------|--------|-------------|
| `difficulty_score` | task config | 0.0–1.0 composite difficulty |
| `difficulty_bucket` | computed | easy/medium/hard/very_hard |
| `task_category` | task config | taxonomy category |
| `workload_type` | task config | inference/rag/agentic/tool_use |
| `max_step_depth` | `orchestration_events` | deepest planning depth |
| `branching_factor` | `orchestration_events` | avg branches per node |
| `input_tokens` | `llm_interactions` | prompt tokens |
| `output_tokens` | `llm_interactions` | completion tokens |
| `context_window_size` | model config | model context limit |
| `total_work_units` | computed | `input_tokens × max_step_depth × branching_factor` |

### Behavioural Factors (dynamic)

Describe how the run actually executed — its efficiency relative to the task.
These require Chunk 8 tables (`query_execution`, `query_attempt`,
`hallucination_events`).

| Factor | Source | Description |
|--------|--------|-------------|
| `successful_goals` | `query_execution` | goals completed successfully |
| `attempted_goals` | `query_execution` | total goals attempted |
| `failed_attempts` | `query_attempt` | attempts with status=failure |
| `retry_depth` | `query_attempt` | max attempt_number seen |
| `total_retries` | `query_attempt` | COUNT where status=retry |
| `total_failures` | `query_attempt` | COUNT where status=failure |
| `total_tool_calls` | `orchestration_events` | all tool invocations |
| `failed_tool_calls` | `tool_failure_events` | failed tool invocations |
| `hallucination_count` | `hallucination_events` | detected hallucinations |
| `hallucination_rate` | computed | `hallucination_count / attempted_goals` |

### Resource Factors

Describe the resource environment during execution.

| Factor | Source | Description |
|--------|--------|-------------|
| `rss_memory_gb` | `runs.rss_memory_mb / 1024` | peak memory usage |
| `cache_miss_rate` | computed | `l3_misses / (l3_hits + l3_misses)` |
| `io_wait_ratio` | computed | `io_block_time_ms / duration_ms` |
| `stall_time_ms` | INFERRED | time CPU stalled (not computing) |
| `sla_violations` | Chunk 8 | steps exceeding latency SLA |

---

## Key Formula

### Total Work Units

```
W_total = T_input × D_max × B_avg
```

Where:
- `T_input` = input tokens (structural complexity proxy)
- `D_max` = max_step_depth (planning depth)
- `B_avg` = branching_factor (decision tree breadth)

This composite captures both the *size* of the task (tokens) and the
*complexity* of the execution path (depth × breadth).

### Difficulty Bucket Thresholds

| Bucket | Score Range |
|--------|------------|
| `easy` | score < 0.25 |
| `medium` | 0.25 ≤ score < 0.50 |
| `hard` | 0.50 ≤ score < 0.75 |
| `very_hard` | score ≥ 0.75 |

### Hallucination Rate

```
hallucination_rate = hallucination_count / attempted_goals
```

Range: 0.0–1.0. A rate > 0.1 (10%) indicates unreliable model output
and should trigger a quality flag in `experiment_valid`.

---

## Population Status

| Factor Group | Chunk 6 | Chunk 8 |
|-------------|---------|---------|
| Structural | ❌ Empty | ✅ Populated |
| Behavioural | ❌ NULL | ✅ Populated |
| Resource | ❌ Empty | ✅ Populated |

**Chunk 6 creates the schema only.** All rows are NULL until the
`normalization_factors_etl.py` script is implemented in Chunk 8.

---

## Why Normalisation Matters — Research Example

Consider two agentic runs:

| Metric | Run A | Run B |
|--------|-------|-------|
| `pkg_energy_uj` | 500,000 µJ | 300,000 µJ |
| `total_work_units` | 10,000 | 2,000 |
| Energy per work unit | 50 µJ | 150 µJ |

Run B appears cheaper — but it did 5× less work. Normalised, Run A is
**3× more efficient**. Without normalisation, this would be inverted.

---

## Chunk 8 Dependencies

```
normalization_factors.successful_goals   ← query_execution.success
normalization_factors.attempted_goals    ← query_execution.num_attempts
normalization_factors.failed_attempts    ← query_attempt WHERE status='failure'
normalization_factors.retry_depth        ← MAX(query_attempt.attempt_number)
normalization_factors.total_retries      ← COUNT(query_attempt WHERE status='retry')
normalization_factors.hallucination_rate ← hallucination_events
normalization_factors.sla_violations     ← tool_failure_events
```

---

## References

1. Patterson, D. et al. *FLOPS vs Energy: A Fair Comparison Framework for LLMs*, 2022.
2. Lottick, K. et al. *Measuring the Carbon Intensity of AI in Cloud Instances*, 2019.
3. Panigrahy, D. *A-LEMS Task Taxonomy and Normalisation Design*, 2026.
