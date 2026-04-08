Run drilldown — all metrics for one run
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