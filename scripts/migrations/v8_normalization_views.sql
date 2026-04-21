-- ============================================================
-- MIGRATION v8: Normalization & Attribution Views
-- ============================================================
-- PURPOSE:
--   SQL views that join energy_attribution + normalization_factors
--   + runs to produce researcher-ready normalised metrics.
--
-- VIEWS:
--   v_energy_normalized      — energy per token/second/work-unit
--   v_attribution_summary    — per-layer breakdown with pct columns
--   v_orchestration_overhead — agentic vs linear overhead analysis
--   v_outcome_efficiency     — energy per successful outcome
--
-- NOTE ON ARITHMETIC:
--   All division uses NULLIF(...,0) to avoid divide-by-zero.
--   All duration uses CAST(x AS REAL) to avoid SQLite integer truncation.
--   All energy divided by 1e6 converts µJ → J for human readability.
--
-- Doc: docs-src/mkdocs/source/research/12-energy-attribution-methodology.md
-- ============================================================

-- ── View 1: Normalised energy metrics ────────────────────────────────────────
-- Primary research view. Joins attribution + runs + llm_interactions.
-- All energy values in Joules. Ratios are dimensionless 0–1.
DROP VIEW IF EXISTS v_energy_normalized;
CREATE VIEW v_energy_normalized AS
SELECT
    a.run_id,
    r.workflow_type,
    r.complexity_level,

    -- Raw energy in Joules (µJ / 1e6)
    a.pkg_energy_uj  / 1e6                                      AS total_energy_j,
    a.core_energy_uj / 1e6                                       AS compute_energy_j,
    a.dram_energy_uj / 1e6                                       AS memory_energy_j,

    -- Foreground energy (derived — not stored): pkg minus background
    (a.pkg_energy_uj - COALESCE(a.background_energy_uj, 0)) / 1e6
                                                                  AS foreground_energy_j,

    -- Per-token normalisation (µJ — kept small for readability)
    a.pkg_energy_uj / NULLIF(l.total_tokens, 0)                  AS energy_per_token_uj,

    -- Per-second power (Watts = J/s)
    a.pkg_energy_uj / 1e6
        / NULLIF(CAST(r.duration_ns AS REAL) / 1e9, 0)           AS avg_power_watts,

    -- Orchestration overhead ratio (0–1): how much of total was coordination
    a.orchestration_energy_uj / NULLIF(CAST(a.pkg_energy_uj AS REAL), 0)
                                                                  AS orchestration_ratio,

    -- LLM compute vs orchestration overhead
    a.llm_compute_energy_uj
        / NULLIF(CAST(a.orchestration_energy_uj AS REAL), 0)     AS compute_vs_overhead_ratio,

    -- Unattributed fraction — research quality indicator
    a.unattributed_energy_uj / NULLIF(CAST(a.pkg_energy_uj AS REAL), 0)
                                                                  AS unattributed_ratio,

    -- Attribution model coverage
    a.attribution_coverage_pct,

    -- Raw outcome-normalised costs (µJ per unit)
    a.energy_per_completion_token_uj,
    a.energy_per_successful_step_uj,
    a.energy_per_accepted_answer_uj,
    a.energy_per_solved_task_uj,

    -- Thermal context
    a.thermal_penalty_energy_uj / 1e6                            AS thermal_penalty_j,
    a.thermal_penalty_time_ms,

    r.duration_ns / 1e6                                           AS duration_ms,
    l.total_tokens,
    l.completion_tokens

FROM energy_attribution a
JOIN runs r ON a.run_id = r.run_id
LEFT JOIN (
    -- Aggregate token counts across all LLM calls for this run
    SELECT
        run_id,
        SUM(total_tokens)      AS total_tokens,
        SUM(completion_tokens) AS completion_tokens
    FROM llm_interactions
    GROUP BY run_id
) l ON a.run_id = l.run_id;


-- ── View 2: Per-layer attribution summary with pct columns ───────────────────
-- Used by dashboard attribution waterfall chart.
-- pct columns computed inline — not stored in table (avoids stale data).
DROP VIEW IF EXISTS v_attribution_summary;
CREATE VIEW v_attribution_summary AS
SELECT
    a.run_id,
    r.workflow_type,

    -- Absolute values in Joules
    a.pkg_energy_uj          / 1e6  AS total_j,
    a.core_energy_uj         / 1e6  AS compute_j,
    a.dram_energy_uj         / 1e6  AS memory_j,
    a.background_energy_uj   / 1e6  AS background_j,
    a.network_wait_energy_uj / 1e6  AS network_j,
    a.io_wait_energy_uj      / 1e6  AS io_j,
    a.orchestration_energy_uj/ 1e6  AS orchestration_j,
    a.planning_energy_uj     / 1e6  AS planning_j,
    a.execution_energy_uj    / 1e6  AS execution_j,
    a.synthesis_energy_uj    / 1e6  AS synthesis_j,
    a.llm_compute_energy_uj  / 1e6  AS llm_compute_j,
    a.thermal_penalty_energy_uj / 1e6 AS thermal_penalty_j,
    a.unattributed_energy_uj / 1e6  AS unattributed_j,

    -- Percentage of total pkg energy (computed inline, always fresh)
    ROUND(a.core_energy_uj          * 100.0 / NULLIF(a.pkg_energy_uj, 0), 2) AS compute_pct,
    ROUND(a.dram_energy_uj          * 100.0 / NULLIF(a.pkg_energy_uj, 0), 2) AS memory_pct,
    ROUND(a.background_energy_uj    * 100.0 / NULLIF(a.pkg_energy_uj, 0), 2) AS background_pct,
    ROUND(a.orchestration_energy_uj * 100.0 / NULLIF(a.pkg_energy_uj, 0), 2) AS orchestration_pct,
    ROUND(a.llm_compute_energy_uj   * 100.0 / NULLIF(a.pkg_energy_uj, 0), 2) AS application_pct,
    ROUND(a.unattributed_energy_uj  * 100.0 / NULLIF(a.pkg_energy_uj, 0), 2) AS unattributed_pct,

    a.attribution_coverage_pct,
    a.attribution_model_version

FROM energy_attribution a
JOIN runs r ON a.run_id = r.run_id;


-- ── View 3: Orchestration overhead analysis ───────────────────────────────────
-- Core research view: agentic vs linear orchestration tax.
-- Pairs agentic + linear runs from same experiment for direct comparison.
DROP VIEW IF EXISTS v_orchestration_overhead;
CREATE VIEW v_orchestration_overhead AS
SELECT
    r.exp_id,
    r.run_id,
    r.workflow_type,

    -- Orchestration Tax = agentic_total - linear_total (absolute)
    a.orchestration_energy_uj / 1e6           AS orchestration_j,
    a.pkg_energy_uj / 1e6                     AS total_j,

    -- OOI time: orchestration_ms / total_ms
    ROUND(
        r.orchestration_cpu_ms
        / NULLIF(CAST(r.duration_ns AS REAL) / 1e6, 0),
    4)                                         AS ooi_time,

    -- Phase breakdown
    a.planning_energy_uj   / 1e6              AS planning_j,
    a.execution_energy_uj  / 1e6              AS execution_j,
    a.synthesis_energy_uj  / 1e6              AS synthesis_j,

    r.planning_time_ms,
    r.execution_time_ms,
    r.synthesis_time_ms,
    r.llm_calls,
    r.tool_calls,
    r.steps

FROM energy_attribution a
JOIN runs r ON a.run_id = r.run_id;


-- ── View 4: Outcome efficiency ────────────────────────────────────────────────
-- Energy per successful outcome. NULL for runs without outcome data (pre-Chunk 8).
DROP VIEW IF EXISTS v_outcome_efficiency;
CREATE VIEW v_outcome_efficiency AS
SELECT
    a.run_id,
    r.workflow_type,
    r.complexity_level,
    r.task_id,

    -- Per-token efficiency
    a.energy_per_completion_token_uj,

    -- Per-step efficiency
    a.energy_per_successful_step_uj,

    -- Per-outcome (NULL until Chunk 8)
    a.energy_per_accepted_answer_uj,
    a.energy_per_solved_task_uj,

    -- Normalisation context from normalization_factors
    nf.difficulty_score,
    nf.difficulty_bucket,
    nf.successful_goals,
    nf.attempted_goals,
    nf.total_retries,

    -- Efficiency ratio: energy per successful goal vs attempted goal
    -- < 1.0 means retries were cheap; > 1.0 means retries were expensive
    CASE
        WHEN nf.attempted_goals > 0 AND nf.successful_goals > 0
        THEN CAST(nf.attempted_goals AS REAL) / nf.successful_goals
        ELSE NULL
    END                                        AS attempt_efficiency_ratio

FROM energy_attribution a
JOIN runs r ON a.run_id = r.run_id
LEFT JOIN normalization_factors nf ON a.run_id = nf.run_id;
