Silicon domain attribution by task
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