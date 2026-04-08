-- queries/recent_runs.sql
-- Recent runs with experiment metadata
-- Named params: :limit (default 50)

SELECT
    r.run_id,
    r.exp_id,
    r.workflow_type,
    r.run_number,
    r.total_energy_uj / 1e6         AS energy_j,
    r.dynamic_energy_uj / 1e6       AS dynamic_energy_j,
    r.avg_power_watts,
    r.duration_ns / 1e6             AS duration_ms,
    r.total_tokens,
    r.energy_per_token,
    r.ipc,
    r.cache_miss_rate,
    r.carbon_g,
    r.water_ml,
    r.planning_time_ms,
    r.execution_time_ms,
    r.synthesis_time_ms,
    r.experiment_valid,
    r.thermal_throttle_flag,
    r.background_cpu_percent,
    r.package_temp_celsius,
    r.thermal_delta_c,
    e.task_name,
    e.provider,
    e.model_name,
    e.country_code,
    e.name                          AS exp_name
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.workflow_type IN ('linear', 'agentic')
ORDER BY r.run_id DESC
LIMIT :limit
