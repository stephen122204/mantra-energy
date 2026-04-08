Prompt vs completion token energy split
SELECT
    r.workflow_type,
    AVG(r.prompt_tokens)                                           AS avg_prompt_tokens,
    AVG(r.completion_tokens)                                       AS avg_completion_tokens,
    AVG(r.total_tokens)                                            AS avg_total_tokens,
    AVG(r.prompt_tokens * 100.0 / NULLIF(r.total_tokens, 0))      AS prompt_share_pct,
    AVG(r.completion_tokens * 100.0 / NULLIF(r.total_tokens, 0))  AS completion_share_pct,
    -- Energy attributed proportionally to prompt vs completion
    AVG(r.dynamic_energy_uj / NULLIF(r.total_tokens, 0)
        * r.prompt_tokens) / 1e6                                  AS est_prompt_energy_j,
    AVG(r.dynamic_energy_uj / NULLIF(r.total_tokens, 0)
        * r.completion_tokens) / 1e6                              AS est_completion_energy_j
FROM runs r
WHERE r.total_tokens > 0
  AND r.prompt_tokens > 0
  AND r.experiment_valid = 1
GROUP BY r.workflow_type;

-- ============================================================
-- SECTION 2: SILICON ATTRIBUTION
-- pkg / core / uncore layer breakdown
-- ============================================================