-- Migration 037: Phase Attribution v2 schema additions + view fixes
-- Adds inter_phase_energy_uj and phase_sample_coverage_pct to runs.
-- Fixes v_fraction_verification to use attributed_energy_uj denominator.
-- Fixes v_attribution_summary to use correct denominators per energy layer.
-- Fixes v_energy_normalized orchestration_ratio denominator.
-- Fixes v_goal_energy_decomposition pct calculations.
--
-- Run: sqlite3 data/experiments.db < scripts/migrations/037_phase_attribution_v2.sql
-- After: python scripts/etl/phase_attribution_etl.py --backfill-all
--        python scripts/test_provenance.sh

PRAGMA foreign_keys = OFF;

-- ── runs table: new phase v2 columns ─────────────────────────────────────────
-- inter_phase_energy_uj: energy between phase boundaries (Python overhead,
--   tool dispatch, framework calls). v1 forced this to 0 by normalization.
--   v2 measures it honestly as attributed - SUM(phase energies).
ALTER TABLE runs ADD COLUMN inter_phase_energy_uj     INTEGER;
ALTER TABLE runs ADD COLUMN phase_sample_coverage_pct REAL;

-- ── energy_attribution table: inter_phase column ─────────────────────────────
ALTER TABLE energy_attribution ADD COLUMN inter_phase_energy_uj INTEGER;

-- ── Fix v_fraction_verification ──────────────────────────────────────────────
-- Was: orch / pkg_energy_uj  (wrong — pkg includes idle + other processes)
-- Now: orch / attributed_energy_uj  (correct — orch is derived from attributed)
-- Formula: f_orch = E_orch / E_attributed
DROP VIEW IF EXISTS v_fraction_verification;
CREATE VIEW v_fraction_verification AS
SELECT
    ge.goal_id,
    ge.winning_run_id,
    ea.orchestration_energy_uj              AS numerator_uj,
    ea.attributed_energy_uj                 AS denominator_uj,
    'E_orch / E_attributed'                 AS formula,
    CASE WHEN ea.attributed_energy_uj > 0
        THEN ROUND(
            1.0 * ea.orchestration_energy_uj / ea.attributed_energy_uj, 6)
        ELSE NULL
    END                                     AS recomputed_fraction,
    ge.orchestration_fraction               AS stored_fraction,
    CASE WHEN ea.attributed_energy_uj > 0
        THEN ROUND(ABS(ge.orchestration_fraction -
            1.0 * ea.orchestration_energy_uj / ea.attributed_energy_uj), 8)
        ELSE NULL
    END                                     AS delta
FROM goal_execution ge
LEFT JOIN runs r              ON r.run_id  = ge.winning_run_id
LEFT JOIN energy_attribution ea ON ea.run_id = ge.winning_run_id
WHERE ge.orchestration_fraction IS NOT NULL;

-- ── Fix v_attribution_summary ────────────────────────────────────────────────
-- Percentages now use correct denominators per energy hierarchy layer:
--   pkg-level metrics: / pkg
--   dynamic-level:     / dynamic
--   process-level:     / attributed
DROP VIEW IF EXISTS v_attribution_summary;
CREATE VIEW v_attribution_summary AS
SELECT
    a.run_id,
    r.workflow_type,
    -- Absolute Joules
    a.pkg_energy_uj           / 1e6  AS pkg_j,
    r.baseline_energy_uj      / 1e6  AS baseline_j,
    r.dynamic_energy_uj       / 1e6  AS dynamic_j,
    a.background_energy_uj    / 1e6  AS background_j,
    r.attributed_energy_uj    / 1e6  AS attributed_j,
    a.orchestration_energy_uj / 1e6  AS orchestration_j,
    a.llm_wait_energy_uj      / 1e6  AS llm_wait_j,
    a.llm_compute_energy_uj   / 1e6  AS llm_compute_j,
    a.planning_energy_uj      / 1e6  AS planning_j,
    a.execution_energy_uj     / 1e6  AS execution_j,
    a.synthesis_energy_uj     / 1e6  AS synthesis_j,
    a.inter_phase_energy_uj   / 1e6  AS inter_phase_j,
    a.thermal_penalty_energy_uj / 1e6 AS thermal_j,
    a.unattributed_energy_uj  / 1e6  AS unattributed_j,
    -- L1: pkg decomposition (denominator = pkg)
    ROUND(r.baseline_energy_uj   * 100.0 / NULLIF(a.pkg_energy_uj, 0), 2) AS baseline_pct_of_pkg,
    ROUND(r.dynamic_energy_uj    * 100.0 / NULLIF(a.pkg_energy_uj, 0), 2) AS dynamic_pct_of_pkg,
    ROUND(a.unattributed_energy_uj * 100.0 / NULLIF(a.pkg_energy_uj, 0), 2) AS unattributed_pct_of_pkg,
    -- L2: dynamic decomposition (denominator = dynamic)
    ROUND(a.background_energy_uj  * 100.0 / NULLIF(r.dynamic_energy_uj, 0), 2) AS background_pct_of_dynamic,
    ROUND(r.attributed_energy_uj  * 100.0 / NULLIF(r.dynamic_energy_uj, 0), 2) AS attributed_pct_of_dynamic,
    -- L3: attributed decomposition (denominator = attributed)
    -- These are the paper's primary figures
    ROUND(a.orchestration_energy_uj * 100.0 / NULLIF(r.attributed_energy_uj, 0), 2) AS orchestration_pct,
    ROUND(a.llm_wait_energy_uj      * 100.0 / NULLIF(r.attributed_energy_uj, 0), 2) AS llm_wait_pct,
    ROUND(a.llm_compute_energy_uj   * 100.0 / NULLIF(r.attributed_energy_uj, 0), 2) AS llm_compute_pct,
    ROUND(a.inter_phase_energy_uj   * 100.0 / NULLIF(r.attributed_energy_uj, 0), 2) AS inter_phase_pct,
    -- Coverage
    a.attribution_coverage_pct,
    r.phase_sample_coverage_pct,
    a.attribution_method,
    a.attribution_model_version
FROM energy_attribution a
JOIN runs r ON a.run_id = r.run_id;

-- ── Fix v_energy_normalized ───────────────────────────────────────────────────
-- orchestration_ratio: was orch/pkg, now orch/attributed (correct denominator)
DROP VIEW IF EXISTS v_energy_normalized;
CREATE VIEW v_energy_normalized AS
SELECT
    a.run_id,
    r.workflow_type,
    r.complexity_level,
    a.pkg_energy_uj  / 1e6                                              AS total_energy_j,
    a.core_energy_uj / 1e6                                              AS compute_energy_j,
    a.dram_energy_uj / 1e6                                              AS memory_energy_j,
    a.background_energy_uj / 1e6                                        AS background_energy_j,
    r.attributed_energy_uj / 1e6                                        AS attributed_energy_j,
    a.llm_wait_energy_uj / 1e6                                          AS llm_wait_energy_j,
    a.llm_compute_energy_uj / 1e6                                       AS llm_compute_energy_j,
    a.orchestration_energy_uj / 1e6                                     AS orchestration_energy_j,
    a.inter_phase_energy_uj / 1e6                                       AS inter_phase_energy_j,
    -- Per-token normalisation (µJ)
    a.pkg_energy_uj / NULLIF(l.total_tokens, 0)                         AS energy_per_token_uj,
    -- Corrected power: task_duration_ns not duration_ns (Chunk 6 duration fix)
    a.pkg_energy_uj / 1e6
        / NULLIF(CAST(r.task_duration_ns AS REAL) / 1e9, 0)             AS avg_power_watts,
    -- Fractions — all use attributed as denominator for process-level metrics
    -- Formula: f_orch = E_orch / E_attributed
    a.orchestration_energy_uj
        / NULLIF(CAST(r.attributed_energy_uj AS REAL), 0)               AS orchestration_ratio,
    a.llm_wait_energy_uj
        / NULLIF(CAST(r.attributed_energy_uj AS REAL), 0)               AS llm_wait_ratio,
    a.llm_compute_energy_uj
        / NULLIF(CAST(r.attributed_energy_uj AS REAL), 0)               AS llm_compute_ratio,
    a.inter_phase_energy_uj
        / NULLIF(CAST(r.attributed_energy_uj AS REAL), 0)               AS inter_phase_ratio,
    a.llm_compute_energy_uj
        / NULLIF(CAST(a.orchestration_energy_uj AS REAL), 0)            AS compute_vs_overhead_ratio,
    a.unattributed_energy_uj
        / NULLIF(CAST(a.pkg_energy_uj AS REAL), 0)                      AS unattributed_ratio,
    a.attribution_coverage_pct,
    r.phase_sample_coverage_pct,
    a.attribution_method,
    -- Outcome normalised costs
    a.energy_per_completion_token_uj,
    a.energy_per_successful_step_uj,
    a.energy_per_accepted_answer_uj,
    a.energy_per_solved_task_uj,
    -- Thermal
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

-- ── Fix v_goal_energy_decomposition ──────────────────────────────────────────
-- compute_pct and orchestration_pct: use attributed not pkg as denominator
DROP VIEW IF EXISTS v_goal_energy_decomposition;
CREATE VIEW v_goal_energy_decomposition AS
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
    ea.inter_phase_energy_uj    / 1e6  AS inter_phase_energy_j,
    -- Percentages: use attributed as denominator (process-level metrics)
    -- Formula: pct = E_component / E_attributed × 100
    ROUND(ea.llm_compute_energy_uj   * 100.0
          / NULLIF(r.attributed_energy_uj, 0), 2)   AS compute_pct,
    ROUND(ea.orchestration_energy_uj * 100.0
          / NULLIF(r.attributed_energy_uj, 0), 2)   AS orchestration_pct,
    ROUND(ea.inter_phase_energy_uj   * 100.0
          / NULLIF(r.attributed_energy_uj, 0), 2)   AS inter_phase_pct,
    CASE WHEN ge.total_attempts > 1 THEN 1 ELSE 0
    END                                             AS had_retry,
    e.experiment_type,
    e.experiment_goal
FROM goal_execution ge
JOIN experiments e    ON ge.exp_id = e.exp_id
LEFT JOIN runs r      ON r.run_id  = ge.winning_run_id
LEFT JOIN energy_attribution ea ON ge.winning_run_id = ea.run_id
WHERE e.experiment_type IN (
    'normal','overhead_study','retry_study',
    'failure_injection','quality_sweep','ablation','pilot'
);

PRAGMA foreign_key_check;
PRAGMA integrity_check;
