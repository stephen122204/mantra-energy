-- queries/overview.sql
-- Overview metrics — all KPIs for the main dashboard
-- Works on SQLite and PostgreSQL (pure ANSI SQL)
-- Named params: none (aggregate query)

SELECT
    COUNT(DISTINCT e.exp_id)                                              AS total_experiments,
    COUNT(r.run_id)                                                       AS total_runs,
    SUM(CASE WHEN r.workflow_type = 'linear'  THEN 1 ELSE 0 END)         AS linear_runs,
    SUM(CASE WHEN r.workflow_type = 'agentic' THEN 1 ELSE 0 END)         AS agentic_runs,

    -- Energy
    AVG(CASE WHEN r.workflow_type = 'linear'  THEN r.total_energy_uj END) / 1e6  AS avg_linear_j,
    AVG(CASE WHEN r.workflow_type = 'agentic' THEN r.total_energy_uj END) / 1e6  AS avg_agentic_j,
    SUM(r.total_energy_uj) / 1e6                                          AS total_energy_j,
    MAX(r.total_energy_uj) / 1e6                                          AS max_energy_j,
    MIN(r.total_energy_uj) / 1e6                                          AS min_energy_j,
    AVG(r.avg_power_watts)                                                AS avg_power_w,

    -- Performance
    AVG(r.ipc)                                                            AS avg_ipc,
    MAX(r.ipc)                                                            AS max_ipc,
    AVG(r.cache_miss_rate) * 100                                          AS avg_cache_miss_pct,
    AVG(r.frequency_mhz)                                                  AS avg_freq_mhz,

    -- Tokens
    AVG(r.total_tokens)                                                   AS avg_tokens,
    AVG(r.energy_per_token)                                               AS avg_energy_per_token,

    -- Sustainability
    SUM(r.carbon_g) * 1000                                                AS total_carbon_mg,
    AVG(r.carbon_g) * 1000                                                AS avg_carbon_mg,
    AVG(r.water_ml)                                                       AS avg_water_ml,
    AVG(r.methane_mg)                                                     AS avg_methane_mg,

    -- Agentic phase timing
    AVG(CASE WHEN r.workflow_type = 'agentic' THEN r.planning_time_ms  END) AS avg_planning_ms,
    AVG(CASE WHEN r.workflow_type = 'agentic' THEN r.execution_time_ms END) AS avg_execution_ms,
    AVG(CASE WHEN r.workflow_type = 'agentic' THEN r.synthesis_time_ms END) AS avg_synthesis_ms,
    AVG(CASE WHEN r.workflow_type = 'agentic' THEN r.llm_calls         END) AS avg_llm_calls,
    AVG(CASE WHEN r.workflow_type = 'agentic' THEN r.tool_calls        END) AS avg_tool_calls,

    -- Data quality flags
    SUM(CASE WHEN r.experiment_valid = 0      THEN 1 ELSE 0 END)         AS invalid_runs,
    SUM(CASE WHEN r.thermal_throttle_flag = 1 THEN 1 ELSE 0 END)         AS throttled_runs,
    SUM(CASE WHEN r.background_cpu_percent > 10 THEN 1 ELSE 0 END)       AS noisy_env_runs,
    SUM(CASE WHEN r.baseline_id IS NULL       THEN 1 ELSE 0 END)         AS no_baseline_runs

FROM experiments e
LEFT JOIN runs r ON e.exp_id = r.exp_id
WHERE r.workflow_type IN ('linear', 'agentic')
