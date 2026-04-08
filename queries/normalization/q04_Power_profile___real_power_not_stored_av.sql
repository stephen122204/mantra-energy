Power profile — real power not stored avg_power_watts
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