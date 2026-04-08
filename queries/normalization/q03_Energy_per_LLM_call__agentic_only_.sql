Energy per LLM call (agentic only)
SELECT
    e.task_name,
    e.provider,
    e.model_name,
    COUNT(*)                                                        AS run_count,
    AVG(r.llm_calls)                                               AS avg_llm_calls,
    AVG(r.tool_calls)                                              AS avg_tool_calls,
    AVG(r.dynamic_energy_uj / NULLIF(r.llm_calls,  0)) / 1e6     AS avg_j_per_llm_call,
    AVG(r.dynamic_energy_uj / NULLIF(r.tool_calls, 0)) / 1e6     AS avg_j_per_tool_call,
    AVG(r.dynamic_energy_uj / NULLIF(r.steps, 0))      / 1e6     AS avg_j_per_step
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.workflow_type = 'agentic'
  AND r.llm_calls > 0
  AND r.experiment_valid = 1
GROUP BY e.task_name, e.provider, e.model_name
ORDER BY avg_j_per_llm_call DESC;