# Hallucination and Output Quality Methodology
*Chunk 8.3 | Schema Revision: 028*

---

## Overview

This document covers the measurement methodology for two new research tables introduced in Chunk 8.3:

- `hallucination_events` — energy cost of incorrect outputs
- `output_quality` — reconciled judgment verdict per attempt
- `output_quality_judges` — per-judge evidence trail

These tables answer the core research question: **how much energy does the agentic workflow waste on wrong answers?**

---

## Hallucination Detection Methodology
*method_id: `hallucination_detection_v1` | confidence: 0.85*

### Definition

A hallucination is an unsupported or incorrect output later classified as hallucinatory by a detection pipeline. Confidence is not required at detection time — some pipelines have no logit access.

### Taxonomy

Hallucination types and detection methods are governed by `core/ontology_registry.py` v1.0.0. This is the single source of truth across all papers on this platform.

| Field | Governance | Extensibility |
|---|---|---|
| `hallucination_type` | `ontology_registry.HALLUCINATION_TYPES` | PR to registry — no DB migration |
| `detection_method` | `ontology_registry.DETECTION_METHODS` | PR to registry + new `method_id` in provenance |

### Detection Signals

**`detection_confidence`** — the detection pipeline's confidence (0–1) that this output is hallucinatory. This is not model logprob. It is the detector's own assessment. Nullable when detection pipeline produces binary yes/no only.

**`semantic_similarity`** — cosine similarity between embeddings of `expected_output` and `actual_output`, range 0–1. Nullable when detection method does not use embeddings.

**`severity`** — continuous 0.0–1.0 scale indicating impact magnitude. NULL in Chunk 8.3 — populated by a future chunk that defines a `hallucination_severity_vN` method.

### Nullable Trace Links

`decision_id`, `interaction_id`, and `orchestration_event_id` are all nullable. Real systems do not always have full traceability from a hallucination back to its originating event.

---

## Hallucination Wasted Energy Methodology
*method_id: `hallucination_wasted_energy_v1` | confidence: 0.85*

### Definition

$$E_{wasted} = E_{\text{attempt\_start} \to \text{detected}}$$

Energy consumed from the start of the attempt until the hallucination was detected. This is the energy that would have been saved if the hallucination had been caught earlier.

### Population

`wasted_energy_uj` is NULL at insert time. Populated asynchronously by `chunk8_attribution_etl.py` (Agent 8.4). Source: `orchestration_events.event_energy_uj` for the relevant event window.

### Corrected-Later Derivation

Whether a hallucination was subsequently corrected is **not stored** in this table. Derive when needed:

```sql
SELECT he.*,
       CASE WHEN EXISTS (
           SELECT 1 FROM goal_attempt ga2
           WHERE ga2.goal_id = he.goal_id
             AND ga2.attempt_number > ga.attempt_number
             AND ga2.outcome = 'success'
       ) THEN 1 ELSE 0 END AS corrected_by_retry
FROM hallucination_events he
JOIN goal_attempt ga ON he.attempt_id = ga.attempt_id
```

---

## Output Quality Normalization Methodology
*method_id: `output_quality_normalization_v1` | confidence: 0.90*

### Architecture

`output_quality` (parent) holds the reconciled verdict. `output_quality_judges` (child) holds one row per judge per attempt. This supports N judges without schema changes.

### Agreement Score

For two judges (scores normalized 0–1):

$$\text{agreement} = 1 - |s_1 - s_2|$$

For N judges: normalized standard deviation over child table rows.

### Tie-Break Logic

Application layer computes `score_method` and `normalized_score` at insert time:

| Condition | `score_method` | `normalized_score` |
|---|---|---|
| `judge_count = 1` | `single_judge` | that judge's score |
| `agreement >= 0.8` | `averaged` | mean of judge scores |
| `agreement >= 0.5` | `conservative_min` | min of judge scores |
| `agreement < 0.5` | `needs_review` | NULL |

### Analysis Exclusion

Rows with `score_method = 'needs_review'` are excluded from all paper analysis queries:

```sql
WHERE score_method != 'needs_review'
```

The disagreement rate (proportion of `needs_review` rows) should be reported separately in the paper as a data quality metric.

### Re-Judging

One row per attempt is enforced by `UNIQUE(attempt_id)`. Re-judging requires UPDATE of the existing row plus INSERT of new rows into `output_quality_judges`. Do not DELETE and re-INSERT.

### Judge Reproducibility Fields

`judge_prompt_hash`, `judge_version`, `judge_temperature`, and `judge_provider` in `output_quality_judges` enable exact reproduction of any judgment across papers. These fields are nullable until the experiment runner implements prompt hashing.

---

## Provenance Summary

| Column | Method | Type |
|---|---|---|
| `he.detection_confidence` | `hallucination_detection_v1` | INFERRED |
| `he.semantic_similarity` | `hallucination_detection_v1` | INFERRED |
| `he.severity` | `hallucination_detection_v1` | INFERRED |
| `he.wasted_energy_uj` | `hallucination_wasted_energy_v1` | CALCULATED |
| `oq.raw_score` | `output_quality_normalization_v1` | MEASURED |
| `oq.normalized_score` | `output_quality_normalization_v1` | CALCULATED |
| `oq.agreement_score` | `output_quality_normalization_v1` | CALCULATED |
| `oq.energy_uj_at_judgment` | `goal_execution_rollup_v1` | CALCULATED |
| `oqj.judge_score` | `output_quality_normalization_v1` | MEASURED |
| `oqj.judge_confidence` | `output_quality_normalization_v1` | INFERRED |

---

## What Agent 8.3 Does NOT Do

- Does not write ETL to populate `wasted_energy_uj` — owned by Agent 8.4
- Does not backfill `normalization_factors` — owned by Agent 8.4
- Does not populate `severity` — owned by a future chunk
- Does not touch `run_quality`, `goal_execution`, `goal_attempt` schema
