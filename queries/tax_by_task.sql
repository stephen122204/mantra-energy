-- queries/tax_by_task.sql
-- Orchestration tax by task and model
-- Named params: none

SELECT
    el.task_name,
    el.provider,
    el.model_name,
    AVG(ots.tax_percent)                    AS tax_percent,
    AVG(ots.orchestration_tax_uj) / 1e6     AS avg_tax_j,
    AVG(ots.linear_dynamic_uj) / 1e6        AS avg_linear_j,
    AVG(ots.agentic_dynamic_uj) / 1e6       AS avg_agentic_j,
    AVG(ra.planning_time_ms)                AS avg_planning_ms,
    AVG(ra.execution_time_ms)               AS avg_execution_ms,
    AVG(ra.synthesis_time_ms)               AS avg_synthesis_ms,
    COUNT(*)                                AS pair_count
FROM orchestration_tax_summary ots
JOIN runs rl  ON ots.linear_run_id  = rl.run_id
JOIN runs ra  ON ots.agentic_run_id = ra.run_id
JOIN experiments el ON rl.exp_id = el.exp_id
GROUP BY el.task_name, el.provider, el.model_name
ORDER BY tax_percent DESC
