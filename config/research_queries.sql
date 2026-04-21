-- ============================================================
-- A-LEMS Research Query Library
-- config/research_queries.sql
-- ============================================================
-- PURPOSE:
--   Canonical SQL queries for A-LEMS research analysis.
--   Used by:
--     - UI API endpoints (served as named queries)
--     - Paper figure generation
--     - Researcher exploratory analysis
--     - mkdocs research guide
--
-- QUERY NAMING:
--   RQ-01 through RQ-XX: Research Queries
--   VQ-01 through VQ-XX: Validation Queries
--   DQ-01 through DQ-XX: Diagnostic Queries
--
-- AUTHOR: Deepak Panigrahy
-- ============================================================


-- ============================================================
-- RQ-01: Time Budget Decomposition (The Gap Discovery)
-- ============================================================
-- Decomposes run wall-clock time into named components.
-- Discovered that ~50% of agentic run time is LLM API wait.
-- This finding motivates the phase taxonomy extension.
-- Paper: Section 5.2 "Execution Time Decomposition"
-- ============================================================
-- RQ-01: AGENTIC time budget
SELECT
    run_id,
    ROUND(task_duration_ns / 1e6, 2)                    AS task_duration_ms,
    ROUND(planning_time_ms, 2)                           AS planning_ms,
    ROUND(execution_time_ms, 2)                          AS execution_ms,
    ROUND(synthesis_time_ms, 2)                          AS synthesis_ms,
    ROUND(api_latency_ms, 2)                             AS api_wait_ms,
    ROUND(compute_time_ms, 2)                            AS orchestrator_cpu_ms,
    ROUND(task_duration_ns/1e6
          - planning_time_ms
          - execution_time_ms
          - synthesis_time_ms
          - api_latency_ms
          - compute_time_ms, 2)                          AS residual_ms,
    ROUND((planning_time_ms + execution_time_ms
           + synthesis_time_ms) * 100.0
          / NULLIF(task_duration_ns/1e6, 0), 2)          AS phase_pct,
    ROUND(api_latency_ms * 100.0
          / NULLIF(task_duration_ns/1e6, 0), 2)          AS api_wait_pct,
    ROUND(framework_overhead_ns / 1e6, 2)                AS framework_overhead_ms
FROM runs
WHERE workflow_type = 'agentic'
  AND task_duration_ns IS NOT NULL
ORDER BY run_id DESC;

-- RQ-01b: LINEAR time budget
SELECT
    run_id,
    ROUND(task_duration_ns / 1e6, 2)                    AS task_duration_ms,
    ROUND(api_latency_ms, 2)                             AS api_wait_ms,
    ROUND(compute_time_ms, 2)                            AS compute_ms,
    ROUND(task_duration_ns/1e6
          - api_latency_ms
          - compute_time_ms, 2)                          AS residual_ms,
    ROUND(api_latency_ms * 100.0
          / NULLIF(task_duration_ns/1e6, 0), 2)          AS api_pct,
    ROUND(framework_overhead_ns / 1e6, 2)                AS framework_overhead_ms
FROM runs
WHERE workflow_type = 'linear'
  AND task_duration_ns IS NOT NULL
ORDER BY run_id DESC;


-- ============================================================
-- RQ-02: Power Profile During Phases vs API Wait
-- ============================================================
-- Measures actual CPU power during active phases vs blocking wait.
-- KEY FINDING: Power drops 61% during API wait on large runs.
-- Proves current time-fraction attribution overestimates wait energy.
-- Paper: Section 5.3 "Phase Power Profile"
-- ============================================================
-- Usage: Replace :run_id with target run_id
-- Example: .param set :run_id 1873
SELECT
    oe.phase,
    oe.event_type,
    ROUND((oe.end_time_ns - oe.start_time_ns) / 1e6, 2)  AS duration_ms,
    COUNT(es.sample_id)                                    AS energy_samples,
    ROUND(SUM(es.pkg_end_uj - es.pkg_start_uj) / 1e6, 4) AS energy_j,
    ROUND(AVG(
        (es.pkg_end_uj - es.pkg_start_uj)
        / CAST((es.sample_end_ns - es.sample_start_ns) AS REAL) * 1e3
    ), 3)                                                  AS avg_power_mw,
    ROUND(MAX(
        (es.pkg_end_uj - es.pkg_start_uj)
        / CAST((es.sample_end_ns - es.sample_start_ns) AS REAL) * 1e3
    ), 3)                                                  AS max_power_mw
FROM orchestration_events oe
LEFT JOIN energy_samples es
       ON es.run_id = oe.run_id
      AND es.sample_start_ns >= oe.start_time_ns
      AND es.sample_end_ns   <= oe.end_time_ns
WHERE oe.run_id = :run_id
GROUP BY oe.event_id
ORDER BY oe.start_time_ns;


-- ============================================================
-- RQ-03: Measurement Coverage Distribution
-- ============================================================
-- Validates energy sample completeness across all runs.
-- Used to identify runs with measurement gaps for exclusion.
-- Paper: Section 4.4 "Measurement Validity"
-- ============================================================
SELECT
    workflow_type,
    COUNT(*)                                               AS total_runs,
    COUNT(CASE WHEN energy_sample_coverage_pct >= 95
               THEN 1 END)                                 AS gold_coverage,
    COUNT(CASE WHEN energy_sample_coverage_pct >= 80
                AND energy_sample_coverage_pct < 95
               THEN 1 END)                                 AS ok_coverage,
    COUNT(CASE WHEN energy_sample_coverage_pct < 80
               THEN 1 END)                                 AS poor_coverage,
    ROUND(AVG(energy_sample_coverage_pct), 2)              AS avg_coverage_pct,
    ROUND(AVG(framework_overhead_ns / 1e6), 2)             AS avg_framework_ms,
    ROUND(AVG(framework_overhead_ns * 100.0
              / NULLIF(total_run_duration_ns, 0)), 2)       AS avg_overhead_pct
FROM runs
WHERE task_duration_ns IS NOT NULL
GROUP BY workflow_type;


-- ============================================================
-- RQ-04: Framework Overhead Tax
-- ============================================================
-- Quantifies A-LEMS measurement overhead as % of task time.
-- Proves the measurement system is lightweight.
-- Paper: Section 6.5 "Measurement Overhead"
-- ============================================================
SELECT
    workflow_type,
    COUNT(*)                                               AS runs,
    ROUND(AVG(framework_overhead_ns / 1e6), 2)             AS avg_overhead_ms,
    ROUND(MIN(framework_overhead_ns / 1e6), 2)             AS min_overhead_ms,
    ROUND(MAX(framework_overhead_ns / 1e6), 2)             AS max_overhead_ms,
    ROUND(AVG(framework_overhead_ns * 100.0
              / NULLIF(total_run_duration_ns, 0)), 3)       AS avg_overhead_pct,
    ROUND(AVG(task_duration_ns / 1e6), 2)                  AS avg_task_ms
FROM runs
WHERE task_duration_ns IS NOT NULL
  AND framework_overhead_ns IS NOT NULL
  AND duration_includes_overhead = 0   -- new corrected runs only
GROUP BY workflow_type;


-- ============================================================
-- RQ-05: Energy Attribution Hierarchy
-- ============================================================
-- Full L0-L5 energy decomposition per run.
-- Primary attribution table query for paper tables.
-- Paper: Section 5.1 "Multi-Layer Energy Attribution"
-- ============================================================
SELECT
    r.run_id,
    r.workflow_type,
    -- L0: Hardware
    ROUND(a.pkg_energy_uj / 1e6, 4)              AS L0_pkg_j,
    ROUND(a.core_energy_uj / 1e6, 4)             AS L0_core_j,
    ROUND(a.dram_energy_uj / 1e6, 4)             AS L0_dram_j,
    -- L1: Baseline isolation
    ROUND(r.baseline_energy_uj / 1e6, 4)         AS L1_baseline_j,
    ROUND(r.dynamic_energy_uj / 1e6, 4)          AS L1_dynamic_j,
    -- L2: Process isolation
    ROUND(r.attributed_energy_uj / 1e6, 4)       AS L2_attributed_j,
    ROUND(r.cpu_fraction, 4)                      AS L2_cpu_fraction,
    -- L3: Workflow decomposition
    ROUND(a.planning_energy_uj / 1e6, 4)         AS L3_planning_j,
    ROUND(a.execution_energy_uj / 1e6, 4)        AS L3_execution_j,
    ROUND(a.synthesis_energy_uj / 1e6, 4)        AS L3_synthesis_j,
    ROUND(a.orchestration_energy_uj / 1e6, 4)    AS L3_orchestration_j,
    -- L4: Model compute
    ROUND(a.llm_compute_energy_uj / 1e6, 4)      AS L4_llm_compute_j,
    -- L5: Outcome
    ROUND(a.energy_per_completion_token_uj, 2)   AS L5_uj_per_token,
    ROUND(a.energy_per_successful_step_uj, 2)    AS L5_uj_per_step,
    -- Attribution quality
    a.attribution_coverage_pct,
    r.energy_sample_coverage_pct
FROM runs r
JOIN energy_attribution a ON r.run_id = a.run_id
WHERE r.task_duration_ns IS NOT NULL
ORDER BY r.run_id DESC;


-- ============================================================
-- RQ-06: Orchestration Tax (Core Thesis Metric)
-- ============================================================
-- Compares agentic vs linear energy per experiment.
-- τ_orch = (E_agentic - E_linear) / E_linear
-- Paper: Section 5.4 "Orchestration Tax"
-- ============================================================
SELECT
    la.run_id                                             AS linear_run_id,
    ag.run_id                                             AS agentic_run_id,
    lr.exp_id,
    -- Total energy comparison
    ROUND(la.pkg_energy_uj / 1e6, 4)                     AS linear_total_j,
    ROUND(aa.pkg_energy_uj / 1e6, 4)                     AS agentic_total_j,
    -- Attributed energy comparison
    ROUND(lr.attributed_energy_uj / 1e6, 4)              AS linear_attributed_j,
    ROUND(ar.attributed_energy_uj / 1e6, 4)              AS agentic_attributed_j,
    -- Orchestration tax (absolute)
    ROUND((ar.attributed_energy_uj - lr.attributed_energy_uj) / 1e6, 4) AS tax_j,
    -- Orchestration tax ratio τ_orch
    ROUND((ar.attributed_energy_uj - lr.attributed_energy_uj) * 1.0
          / NULLIF(lr.attributed_energy_uj, 0), 4)        AS tau_orch,
    -- Agentic overhead ratio ρ_agent = E_agentic / E_linear
    ROUND(aa.pkg_energy_uj * 1.0
          / NULLIF(la.pkg_energy_uj, 0), 4)               AS rho_agent,
    -- Planning + synthesis as orchestration overhead
    ROUND((aa.planning_energy_uj + aa.synthesis_energy_uj) * 1.0
          / NULLIF(ar.attributed_energy_uj, 0), 4)        AS orchestration_tax_ratio,
    -- Token efficiency comparison
    ROUND(la.energy_per_completion_token_uj, 2)           AS linear_uj_per_token,
    ROUND(aa.energy_per_completion_token_uj, 2)           AS agentic_uj_per_token
FROM runs lr
JOIN runs ar        ON lr.exp_id = ar.exp_id
                   AND ar.workflow_type = 'agentic'
JOIN energy_attribution la ON lr.run_id = la.run_id
JOIN energy_attribution aa ON ar.run_id = aa.run_id
WHERE lr.workflow_type = 'linear'
  AND lr.task_duration_ns IS NOT NULL
  AND ar.task_duration_ns IS NOT NULL
ORDER BY lr.exp_id DESC;


-- ============================================================
-- RQ-07: Baseline Validity Check
-- ============================================================
-- Identifies runs where baseline_energy > pkg_energy (invalid).
-- 32 such runs found in 1873-run dataset.
-- Paper: Section 4.3 "Baseline Isolation Validity"
-- ============================================================
SELECT
    run_id,
    workflow_type,
    pkg_energy_uj,
    baseline_energy_uj,
    dynamic_energy_uj,
    pkg_energy_uj - baseline_energy_uj          AS computed_dynamic_uj,
    dynamic_energy_uj
        - (pkg_energy_uj - baseline_energy_uj)  AS delta_uj,
    CASE
        WHEN baseline_energy_uj > pkg_energy_uj THEN 'baseline_gt_pkg'
        WHEN dynamic_energy_uj < 0              THEN 'negative_dynamic'
        ELSE 'valid'
    END                                          AS validity_reason
FROM runs
WHERE baseline_energy_uj > pkg_energy_uj
   OR dynamic_energy_uj < 0
ORDER BY ABS(dynamic_energy_uj
             - (pkg_energy_uj - baseline_energy_uj)) DESC;


-- ============================================================
-- RQ-08: CPU Fraction vs Wall Compute Ratio Divergence
-- ============================================================
-- Compares cpu_fraction (tick-based) vs UCR (wall-time-based).
-- Divergence reveals memory-bound vs compute-bound workloads.
-- Paper: Section 5.5 "Attribution Signal Comparison"
-- ============================================================
SELECT
    run_id,
    workflow_type,
    ROUND(cpu_fraction, 4)                               AS cpu_share_ratio,
    ROUND(compute_time_ms
          / NULLIF(task_duration_ns / 1e6, 0), 4)        AS wall_compute_ratio,
    ROUND(cpu_fraction
          - compute_time_ms
          / NULLIF(task_duration_ns / 1e6, 0), 4)        AS divergence,
    CASE
        WHEN cpu_fraction > 0.7 AND
             compute_time_ms / NULLIF(task_duration_ns/1e6,0) < 0.1
        THEN 'HIGH_TICK_LOW_WALL: IO-wait or memory stall'
        WHEN cpu_fraction < 0.2
        THEN 'LOW_ATTRIBUTION: background noise dominant'
        ELSE 'normal'
    END                                                   AS interpretation,
    ROUND(task_duration_ns / 1e6, 2)                     AS task_ms,
    ROUND(compute_time_ms, 2)                             AS compute_ms
FROM runs
WHERE task_duration_ns IS NOT NULL
  AND cpu_fraction IS NOT NULL
ORDER BY ABS(cpu_fraction
             - compute_time_ms
               / NULLIF(task_duration_ns/1e6, 0)) DESC
LIMIT 50;


-- ============================================================
-- RQ-09: Energy Sample Coverage by Run (Measurement Audit)
-- ============================================================
-- Full coverage audit: sample span vs task duration.
-- Used to validate historical runs and identify data quality issues.
-- Paper: Appendix A "Data Quality Audit"
-- ============================================================
SELECT
    r.run_id,
    r.workflow_type,
    ROUND(r.task_duration_ns / 1e6, 2)                   AS task_ms,
    ROUND((MAX(es.sample_end_ns)
           - MIN(es.sample_start_ns)) / 1e6, 2)          AS sample_span_ms,
    r.energy_sample_coverage_pct,
    COUNT(es.sample_id)                                   AS sample_count,
    ROUND(r.framework_overhead_ns / 1e6, 2)              AS framework_ms,
    CASE
        WHEN r.energy_sample_coverage_pct >= 95 THEN 'gold'
        WHEN r.energy_sample_coverage_pct >= 80 THEN 'acceptable'
        ELSE 'poor'
    END                                                   AS coverage_grade
FROM runs r
JOIN energy_samples es ON r.run_id = es.run_id
WHERE r.task_duration_ns IS NOT NULL
GROUP BY r.run_id
ORDER BY r.energy_sample_coverage_pct ASC;


-- ============================================================
-- RQ-10: Corrected Power Profile (post v9)
-- ============================================================
-- Compares legacy avg_power_watts vs corrected avg_task_power_watts.
-- Shows magnitude of measurement boundary bug.
-- Paper: Section 4.2 "Measurement Boundary Correction"
-- ============================================================
SELECT
    r.run_id,
    r.workflow_type,
    ROUND(r.avg_power_watts, 3)                          AS legacy_power_w,
    ROUND(r.avg_task_power_watts, 3)                     AS corrected_power_w,
    ROUND(r.avg_task_power_watts
          - r.avg_power_watts, 3)                        AS power_delta_w,
    ROUND((r.avg_task_power_watts - r.avg_power_watts)
          * 100.0 / NULLIF(r.avg_power_watts, 0), 2)     AS pct_understatement,
    ROUND(r.task_duration_ns / 1e6, 2)                   AS task_ms,
    ROUND(r.total_run_duration_ns / 1e6, 2)              AS total_ms,
    ROUND(r.framework_overhead_ns / 1e6, 2)              AS overhead_ms
FROM runs r
WHERE r.avg_task_power_watts IS NOT NULL
  AND r.avg_power_watts IS NOT NULL
ORDER BY r.run_id DESC
LIMIT 50;


-- ============================================================
-- VQ-01: Attribution Layer Conservation Check
-- ============================================================
-- Validates that L1 conservation holds: dynamic + baseline = pkg.
-- Expected: 1841/1873 valid (32 baseline anomalies known).
-- ============================================================
SELECT
    COUNT(*)                                              AS total,
    COUNT(CASE WHEN ABS(dynamic_energy_uj
                        - (pkg_energy_uj - baseline_energy_uj)) < 1000
               THEN 1 END)                               AS l1_valid,
    COUNT(CASE WHEN ABS(dynamic_energy_uj
                        - (pkg_energy_uj - baseline_energy_uj)) >= 1000
               THEN 1 END)                               AS l1_anomaly,
    COUNT(CASE WHEN baseline_energy_uj > pkg_energy_uj
               THEN 1 END)                               AS baseline_gt_pkg
FROM runs
WHERE pkg_energy_uj IS NOT NULL
  AND baseline_energy_uj IS NOT NULL
  AND dynamic_energy_uj IS NOT NULL;


-- ============================================================
-- VQ-02: L2 Conservation Check
-- ============================================================
-- Validates: attributed = cpu_fraction × dynamic (within 0.1%).
-- ============================================================
SELECT
    COUNT(*)                                              AS total,
    COUNT(CASE WHEN ABS(attributed_energy_uj
                        - cpu_fraction * dynamic_energy_uj)
                    / NULLIF(attributed_energy_uj, 0) < 0.001
               THEN 1 END)                               AS l2_valid,
    ROUND(AVG(ABS(attributed_energy_uj
                  - cpu_fraction * dynamic_energy_uj)
              / NULLIF(attributed_energy_uj, 0)) * 100, 4) AS avg_error_pct
FROM runs
WHERE attributed_energy_uj IS NOT NULL
  AND cpu_fraction IS NOT NULL
  AND dynamic_energy_uj IS NOT NULL;


-- ============================================================
-- DQ-01: Phase Energy Alignment Check
-- ============================================================
-- Compares phase energy from orchestration_events vs runs table.
-- Runs table populated by Chunk 5 ETL.
-- Events table event_energy_uj = NULL (not yet populated).
-- ============================================================
SELECT
    r.run_id,
    r.workflow_type,
    r.planning_energy_uj                                 AS runs_planning_uj,
    r.execution_energy_uj                                AS runs_execution_uj,
    r.synthesis_energy_uj                                AS runs_synthesis_uj,
    SUM(oe.event_energy_uj)                              AS events_energy_uj,
    COUNT(oe.event_id)                                   AS event_count,
    COUNT(CASE WHEN oe.event_energy_uj IS NOT NULL
               THEN 1 END)                               AS events_with_energy
FROM runs r
LEFT JOIN orchestration_events oe ON r.run_id = oe.run_id
WHERE r.workflow_type = 'agentic'
GROUP BY r.run_id
ORDER BY r.run_id DESC
LIMIT 10;
