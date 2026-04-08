Energy trend over time (by session)
SELECT
    e.group_id                                                     AS session_id,
    COUNT(DISTINCT e.exp_id)                                       AS experiments,
    COUNT(r.run_id)                                                AS runs,
    AVG(r.pkg_energy_uj) / 1e6                                    AS avg_energy_j,
    AVG(r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9))           AS avg_power_w,
    AVG(r.dynamic_energy_uj / NULLIF(r.total_tokens, 0)) / 1e6   AS avg_j_per_token,
    AVG(CASE WHEN r.workflow_type='agentic' THEN r.pkg_energy_uj END) /
    NULLIF(AVG(CASE WHEN r.workflow_type='linear'
        THEN r.pkg_energy_uj END), 0)                             AS tax_multiplier
FROM experiments e
JOIN runs r ON e.exp_id = r.exp_id
WHERE e.group_id IS NOT NULL
  AND r.experiment_valid = 1
GROUP BY e.group_id
ORDER BY e.group_id;