LLM call efficiency — energy per useful token per call
SELECT
    e.task_name,
    e.provider,
    COUNT(*)                                                       AS run_count,
    AVG(r.llm_calls)                                              AS avg_llm_calls,
    AVG(r.total_tokens / NULLIF(r.llm_calls, 0))                 AS avg_tokens_per_call,
    AVG(r.dynamic_energy_uj / NULLIF(r.llm_calls, 0)) / 1e6     AS avg_j_per_call,
    -- Energy efficiency: tokens per joule
    AVG(r.total_tokens / NULLIF(r.dynamic_energy_uj / 1e6, 0))  AS avg_tokens_per_j
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.workflow_type = 'agentic'
  AND r.llm_calls > 0
  AND r.total_tokens > 0
  AND r.experiment_valid = 1
GROUP BY e.task_name, e.provider
ORDER BY avg_j_per_call DESC;