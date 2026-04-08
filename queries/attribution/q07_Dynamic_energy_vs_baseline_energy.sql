Dynamic energy vs baseline energy
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