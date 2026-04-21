-- Chunk 6.1 Fixes Migration
-- Deploy: sqlite3 data/experiments.db < scripts/migrations/v10_chunk61_fixes.sql

-- 1. New columns in energy_attribution
ALTER TABLE energy_attribution ADD COLUMN llm_wait_energy_uj BIGINT DEFAULT 0;
ALTER TABLE energy_attribution ADD COLUMN attribution_method TEXT DEFAULT 'cpu_fraction_v1';
ALTER TABLE energy_attribution ADD COLUMN ml_model_version TEXT DEFAULT NULL;

-- 2. Drop all Chunk 6 views (will recreate below with fixes)
DROP VIEW IF EXISTS v_energy_normalized;
DROP VIEW IF EXISTS v_attribution_summary;
DROP VIEW IF EXISTS v_orchestration_overhead;
DROP VIEW IF EXISTS v_outcome_efficiency;

-- 3. v_energy_normalized — fixed: task_duration_ns for power, added llm_wait_ratio
CREATE VIEW v_energy_normalized AS
SELECT
    a.run_id,
    r.workflow_type,
    r.complexity_level,
    a.pkg_energy_uj  / 1e6                                             AS total_energy_j,
    a.core_energy_uj / 1e6                                             AS compute_energy_j,
    a.dram_energy_uj / 1e6                                             AS memory_energy_j,
    a.background_energy_uj / 1e6                                       AS background_energy_j,
    (a.pkg_energy_uj - COALESCE(a.background_energy_uj,0)) / 1e6      AS foreground_energy_j,
    a.llm_wait_energy_uj / 1e6                                         AS llm_wait_energy_j,
    a.llm_compute_energy_uj / 1e6                                      AS llm_compute_energy_j,
    a.orchestration_energy_uj / 1e6                                    AS orchestration_energy_j,
    -- per-token normalisation (µJ)
    a.pkg_energy_uj / NULLIF(l.total_tokens, 0)                        AS energy_per_token_uj,
    -- corrected power: use task_duration_ns not duration_ns (Chunk 6 duration fix)
    a.pkg_energy_uj / 1e6
        / NULLIF(CAST(r.task_duration_ns AS REAL) / 1e9, 0)            AS avg_power_watts,
    -- ratios (0-1)
    a.orchestration_energy_uj / NULLIF(CAST(a.pkg_energy_uj AS REAL),0) AS orchestration_ratio,
    a.llm_wait_energy_uj      / NULLIF(CAST(a.pkg_energy_uj AS REAL),0) AS llm_wait_ratio,
    a.llm_compute_energy_uj
        / NULLIF(CAST(a.orchestration_energy_uj AS REAL),0)             AS compute_vs_overhead_ratio,
    a.unattributed_energy_uj  / NULLIF(CAST(a.pkg_energy_uj AS REAL),0) AS unattributed_ratio,
    a.attribution_coverage_pct,
    a.attribution_method,
    -- outcome normalised costs
    a.energy_per_completion_token_uj,
    a.energy_per_successful_step_uj,
    a.energy_per_accepted_answer_uj,
    a.energy_per_solved_task_uj,
    -- thermal
    a.thermal_penalty_energy_uj / 1e6                                   AS thermal_penalty_j,
    a.thermal_penalty_time_ms,
    r.task_duration_ns / 1e6                                            AS task_duration_ms,
    r.duration_ns      / 1e6                                            AS total_duration_ms,
    l.total_tokens,
    l.completion_tokens
FROM energy_attribution a
JOIN runs r ON a.run_id = r.run_id
LEFT JOIN (
    SELECT run_id,
           SUM(total_tokens)      AS total_tokens,
           SUM(completion_tokens) AS completion_tokens
    FROM llm_interactions
    GROUP BY run_id
) l ON a.run_id = l.run_id;

-- 4. v_attribution_summary — added llm_wait_j + llm_wait_pct
CREATE VIEW v_attribution_summary AS
SELECT
    a.run_id,
    r.workflow_type,
    -- absolute Joules
    a.pkg_energy_uj           / 1e6  AS total_j,
    a.core_energy_uj          / 1e6  AS compute_j,
    a.dram_energy_uj          / 1e6  AS memory_j,
    a.background_energy_uj    / 1e6  AS background_j,
    a.network_wait_energy_uj  / 1e6  AS network_j,
    a.io_wait_energy_uj       / 1e6  AS io_j,
    a.llm_wait_energy_uj      / 1e6  AS llm_wait_j,
    a.llm_compute_energy_uj   / 1e6  AS llm_compute_j,
    a.orchestration_energy_uj / 1e6  AS orchestration_j,
    a.planning_energy_uj      / 1e6  AS planning_j,
    a.execution_energy_uj     / 1e6  AS execution_j,
    a.synthesis_energy_uj     / 1e6  AS synthesis_j,
    a.thermal_penalty_energy_uj / 1e6 AS thermal_penalty_j,
    a.unattributed_energy_uj  / 1e6  AS unattributed_j,
    -- percentages of pkg
    ROUND(a.core_energy_uj          * 100.0 / NULLIF(a.pkg_energy_uj,0), 2) AS compute_pct,
    ROUND(a.dram_energy_uj          * 100.0 / NULLIF(a.pkg_energy_uj,0), 2) AS memory_pct,
    ROUND(a.background_energy_uj    * 100.0 / NULLIF(a.pkg_energy_uj,0), 2) AS background_pct,
    ROUND(a.llm_wait_energy_uj      * 100.0 / NULLIF(a.pkg_energy_uj,0), 2) AS llm_wait_pct,
    ROUND(a.llm_compute_energy_uj   * 100.0 / NULLIF(a.pkg_energy_uj,0), 2) AS application_pct,
    ROUND(a.orchestration_energy_uj * 100.0 / NULLIF(a.pkg_energy_uj,0), 2) AS orchestration_pct,
    ROUND(a.unattributed_energy_uj  * 100.0 / NULLIF(a.pkg_energy_uj,0), 2) AS unattributed_pct,
    a.attribution_coverage_pct,
    a.attribution_method,
    a.attribution_model_version
FROM energy_attribution a
JOIN runs r ON a.run_id = r.run_id;

-- 5. v_orchestration_overhead — unchanged logic, kept clean
CREATE VIEW v_orchestration_overhead AS
SELECT
    r.exp_id,
    r.run_id,
    r.workflow_type,
    a.orchestration_energy_uj / 1e6   AS orchestration_j,
    a.llm_wait_energy_uj      / 1e6   AS llm_wait_j,
    a.llm_compute_energy_uj   / 1e6   AS llm_compute_j,
    a.pkg_energy_uj           / 1e6   AS total_j,
    ROUND(
        r.orchestration_cpu_ms
        / NULLIF(CAST(r.task_duration_ns AS REAL) / 1e6, 0),
    4)                                AS ooi_time,
    a.planning_energy_uj  / 1e6       AS planning_j,
    a.execution_energy_uj / 1e6       AS execution_j,
    a.synthesis_energy_uj / 1e6       AS synthesis_j,
    r.planning_time_ms,
    r.execution_time_ms,
    r.synthesis_time_ms,
    r.llm_calls,
    r.tool_calls,
    r.steps
FROM energy_attribution a
JOIN runs r ON a.run_id = r.run_id;

-- 6. v_outcome_efficiency — unchanged, Chunk 8 dependent
CREATE VIEW v_outcome_efficiency AS
SELECT
    a.run_id,
    r.workflow_type,
    r.complexity_level,
    r.task_id,
    a.energy_per_completion_token_uj,
    a.energy_per_successful_step_uj,
    a.energy_per_accepted_answer_uj,
    a.energy_per_solved_task_uj,
    nf.difficulty_score,
    nf.difficulty_bucket,
    nf.successful_goals,
    nf.attempted_goals,
    nf.total_retries,
    CASE
        WHEN nf.attempted_goals > 0 AND nf.successful_goals > 0
        THEN CAST(nf.attempted_goals AS REAL) / nf.successful_goals
        ELSE NULL
    END AS attempt_efficiency_ratio
FROM energy_attribution a
JOIN runs r ON a.run_id = r.run_id
LEFT JOIN normalization_factors nf ON a.run_id = nf.run_id;
