-- Migration 030: Research Views
-- Chunk 8.4 | Schema Revision: 030
--
-- Three views that directly support paper analysis.
-- Views are read-only aggregation — they never recompute energy.
-- All energy ground truth comes from ETL-populated columns in goal_execution
-- and energy_attribution. Views only present and join that data.
--
-- corrected_by_retry derived here (not stored in hallucination_events):
--   EXISTS later attempt with outcome='success' on same goal.

PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────
-- VIEW: v_goal_energy_decomposition
-- Primary paper view. Per-goal energy breakdown by workflow type.
-- ge.total_energy_uj is authoritative ground truth — set by goal_execution_etl.py.
-- orchestration fraction sourced from winning run only (correct — it is a rate, not a sum).
-- Uses positive inclusion filter on experiment_type per master spec.
-- ─────────────────────────────────────────────
CREATE VIEW IF NOT EXISTS v_goal_energy_decomposition AS
SELECT
    ge.goal_id,
    ge.exp_id,
    ge.workflow_type,
    ge.goal_type,
    ge.difficulty_level,
    ge.total_attempts,
    ge.success,
    ge.total_energy_uj          / 1e6  AS total_energy_j,
    ge.successful_energy_uj     / 1e6  AS successful_energy_j,
    ge.overhead_energy_uj       / 1e6  AS overhead_energy_j,
    ge.overhead_fraction,
    ge.orchestration_fraction,
    ea.llm_compute_energy_uj    / 1e6  AS compute_energy_j,
    ea.orchestration_energy_uj  / 1e6  AS orchestration_energy_j,
    ROUND(ea.llm_compute_energy_uj * 100.0
          / NULLIF(ea.pkg_energy_uj, 0), 2)        AS compute_pct,
    ROUND(ea.orchestration_energy_uj * 100.0
          / NULLIF(ea.pkg_energy_uj, 0), 2)        AS orchestration_pct,
    CASE WHEN ge.total_attempts > 1 THEN 1 ELSE 0
    END                                            AS had_retry,
    e.experiment_type,
    e.experiment_goal
FROM goal_execution ge
JOIN experiments e
    ON ge.exp_id = e.exp_id
LEFT JOIN energy_attribution ea
    ON ge.winning_run_id = ea.run_id
WHERE e.experiment_type IN (
    'normal','overhead_study','retry_study',
    'failure_injection','quality_sweep','ablation','pilot'
);

-- ─────────────────────────────────────────────
-- VIEW: v_failure_energy_taxonomy
-- Shows energy wasted per failure category and type.
-- Supports paper claim that orchestration failures dominate overhead.
-- failure_domain separates reasoning failures from execution failures —
--   required for cross-category paper comparisons.
-- Uses wasted_energy_uj_real (REAL) from hallucination_events for precision.
-- ─────────────────────────────────────────────
CREATE VIEW IF NOT EXISTS v_failure_energy_taxonomy AS
SELECT
    'reasoning'                 AS failure_domain,
    'hallucination'             AS failure_category,
    he.hallucination_type       AS failure_subtype,
    COUNT(*)                    AS event_count,
    SUM(he.wasted_energy_uj_real) / 1e6  AS total_wasted_j,
    AVG(he.wasted_energy_uj_real) / 1e6  AS avg_wasted_j,
    ge.workflow_type,
    EXISTS (
        SELECT 1 FROM goal_attempt ga2
        WHERE ga2.goal_id = he.goal_id
          AND ga2.attempt_number > ga.attempt_number
          AND ga2.outcome = 'success'
    )                           AS corrected_by_retry
FROM hallucination_events he
JOIN goal_attempt ga   ON he.attempt_id = ga.attempt_id
JOIN goal_execution ge ON he.goal_id = ge.goal_id
GROUP BY he.hallucination_type, ge.workflow_type

UNION ALL

SELECT
    'execution'                 AS failure_domain,
    'tool_failure'              AS failure_category,
    tfe.failure_type            AS failure_subtype,
    COUNT(*)                    AS event_count,
    SUM(tfe.wasted_energy_uj) / 1e6  AS total_wasted_j,
    AVG(tfe.wasted_energy_uj) / 1e6  AS avg_wasted_j,
    ge.workflow_type,
    0                           AS corrected_by_retry
FROM tool_failure_events tfe
JOIN goal_attempt ga   ON tfe.attempt_id = ga.attempt_id
JOIN goal_execution ge ON tfe.goal_id = ge.goal_id
GROUP BY tfe.failure_type, ge.workflow_type;

-- ─────────────────────────────────────────────
-- VIEW: v_quality_energy_frontier
-- Quality vs energy per goal. Supports paper figure showing quality-energy
-- tradeoff differs between linear and agentic workflows.
-- Uses ge.total_energy_uj (authoritative, includes all retry overhead)
-- NOT ga.energy_uj (single attempt only — would bias toward single-attempt runs).
-- Excludes needs_review scores and debug experiments.
-- ─────────────────────────────────────────────
CREATE VIEW IF NOT EXISTS v_quality_energy_frontier AS
SELECT
    oq.attempt_id,
    oq.goal_id,
    oq.normalized_score,
    oq.metric_type,
    oq.judge_method,
    oq.score_method,
    oq.judge_count,
    ge.total_energy_uj      / 1e6  AS total_goal_energy_j,
    ga.energy_uj            / 1e6  AS attempt_energy_j,
    ga.orchestration_uj     / 1e6  AS attempt_orchestration_j,
    ga.compute_uj           / 1e6  AS attempt_compute_j,
    ga.outcome,
    ge.workflow_type,
    ge.goal_type,
    ge.difficulty_level,
    CASE WHEN oq.normalized_score > 0
         THEN ge.total_energy_uj / oq.normalized_score
         ELSE NULL
    END                            AS energy_per_quality_point_uj,
    e.experiment_type
FROM output_quality oq
JOIN goal_attempt ga   ON oq.attempt_id = ga.attempt_id
JOIN goal_execution ge ON oq.goal_id = ge.goal_id
JOIN experiments e     ON ge.exp_id = e.exp_id
WHERE oq.score_method != 'needs_review'
  AND e.experiment_type IN (
      'normal','overhead_study','retry_study',
      'failure_injection','quality_sweep','ablation','pilot'
  );
