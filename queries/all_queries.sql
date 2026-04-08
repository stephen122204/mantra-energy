-- ============================================================
-- A-LEMS Complete Query Library
-- All queries use named params (:param) — safe for SQLite + PG
-- No views — pure SQL with joins
-- Test: sqlite3 data/experiments.db < queries/all_queries.sql
-- ============================================================

-- ============================================================
-- SECTION 1: NORMALIZATION
-- Energy per query, per token, per second, per call
-- ============================================================

-- Q01: Energy per query by workflow and task
-- Sharp answer: what does ONE query cost?
SELECT
    e.task_name,
    e.provider,
    e.model_name,
    r.workflow_type,
    COUNT(*)                                                        AS run_count,
    AVG(r.pkg_energy_uj)   / 1e6                                   AS avg_pkg_j_per_query,
    AVG(r.core_energy_uj)  / 1e6                                   AS avg_core_j_per_query,
    AVG(r.uncore_energy_uj)/ 1e6                                   AS avg_uncore_j_per_query,
    AVG(r.dynamic_energy_uj)/ 1e6                                  AS avg_dynamic_j_per_query,
    MIN(r.pkg_energy_uj)   / 1e6                                   AS min_pkg_j_per_query,
    MAX(r.pkg_energy_uj)   / 1e6                                   AS max_pkg_j_per_query,
    -- Real power = energy/time (not stored avg_power_watts)
    AVG(r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9))            AS avg_power_w
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.pkg_energy_uj > 0
  AND r.duration_ns > 0
  AND r.experiment_valid = 1
GROUP BY e.task_name, e.provider, e.model_name, r.workflow_type
ORDER BY avg_pkg_j_per_query DESC;

-- Q02: Energy per token — linear vs agentic
-- Where tokens available (74% coverage)
SELECT
    e.task_name,
    e.provider,
    r.workflow_type,
    COUNT(*)                                                        AS run_count,
    AVG(r.total_tokens)                                            AS avg_tokens,
    AVG(r.dynamic_energy_uj / NULLIF(r.total_tokens, 0)) / 1e6   AS avg_j_per_token,
    AVG(r.pkg_energy_uj     / NULLIF(r.total_tokens, 0)) / 1e6   AS avg_pkg_j_per_token,
    -- Per 1k tokens
    AVG(r.dynamic_energy_uj / NULLIF(r.total_tokens, 0)) / 1e3   AS avg_mj_per_1k_tokens,
    MIN(r.dynamic_energy_uj / NULLIF(r.total_tokens, 0)) / 1e6   AS min_j_per_token,
    MAX(r.dynamic_energy_uj / NULLIF(r.total_tokens, 0)) / 1e6   AS max_j_per_token
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.total_tokens > 0
  AND r.dynamic_energy_uj > 0
  AND r.experiment_valid = 1
GROUP BY e.task_name, e.provider, r.workflow_type
ORDER BY avg_j_per_token DESC;

-- Q03: Energy per LLM call (agentic only)
SELECT
    e.task_name,
    e.provider,
    e.model_name,
    COUNT(*)                                                        AS run_count,
    AVG(r.llm_calls)                                               AS avg_llm_calls,
    AVG(r.tool_calls)                                              AS avg_tool_calls,
    AVG(r.dynamic_energy_uj / NULLIF(r.llm_calls,  0)) / 1e6     AS avg_j_per_llm_call,
    AVG(r.dynamic_energy_uj / NULLIF(r.tool_calls, 0)) / 1e6     AS avg_j_per_tool_call,
    AVG(r.dynamic_energy_uj / NULLIF(r.steps, 0))      / 1e6     AS avg_j_per_step
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.workflow_type = 'agentic'
  AND r.llm_calls > 0
  AND r.experiment_valid = 1
GROUP BY e.task_name, e.provider, e.model_name
ORDER BY avg_j_per_llm_call DESC;

-- Q04: Power profile — real power not stored avg_power_watts
SELECT
    e.task_name,
    r.workflow_type,
    COUNT(*)                                                        AS run_count,
    AVG(r.pkg_energy_uj   / 1e6 / (r.duration_ns / 1e9))          AS avg_pkg_power_w,
    AVG(r.core_energy_uj  / 1e6 / (r.duration_ns / 1e9))          AS avg_core_power_w,
    AVG(r.uncore_energy_uj/ 1e6 / (r.duration_ns / 1e9))          AS avg_uncore_power_w,
    MIN(r.pkg_energy_uj   / 1e6 / (r.duration_ns / 1e9))          AS min_power_w,
    MAX(r.pkg_energy_uj   / 1e6 / (r.duration_ns / 1e9))          AS max_power_w,
    AVG(r.duration_ns) / 1e9                                       AS avg_duration_s
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.pkg_energy_uj > 0
  AND r.duration_ns > 0
  AND r.experiment_valid = 1
GROUP BY e.task_name, r.workflow_type
ORDER BY avg_pkg_power_w DESC;

-- Q05: Prompt vs completion token energy split
SELECT
    r.workflow_type,
    AVG(r.prompt_tokens)                                           AS avg_prompt_tokens,
    AVG(r.completion_tokens)                                       AS avg_completion_tokens,
    AVG(r.total_tokens)                                            AS avg_total_tokens,
    AVG(r.prompt_tokens * 100.0 / NULLIF(r.total_tokens, 0))      AS prompt_share_pct,
    AVG(r.completion_tokens * 100.0 / NULLIF(r.total_tokens, 0))  AS completion_share_pct,
    -- Energy attributed proportionally to prompt vs completion
    AVG(r.dynamic_energy_uj / NULLIF(r.total_tokens, 0)
        * r.prompt_tokens) / 1e6                                  AS est_prompt_energy_j,
    AVG(r.dynamic_energy_uj / NULLIF(r.total_tokens, 0)
        * r.completion_tokens) / 1e6                              AS est_completion_energy_j
FROM runs r
WHERE r.total_tokens > 0
  AND r.prompt_tokens > 0
  AND r.experiment_valid = 1
GROUP BY r.workflow_type;

-- ============================================================
-- SECTION 2: SILICON ATTRIBUTION
-- pkg / core / uncore layer breakdown
-- ============================================================

-- Q06: Silicon domain attribution by task
SELECT
    e.task_name,
    r.workflow_type,
    COUNT(*)                                                        AS run_count,
    -- Layer shares
    AVG(r.core_energy_uj   * 100.0 / r.pkg_energy_uj)             AS avg_core_share_pct,
    AVG(r.uncore_energy_uj * 100.0 / r.pkg_energy_uj)             AS avg_uncore_share_pct,
    AVG((r.pkg_energy_uj - r.core_energy_uj - r.uncore_energy_uj)
        * 100.0 / r.pkg_energy_uj)                                 AS avg_other_share_pct,
    -- Absolute values
    AVG(r.core_energy_uj)   / 1e6                                  AS avg_core_j,
    AVG(r.uncore_energy_uj) / 1e6                                  AS avg_uncore_j,
    -- IPC correlation
    AVG(r.ipc)                                                     AS avg_ipc,
    AVG(r.cache_miss_rate)  * 100                                  AS avg_cache_miss_pct
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.pkg_energy_uj > 0
  AND r.core_energy_uj > 0
  AND r.experiment_valid = 1
GROUP BY e.task_name, r.workflow_type
ORDER BY avg_core_share_pct DESC;

-- Q07: Dynamic energy vs baseline energy
-- How much is workload vs idle system?
SELECT
    e.task_name,
    r.workflow_type,
    COUNT(*)                                                        AS run_count,
    AVG(r.dynamic_energy_uj) / 1e6                                 AS avg_dynamic_j,
    AVG(r.baseline_energy_uj)/ 1e6                                 AS avg_baseline_j,
    AVG(r.dynamic_energy_uj * 100.0 / NULLIF(r.pkg_energy_uj, 0)) AS dynamic_share_pct,
    AVG(r.baseline_energy_uj* 100.0 / NULLIF(r.pkg_energy_uj, 0)) AS baseline_share_pct
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.dynamic_energy_uj > 0
  AND r.experiment_valid = 1
GROUP BY e.task_name, r.workflow_type
ORDER BY dynamic_share_pct DESC;

-- Q08: C-state residency and energy efficiency
SELECT
    r.workflow_type,
    AVG(r.ipc)                                                     AS avg_ipc,
    AVG(r.frequency_mhz)                                           AS avg_freq_mhz,
    AVG(r.c2_time_seconds)                                         AS avg_c2_s,
    AVG(r.c3_time_seconds)                                         AS avg_c3_s,
    AVG(r.c6_time_seconds)                                         AS avg_c6_s,
    AVG(r.c7_time_seconds)                                         AS avg_c7_s,
    -- C-state sleep time as fraction of duration
    AVG((r.c2_time_seconds + r.c3_time_seconds + r.c6_time_seconds + r.c7_time_seconds)
        / NULLIF(r.duration_ns / 1e9, 0) * 100)                   AS sleep_time_pct,
    AVG(r.energy_per_instruction) * 1e9                           AS avg_nj_per_instruction
FROM runs r
WHERE r.ipc > 0
  AND r.experiment_valid = 1
GROUP BY r.workflow_type;

-- Q09: Cache miss impact on energy
SELECT
    CASE
        WHEN r.cache_miss_rate < 0.01 THEN 'low (<1%)'
        WHEN r.cache_miss_rate < 0.05 THEN 'medium (1-5%)'
        ELSE 'high (>5%)'
    END                                                            AS cache_miss_band,
    r.workflow_type,
    COUNT(*)                                                       AS run_count,
    AVG(r.cache_miss_rate * 100)                                   AS avg_cache_miss_pct,
    AVG(r.pkg_energy_uj) / 1e6                                    AS avg_pkg_j,
    AVG(r.ipc)                                                     AS avg_ipc,
    AVG(r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9))           AS avg_power_w
FROM runs r
WHERE r.cache_miss_rate IS NOT NULL
  AND r.cache_miss_rate >= 0
  AND r.experiment_valid = 1
GROUP BY cache_miss_band, r.workflow_type
ORDER BY avg_cache_miss_pct;

-- Q10: Thermal impact on energy
SELECT
    CASE
        WHEN r.package_temp_celsius < 50 THEN 'cool (<50C)'
        WHEN r.package_temp_celsius < 70 THEN 'warm (50-70C)'
        ELSE 'hot (>70C)'
    END                                                            AS temp_band,
    r.workflow_type,
    COUNT(*)                                                       AS run_count,
    AVG(r.package_temp_celsius)                                    AS avg_temp_c,
    AVG(r.thermal_delta_c)                                         AS avg_thermal_rise_c,
    AVG(r.pkg_energy_uj) / 1e6                                    AS avg_pkg_j,
    SUM(CASE WHEN r.thermal_throttle_flag = 1 THEN 1 ELSE 0 END)  AS throttled_count
FROM runs r
WHERE r.package_temp_celsius IS NOT NULL
  AND r.experiment_valid = 1
GROUP BY temp_band, r.workflow_type
ORDER BY avg_temp_c;

-- ============================================================
-- SECTION 3: ORCHESTRATION ATTRIBUTION
-- Agentic overhead — planning / execution / synthesis
-- ============================================================

-- Q11: Phase energy attribution (proportional by time)
SELECT
    e.task_name,
    e.provider,
    COUNT(*)                                                       AS run_count,
    AVG(r.planning_time_ms)                                        AS avg_planning_ms,
    AVG(r.execution_time_ms)                                       AS avg_execution_ms,
    AVG(r.synthesis_time_ms)                                       AS avg_synthesis_ms,
    -- Phase shares of total time
    AVG(r.planning_time_ms * 100.0 /
        NULLIF(r.planning_time_ms + r.execution_time_ms + r.synthesis_time_ms, 0))  AS planning_time_pct,
    AVG(r.execution_time_ms * 100.0 /
        NULLIF(r.planning_time_ms + r.execution_time_ms + r.synthesis_time_ms, 0))  AS execution_time_pct,
    AVG(r.synthesis_time_ms * 100.0 /
        NULLIF(r.planning_time_ms + r.execution_time_ms + r.synthesis_time_ms, 0))  AS synthesis_time_pct,
    -- Energy attributed proportionally to each phase
    AVG(r.dynamic_energy_uj / 1e6 * r.planning_time_ms /
        NULLIF(r.planning_time_ms + r.execution_time_ms + r.synthesis_time_ms, 0))  AS planning_energy_j,
    AVG(r.dynamic_energy_uj / 1e6 * r.execution_time_ms /
        NULLIF(r.planning_time_ms + r.execution_time_ms + r.synthesis_time_ms, 0))  AS execution_energy_j,
    AVG(r.dynamic_energy_uj / 1e6 * r.synthesis_time_ms /
        NULLIF(r.planning_time_ms + r.execution_time_ms + r.synthesis_time_ms, 0))  AS synthesis_energy_j
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.workflow_type = 'agentic'
  AND r.planning_time_ms > 0
  AND r.experiment_valid = 1
GROUP BY e.task_name, e.provider
ORDER BY avg_planning_ms DESC;

-- Q12: Orchestration tax — agentic overhead over linear baseline
SELECT
    e.task_name,
    e.provider,
    e.model_name,
    COUNT(ots.comparison_id)                                       AS pair_count,
    AVG(ots.tax_percent)                                           AS avg_tax_pct,
    AVG(ots.orchestration_tax_uj) / 1e6                           AS avg_tax_j,
    AVG(ots.linear_dynamic_uj)    / 1e6                           AS avg_linear_dynamic_j,
    AVG(ots.agentic_dynamic_uj)   / 1e6                           AS avg_agentic_dynamic_j,
    AVG(ots.agentic_dynamic_uj) / NULLIF(AVG(ots.linear_dynamic_uj), 0) AS tax_multiplier,
    MIN(ots.tax_percent)                                           AS min_tax_pct,
    MAX(ots.tax_percent)                                           AS max_tax_pct
FROM orchestration_tax_summary ots
JOIN runs rl ON ots.linear_run_id = rl.run_id
JOIN experiments e ON rl.exp_id = e.exp_id
GROUP BY e.task_name, e.provider, e.model_name
ORDER BY tax_multiplier DESC;

-- Q13: OOI — Orchestration Overhead Index
-- ooi_time = orchestration_cpu_ms / total_time_ms
-- ooi_cpu  = orchestration_cpu_ms / compute_time_ms
SELECT
    e.task_name,
    e.provider,
    COUNT(*)                                                       AS run_count,
    AVG(r.orchestration_cpu_ms / NULLIF(r.duration_ns / 1e6, 0)) AS avg_ooi_time,
    AVG(r.orchestration_cpu_ms / NULLIF(r.compute_time_ms, 0))   AS avg_ooi_cpu,
    AVG(r.compute_time_ms / NULLIF(r.duration_ns / 1e6, 0))      AS avg_ucr,
    AVG(r.orchestration_cpu_ms)                                   AS avg_orch_ms,
    AVG(r.compute_time_ms)                                        AS avg_compute_ms
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.workflow_type = 'agentic'
  AND r.orchestration_cpu_ms > 0
  AND r.compute_time_ms > 0
  AND r.experiment_valid = 1
GROUP BY e.task_name, e.provider
ORDER BY avg_ooi_time DESC;

-- Q14: LLM call efficiency — energy per useful token per call
SELECT
    e.task_name,
    e.provider,
    COUNT(*)                                                       AS run_count,
    AVG(r.llm_calls)                                              AS avg_llm_calls,
    AVG(r.total_tokens / NULLIF(r.llm_calls, 0))                 AS avg_tokens_per_call,
    AVG(r.dynamic_energy_uj / NULLIF(r.llm_calls, 0)) / 1e6     AS avg_j_per_call,
    -- Energy efficiency: tokens per joule
    AVG(r.total_tokens / NULLIF(r.dynamic_energy_uj / 1e6, 0))  AS avg_tokens_per_j
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.workflow_type = 'agentic'
  AND r.llm_calls > 0
  AND r.total_tokens > 0
  AND r.experiment_valid = 1
GROUP BY e.task_name, e.provider
ORDER BY avg_j_per_call DESC;

-- Q15: Network wait energy cost
-- Energy wasted waiting for API response
SELECT
    e.provider,
    r.workflow_type,
    COUNT(*)                                                       AS run_count,
    AVG(r.api_latency_ms)                                         AS avg_api_latency_ms,
    AVG(r.dns_latency_ms)                                         AS avg_dns_latency_ms,
    -- Energy during network wait = power × wait_time
    AVG(r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9)
        * r.api_latency_ms / 1e3)                                 AS avg_network_wait_j,
    AVG(r.api_latency_ms * 100.0 / NULLIF(r.duration_ns / 1e6, 0)) AS api_wait_pct,
    AVG(r.bytes_sent)                                             AS avg_bytes_sent,
    AVG(r.bytes_recv)                                             AS avg_bytes_recv
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.api_latency_ms > 0
  AND r.experiment_valid = 1
GROUP BY e.provider, r.workflow_type
ORDER BY avg_network_wait_j DESC;

-- ============================================================
-- SECTION 4: COMPARISON
-- Linear vs agentic, model vs model, task vs task
-- ============================================================

-- Q16: Linear vs agentic — direct comparison all metrics
SELECT
    e.task_name,
    e.provider,
    e.model_name,
    SUM(CASE WHEN r.workflow_type='linear'  THEN 1 ELSE 0 END)    AS linear_runs,
    SUM(CASE WHEN r.workflow_type='agentic' THEN 1 ELSE 0 END)    AS agentic_runs,
    -- Energy per query
    AVG(CASE WHEN r.workflow_type='linear'
        THEN r.pkg_energy_uj END) / 1e6                           AS linear_pkg_j,
    AVG(CASE WHEN r.workflow_type='agentic'
        THEN r.pkg_energy_uj END) / 1e6                           AS agentic_pkg_j,
    -- Tax multiplier
    AVG(CASE WHEN r.workflow_type='agentic' THEN r.pkg_energy_uj END) /
    NULLIF(AVG(CASE WHEN r.workflow_type='linear'
        THEN r.pkg_energy_uj END), 0)                             AS energy_multiplier,
    -- Power comparison
    AVG(CASE WHEN r.workflow_type='linear'
        THEN r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9) END)  AS linear_power_w,
    AVG(CASE WHEN r.workflow_type='agentic'
        THEN r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9) END)  AS agentic_power_w,
    -- Duration comparison
    AVG(CASE WHEN r.workflow_type='linear'
        THEN r.duration_ns END) / 1e9                             AS linear_duration_s,
    AVG(CASE WHEN r.workflow_type='agentic'
        THEN r.duration_ns END) / 1e9                             AS agentic_duration_s,
    -- Token comparison
    AVG(CASE WHEN r.workflow_type='linear'
        THEN r.total_tokens END)                                   AS linear_avg_tokens,
    AVG(CASE WHEN r.workflow_type='agentic'
        THEN r.total_tokens END)                                   AS agentic_avg_tokens
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.experiment_valid = 1
GROUP BY e.task_name, e.provider, e.model_name
HAVING linear_runs > 0 AND agentic_runs > 0
ORDER BY energy_multiplier DESC;

-- Q17: Model comparison — same task, different models
SELECT
    e.task_name,
    e.model_name,
    e.provider,
    r.workflow_type,
    COUNT(*)                                                       AS run_count,
    AVG(r.pkg_energy_uj)   / 1e6                                  AS avg_pkg_j,
    AVG(r.dynamic_energy_uj/ NULLIF(r.total_tokens, 0)) / 1e6    AS avg_j_per_token,
    AVG(r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9))           AS avg_power_w,
    AVG(r.total_tokens)                                           AS avg_tokens,
    AVG(r.duration_ns) / 1e9                                      AS avg_duration_s,
    AVG(r.ipc)                                                    AS avg_ipc
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.experiment_valid = 1
GROUP BY e.task_name, e.model_name, e.provider, r.workflow_type
ORDER BY e.task_name, avg_pkg_j;

-- Q18: Task domain energy profile
SELECT
    e.task_name,
    COUNT(*)                                                       AS total_runs,
    -- Energy
    AVG(r.pkg_energy_uj) / 1e6                                    AS avg_energy_j,
    AVG(r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9))           AS avg_power_w,
    AVG(r.dynamic_energy_uj / NULLIF(r.total_tokens, 0)) / 1e6   AS avg_j_per_token,
    -- Performance
    AVG(r.ipc)                                                    AS avg_ipc,
    AVG(r.frequency_mhz)                                          AS avg_freq_mhz,
    AVG(r.cache_miss_rate * 100)                                  AS avg_cache_miss_pct,
    -- Agentic tax
    AVG(CASE WHEN r.workflow_type='agentic'
        THEN r.pkg_energy_uj END) /
    NULLIF(AVG(CASE WHEN r.workflow_type='linear'
        THEN r.pkg_energy_uj END), 0)                             AS tax_multiplier,
    -- Sustainability
    AVG(r.carbon_g)                                               AS avg_carbon_g,
    AVG(r.water_ml)                                               AS avg_water_ml
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.experiment_valid = 1
GROUP BY e.task_name
ORDER BY avg_energy_j DESC;

-- Q19: Complexity scaling — does energy scale with complexity level?
SELECT
    r.complexity_level,
    r.workflow_type,
    COUNT(*)                                                       AS run_count,
    AVG(r.pkg_energy_uj) / 1e6                                    AS avg_energy_j,
    AVG(r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9))           AS avg_power_w,
    AVG(r.total_tokens)                                           AS avg_tokens,
    AVG(r.llm_calls)                                              AS avg_llm_calls,
    AVG(r.duration_ns) / 1e9                                      AS avg_duration_s
FROM runs r
WHERE r.complexity_level IS NOT NULL
  AND r.experiment_valid = 1
GROUP BY r.complexity_level, r.workflow_type
ORDER BY r.complexity_level, r.workflow_type;

-- Q20: Provider comparison — cloud vs local
SELECT
    e.provider,
    r.workflow_type,
    COUNT(*)                                                       AS run_count,
    AVG(r.pkg_energy_uj) / 1e6                                    AS avg_energy_j,
    AVG(r.dynamic_energy_uj / NULLIF(r.total_tokens, 0)) / 1e6   AS avg_j_per_token,
    AVG(r.api_latency_ms)                                         AS avg_api_latency_ms,
    AVG(r.dns_latency_ms)                                         AS avg_dns_latency_ms,
    AVG(r.total_tokens)                                           AS avg_tokens,
    AVG(r.carbon_g)                                               AS avg_carbon_g
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.experiment_valid = 1
GROUP BY e.provider, r.workflow_type
ORDER BY avg_energy_j;

-- ============================================================
-- SECTION 5: DATA QUALITY
-- ============================================================

-- Q21: Data coverage — which columns are populated
SELECT
    COUNT(*)                                                       AS total_runs,
    COUNT(CASE WHEN r.pkg_energy_uj > 0     THEN 1 END)           AS has_pkg_energy,
    COUNT(CASE WHEN r.core_energy_uj > 0    THEN 1 END)           AS has_core_energy,
    COUNT(CASE WHEN r.uncore_energy_uj > 0  THEN 1 END)           AS has_uncore_energy,
    COUNT(CASE WHEN r.dynamic_energy_uj > 0 THEN 1 END)           AS has_dynamic_energy,
    COUNT(CASE WHEN r.total_tokens > 0      THEN 1 END)           AS has_tokens,
    COUNT(CASE WHEN r.ipc > 0              THEN 1 END)            AS has_ipc,
    COUNT(CASE WHEN r.compute_time_ms > 0  THEN 1 END)            AS has_compute_time,
    COUNT(CASE WHEN r.orchestration_cpu_ms > 0 THEN 1 END)        AS has_orch_cpu,
    COUNT(CASE WHEN r.planning_time_ms > 0 THEN 1 END)            AS has_phases,
    COUNT(CASE WHEN r.baseline_id IS NOT NULL THEN 1 END)         AS has_baseline,
    COUNT(CASE WHEN r.experiment_valid = 1  THEN 1 END)           AS valid_runs,
    COUNT(CASE WHEN r.thermal_throttle_flag = 1 THEN 1 END)       AS throttled_runs,
    COUNT(CASE WHEN r.background_cpu_percent > 10 THEN 1 END)     AS noisy_runs
FROM runs r;

-- Q22: Outlier detection — energy anomalies
SELECT
    r.run_id,
    e.task_name,
    r.workflow_type,
    r.pkg_energy_uj / 1e6                                         AS pkg_j,
    r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9)                AS power_w,
    r.ipc,
    r.cache_miss_rate * 100                                        AS cache_miss_pct,
    r.package_temp_celsius,
    r.thermal_throttle_flag,
    r.background_cpu_percent,
    r.experiment_valid
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.pkg_energy_uj > (
    SELECT AVG(pkg_energy_uj) + 3 * AVG(pkg_energy_uj) * 0.5 FROM runs
)
OR r.experiment_valid = 0
OR r.thermal_throttle_flag = 1
ORDER BY r.pkg_energy_uj DESC
LIMIT 50;

-- Q23: Statistical sufficiency — how many runs per cell
SELECT
    e.task_name,
    e.model_name,
    r.workflow_type,
    COUNT(*)                                                       AS run_count,
    CASE
        WHEN COUNT(*) >= 30 THEN 'sufficient'
        WHEN COUNT(*) >= 10 THEN 'moderate'
        WHEN COUNT(*) >= 5  THEN 'low'
        ELSE 'insufficient'
    END                                                            AS sufficiency,
    AVG(r.pkg_energy_uj) / 1e6                                    AS avg_energy_j,
    -- Coefficient of variation (std/mean)
    (MAX(r.pkg_energy_uj) - MIN(r.pkg_energy_uj)) /
    NULLIF(AVG(r.pkg_energy_uj), 0) * 100                         AS energy_range_pct
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.experiment_valid = 1
GROUP BY e.task_name, e.model_name, r.workflow_type
ORDER BY run_count DESC;

-- Q24: Reproducibility — variance within same experiment
SELECT
    r.exp_id,
    e.task_name,
    e.provider,
    r.workflow_type,
    COUNT(*)                                                       AS run_count,
    AVG(r.pkg_energy_uj) / 1e6                                    AS avg_energy_j,
    MAX(r.pkg_energy_uj) / 1e6                                    AS max_energy_j,
    MIN(r.pkg_energy_uj) / 1e6                                    AS min_energy_j,
    (MAX(r.pkg_energy_uj) - MIN(r.pkg_energy_uj)) /
    NULLIF(AVG(r.pkg_energy_uj), 0) * 100                         AS range_pct
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.experiment_valid = 1
GROUP BY r.exp_id, e.task_name, e.provider, r.workflow_type
HAVING COUNT(*) > 1
ORDER BY range_pct DESC
LIMIT 20;

-- ============================================================
-- SECTION 6: SUSTAINABILITY ATTRIBUTION
-- ============================================================

-- Q25: Carbon per query by task and workflow
SELECT
    e.task_name,
    e.country_code,
    r.workflow_type,
    COUNT(*)                                                       AS run_count,
    AVG(r.carbon_g)                                               AS avg_carbon_g,
    AVG(r.carbon_g) * 1000                                        AS avg_carbon_mg,
    AVG(r.water_ml)                                               AS avg_water_ml,
    AVG(r.methane_mg)                                             AS avg_methane_mg,
    -- Per token sustainability
    AVG(r.carbon_g / NULLIF(r.total_tokens, 0)) * 1000           AS avg_carbon_mg_per_token,
    -- Agentic carbon tax
    AVG(CASE WHEN r.workflow_type='agentic' THEN r.carbon_g END) /
    NULLIF(AVG(CASE WHEN r.workflow_type='linear'
        THEN r.carbon_g END), 0)                                   AS carbon_multiplier
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.carbon_g > 0
  AND r.experiment_valid = 1
GROUP BY e.task_name, e.country_code, r.workflow_type
ORDER BY avg_carbon_g DESC;

-- Q26: Total environmental footprint
SELECT
    SUM(r.carbon_g)                                               AS total_carbon_g,
    SUM(r.carbon_g) * 1000                                        AS total_carbon_mg,
    SUM(r.water_ml)                                               AS total_water_ml,
    SUM(r.water_ml) / 1000                                        AS total_water_l,
    SUM(r.methane_mg)                                             AS total_methane_mg,
    -- Agentic overhead footprint
    SUM(CASE WHEN r.workflow_type='agentic' THEN r.carbon_g ELSE 0 END) -
    SUM(CASE WHEN r.workflow_type='linear'  THEN r.carbon_g ELSE 0 END) AS agentic_carbon_overhead_g,
    COUNT(*)                                                       AS total_runs,
    SUM(r.pkg_energy_uj) / 1e6                                    AS total_energy_j,
    SUM(r.pkg_energy_uj) / 1e9                                    AS total_energy_kj
FROM runs r
WHERE r.experiment_valid = 1;

-- ============================================================
-- SECTION 7: TIME SERIES AND TRENDS
-- ============================================================

-- Q27: Energy trend over time (by session)
SELECT
    e.group_id                                                     AS session_id,
    COUNT(DISTINCT e.exp_id)                                       AS experiments,
    COUNT(r.run_id)                                                AS runs,
    AVG(r.pkg_energy_uj) / 1e6                                    AS avg_energy_j,
    AVG(r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9))           AS avg_power_w,
    AVG(r.dynamic_energy_uj / NULLIF(r.total_tokens, 0)) / 1e6   AS avg_j_per_token,
    AVG(CASE WHEN r.workflow_type='agentic' THEN r.pkg_energy_uj END) /
    NULLIF(AVG(CASE WHEN r.workflow_type='linear'
        THEN r.pkg_energy_uj END), 0)                             AS tax_multiplier
FROM experiments e
JOIN runs r ON e.exp_id = r.exp_id
WHERE e.group_id IS NOT NULL
  AND r.experiment_valid = 1
GROUP BY e.group_id
ORDER BY e.group_id;

-- Q28: Run drilldown — all metrics for one run
-- Replace :run_id with actual run_id
SELECT
    r.run_id,
    r.exp_id,
    r.workflow_type,
    r.run_number,
    e.task_name,
    e.provider,
    e.model_name,
    -- MEASURED: Silicon energy
    r.pkg_energy_uj    / 1e6                                      AS pkg_j,
    r.core_energy_uj   / 1e6                                      AS core_j,
    r.uncore_energy_uj / 1e6                                      AS uncore_j,
    -- CALCULATED: Power
    r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9)                AS power_w,
    -- CALCULATED: Dynamic
    r.dynamic_energy_uj / 1e6                                     AS dynamic_j,
    r.baseline_energy_uj/ 1e6                                     AS baseline_j,
    -- CALCULATED: Silicon shares
    r.core_energy_uj   * 100.0 / r.pkg_energy_uj                  AS core_share_pct,
    r.uncore_energy_uj * 100.0 / r.pkg_energy_uj                  AS uncore_share_pct,
    -- MEASURED: Duration
    r.duration_ns / 1e9                                           AS duration_s,
    -- CALCULATED: Normalizations
    r.dynamic_energy_uj / NULLIF(r.total_tokens, 0) / 1e6        AS j_per_token,
    -- MEASURED: Performance
    r.ipc,
    r.cache_miss_rate * 100                                       AS cache_miss_pct,
    r.frequency_mhz,
    r.package_temp_celsius,
    r.thermal_delta_c,
    -- MEASURED: Tokens
    r.total_tokens,
    r.prompt_tokens,
    r.completion_tokens,
    -- MEASURED: Agentic phases
    r.planning_time_ms,
    r.execution_time_ms,
    r.synthesis_time_ms,
    r.llm_calls,
    r.tool_calls,
    -- INFERRED: Sustainability
    r.carbon_g,
    r.water_ml,
    r.methane_mg,
    -- Quality
    r.experiment_valid,
    r.thermal_throttle_flag,
    r.background_cpu_percent
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.run_id = :run_id;

-- Q29: LLM interaction breakdown for one run
SELECT
    li.interaction_id,
    li.step_index,
    li.workflow_type,
    li.prompt_tokens,
    li.completion_tokens,
    li.total_tokens,
    li.preprocess_ms,
    li.non_local_ms,
    li.local_compute_ms,
    li.postprocess_ms,
    li.total_time_ms,
    li.api_latency_ms,
    -- UCR for this interaction
    li.local_compute_ms / NULLIF(li.total_time_ms, 0)             AS ucr,
    -- Network ratio
    li.non_local_ms / NULLIF(li.total_time_ms, 0)                 AS network_ratio,
    li.status,
    li.error_message
FROM llm_interactions li
WHERE li.run_id = :run_id
ORDER BY li.step_index;

-- Q30: Energy samples timeseries for one run (power curve)
SELECT
    es.sample_id,
    es.timestamp_ns,
    (es.timestamp_ns - MIN(es.timestamp_ns) OVER ()) / 1e9         AS elapsed_s,
    es.pkg_energy_uj,
    es.core_energy_uj,
    es.uncore_energy_uj,
    -- Instantaneous power between samples
    (es.pkg_energy_uj - LAG(es.pkg_energy_uj) OVER (ORDER BY es.timestamp_ns)) /
    ((es.timestamp_ns - LAG(es.timestamp_ns) OVER (ORDER BY es.timestamp_ns)) / 1e9) / 1e6
                                                                   AS pkg_power_w
FROM energy_samples es
WHERE es.run_id = :run_id
ORDER BY es.timestamp_ns;
