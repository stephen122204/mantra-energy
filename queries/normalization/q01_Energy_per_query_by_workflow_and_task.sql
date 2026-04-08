Energy per query by workflow and task
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