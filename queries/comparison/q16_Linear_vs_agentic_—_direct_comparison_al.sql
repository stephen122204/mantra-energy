Linear vs agentic — direct comparison all metrics
SELECT
    e.task_name,
    e.provider,
    e.model_name,
    SUM(CASE WHEN r.workflow_type='linear'  THEN 1 ELSE 0 END)    AS linear_runs,
    SUM(CASE WHEN r.workflow_type='agentic' THEN 1 ELSE 0 END)    AS agentic_runs,
    -- Energy per query
    AVG(CASE WHEN r.workflow_type='linear'
        THEN r.pkg_energy_uj END) / 1e6                           AS linear_pkg_j,
    AVG(CASE WHEN r.workflow_type='agentic'
        THEN r.pkg_energy_uj END) / 1e6                           AS agentic_pkg_j,
    -- Tax multiplier
    AVG(CASE WHEN r.workflow_type='agentic' THEN r.pkg_energy_uj END) /
    NULLIF(AVG(CASE WHEN r.workflow_type='linear'
        THEN r.pkg_energy_uj END), 0)                             AS energy_multiplier,
    -- Power comparison
    AVG(CASE WHEN r.workflow_type='linear'
        THEN r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9) END)  AS linear_power_w,
    AVG(CASE WHEN r.workflow_type='agentic'
        THEN r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9) END)  AS agentic_power_w,
    -- Duration comparison
    AVG(CASE WHEN r.workflow_type='linear'
        THEN r.duration_ns END) / 1e9                             AS linear_duration_s,
    AVG(CASE WHEN r.workflow_type='agentic'
        THEN r.duration_ns END) / 1e9                             AS agentic_duration_s,
    -- Token comparison
    AVG(CASE WHEN r.workflow_type='linear'
        THEN r.total_tokens END)                                   AS linear_avg_tokens,
    AVG(CASE WHEN r.workflow_type='agentic'
        THEN r.total_tokens END)                                   AS agentic_avg_tokens
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.experiment_valid = 1
GROUP BY e.task_name, e.provider, e.model_name
HAVING linear_runs > 0 AND agentic_runs > 0
ORDER BY energy_multiplier DESC;