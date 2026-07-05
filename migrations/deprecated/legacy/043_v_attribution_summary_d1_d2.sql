-- Migration 043: Add D1 and D2 conservation-bounded percentage columns
-- to v_attribution_summary.
-- D1: llm_compute + orchestration = attributed (proven 100.0%)
-- D2: planning + execution + synthesis + inter_phase = attributed (proven ~100%)
-- These replace the old pkg-denominator percentages for paper cross-tab queries.
-- Backward compat: all existing columns retained per SC-5.

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
    ROUND(r.baseline_energy_uj     * 100.0 / NULLIF(a.pkg_energy_uj, 0), 2) AS baseline_pct_of_pkg,
    ROUND(r.dynamic_energy_uj      * 100.0 / NULLIF(a.pkg_energy_uj, 0), 2) AS dynamic_pct_of_pkg,
    ROUND(a.unattributed_energy_uj * 100.0 / NULLIF(a.pkg_energy_uj, 0), 2) AS unattributed_pct_of_pkg,
    -- L2: dynamic decomposition (denominator = dynamic)
    ROUND(a.background_energy_uj   * 100.0 / NULLIF(r.dynamic_energy_uj, 0), 2) AS background_pct_of_dynamic,
    ROUND(r.attributed_energy_uj   * 100.0 / NULLIF(r.dynamic_energy_uj, 0), 2) AS attributed_pct_of_dynamic,
    -- L3: attributed decomposition (denominator = attributed) — broad metrics
    ROUND(a.orchestration_energy_uj * 100.0 / NULLIF(r.attributed_energy_uj, 0), 2) AS orchestration_pct,
    ROUND(a.llm_wait_energy_uj      * 100.0 / NULLIF(r.attributed_energy_uj, 0), 2) AS llm_wait_pct,
    ROUND(a.llm_compute_energy_uj   * 100.0 / NULLIF(r.attributed_energy_uj, 0), 2) AS llm_compute_pct,
    ROUND(a.inter_phase_energy_uj   * 100.0 / NULLIF(r.attributed_energy_uj, 0), 2) AS inter_phase_pct,
    -- D1: conservation-bounded functional partition (sums to 100% of attributed)
    ROUND(a.llm_compute_energy_uj   * 100.0 / NULLIF(r.attributed_energy_uj, 0), 2) AS d1_llm_pct,
    ROUND(a.orchestration_energy_uj * 100.0 / NULLIF(r.attributed_energy_uj, 0), 2) AS d1_orch_pct,
    -- D2: conservation-bounded phase partition (sums to ~100% of attributed)
    ROUND(a.planning_energy_uj      * 100.0 / NULLIF(r.attributed_energy_uj, 0), 2) AS d2_plan_pct,
    ROUND(a.execution_energy_uj     * 100.0 / NULLIF(r.attributed_energy_uj, 0), 2) AS d2_exec_pct,
    ROUND(a.synthesis_energy_uj     * 100.0 / NULLIF(r.attributed_energy_uj, 0), 2) AS d2_syn_pct,
    ROUND(a.inter_phase_energy_uj   * 100.0 / NULLIF(r.attributed_energy_uj, 0), 2) AS d2_inter_pct,
    -- Coverage
    a.attribution_coverage_pct,
    r.phase_sample_coverage_pct,
    a.attribution_method,
    a.attribution_model_version
FROM energy_attribution a
JOIN runs r ON a.run_id = r.run_id;

INSERT INTO schema_version (version, applied_at, description)
VALUES (43, datetime('now'), 'v_attribution_summary: add D1/D2 conservation-bounded pct columns');
