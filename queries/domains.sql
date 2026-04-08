-- queries/domains.sql
-- Energy by task domain

SELECT
    e.task_name,
    COUNT(*)                                AS run_count,
    AVG(r.total_energy_uj) / 1e6           AS avg_energy_j,
    AVG(r.avg_power_watts)                  AS avg_power_w,
    AVG(r.carbon_g)                         AS avg_carbon_g,
    AVG(r.total_tokens)                     AS avg_tokens,
    AVG(r.energy_per_token)                 AS avg_energy_per_token,
    AVG(r.ipc)                              AS avg_ipc,
    AVG(CASE WHEN r.workflow_type='linear'  THEN r.total_energy_uj END)/1e6 AS avg_linear_j,
    AVG(CASE WHEN r.workflow_type='agentic' THEN r.total_energy_uj END)/1e6 AS avg_agentic_j
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
GROUP BY e.task_name
ORDER BY avg_energy_j DESC
