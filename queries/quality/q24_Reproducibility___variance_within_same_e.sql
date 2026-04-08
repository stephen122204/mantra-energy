Reproducibility — variance within same experiment
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