-- queries/runs_by_experiment.sql
-- All runs for one experiment, ordered by run number
-- Named params: :exp_id (required)

SELECT
    r.run_id,
    r.run_number,
    r.workflow_type,
    r.total_energy_uj / 1e6     AS energy_j,
    r.dynamic_energy_uj / 1e6   AS dynamic_energy_j,
    r.avg_power_watts,
    r.duration_ns / 1e6         AS duration_ms,
    r.total_tokens,
    r.ipc,
    r.cache_miss_rate,
    r.carbon_g,
    r.planning_time_ms,
    r.execution_time_ms,
    r.synthesis_time_ms,
    r.experiment_valid,
    r.thermal_throttle_flag,
    r.package_temp_celsius
FROM runs r
WHERE r.exp_id = :exp_id
ORDER BY r.run_number ASC
