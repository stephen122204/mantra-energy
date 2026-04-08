Statistical sufficiency — how many runs per cell
SELECT
    e.task_name,
    e.model_name,
    r.workflow_type,
    COUNT(*)                                                       AS run_count,
    CASE
        WHEN COUNT(*) >= 30 THEN 'sufficient'
        WHEN COUNT(*) >= 10 THEN 'moderate'
        WHEN COUNT(*) >= 5  THEN 'low'
        ELSE 'insufficient'
    END                                                            AS sufficiency,
    AVG(r.pkg_energy_uj) / 1e6                                    AS avg_energy_j,
    -- Coefficient of variation (std/mean)
    (MAX(r.pkg_energy_uj) - MIN(r.pkg_energy_uj)) /
    NULLIF(AVG(r.pkg_energy_uj), 0) * 100                         AS energy_range_pct
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.experiment_valid = 1
GROUP BY e.task_name, e.model_name, r.workflow_type
ORDER BY run_count DESC;