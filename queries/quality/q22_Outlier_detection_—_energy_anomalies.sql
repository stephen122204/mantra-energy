Outlier detection — energy anomalies
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