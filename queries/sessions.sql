-- queries/sessions.sql
-- Session aggregates grouped by group_id

SELECT
    e.group_id,
    COUNT(DISTINCT e.exp_id)                AS experiments,
    COUNT(DISTINCT r.run_id)                AS runs,
    MIN(r.start_time_ns)                    AS started_ns,
    MAX(r.end_time_ns)                      AS ended_ns,
    SUM(r.total_energy_uj) / 1e6            AS total_energy_j,
    AVG(r.total_energy_uj) / 1e6            AS avg_energy_j,
    AVG(r.avg_power_watts)                  AS avg_power_w,
    SUM(r.carbon_g)                         AS total_carbon_g,
    AVG(CASE WHEN r.workflow_type='agentic' THEN
        ots.tax_percent END)                AS avg_tax_pct,
    COUNT(CASE WHEN r.workflow_type='linear'  THEN 1 END) AS linear_runs,
    COUNT(CASE WHEN r.workflow_type='agentic' THEN 1 END) AS agentic_runs
FROM experiments e
JOIN runs r ON e.exp_id = r.exp_id
LEFT JOIN orchestration_tax_summary ots ON r.run_id = ots.agentic_run_id
WHERE e.group_id IS NOT NULL
GROUP BY e.group_id
ORDER BY started_ns DESC
