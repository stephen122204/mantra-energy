Orchestration tax — agentic overhead over linear baseline
SELECT
    e.task_name,
    e.provider,
    e.model_name,
    COUNT(ots.comparison_id)                                       AS pair_count,
    AVG(ots.tax_percent)                                           AS avg_tax_pct,
    AVG(ots.orchestration_tax_uj) / 1e6                           AS avg_tax_j,
    AVG(ots.linear_dynamic_uj)    / 1e6                           AS avg_linear_dynamic_j,
    AVG(ots.agentic_dynamic_uj)   / 1e6                           AS avg_agentic_dynamic_j,
    AVG(ots.agentic_dynamic_uj) / NULLIF(AVG(ots.linear_dynamic_uj), 0) AS tax_multiplier,
    MIN(ots.tax_percent)                                           AS min_tax_pct,
    MAX(ots.tax_percent)                                           AS max_tax_pct
FROM orchestration_tax_summary ots
JOIN runs rl ON ots.linear_run_id = rl.run_id
JOIN experiments e ON rl.exp_id = e.exp_id
GROUP BY e.task_name, e.provider, e.model_name
ORDER BY tax_multiplier DESC;