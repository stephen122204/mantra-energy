LLM interaction breakdown for one run
SELECT
    li.interaction_id,
    li.step_index,
    li.workflow_type,
    li.prompt_tokens,
    li.completion_tokens,
    li.total_tokens,
    li.preprocess_ms,
    li.non_local_ms,
    li.local_compute_ms,
    li.postprocess_ms,
    li.total_time_ms,
    li.api_latency_ms,
    -- UCR for this interaction
    li.local_compute_ms / NULLIF(li.total_time_ms, 0)             AS ucr,
    -- Network ratio
    li.non_local_ms / NULLIF(li.total_time_ms, 0)                 AS network_ratio,
    li.status,
    li.error_message
FROM llm_interactions li
WHERE li.run_id = :run_id
ORDER BY li.step_index;