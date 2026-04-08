Energy per token — linear vs agentic
-- Where tokens available (74% coverage)
SELECT
    e.task_name,
    e.provider,
    r.workflow_type,
    COUNT(*)                                                        AS run_count,
    AVG(r.total_tokens)                                            AS avg_tokens,
    AVG(r.dynamic_energy_uj / NULLIF(r.total_tokens, 0)) / 1e6   AS avg_j_per_token,
    AVG(r.pkg_energy_uj     / NULLIF(r.total_tokens, 0)) / 1e6   AS avg_pkg_j_per_token,
    -- Per 1k tokens
    AVG(r.dynamic_energy_uj / NULLIF(r.total_tokens, 0)) / 1e3   AS avg_mj_per_1k_tokens,
    MIN(r.dynamic_energy_uj / NULLIF(r.total_tokens, 0)) / 1e6   AS min_j_per_token,
    MAX(r.dynamic_energy_uj / NULLIF(r.total_tokens, 0)) / 1e6   AS max_j_per_token
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.total_tokens > 0
  AND r.dynamic_energy_uj > 0
  AND r.experiment_valid = 1
GROUP BY e.task_name, e.provider, r.workflow_type
ORDER BY avg_j_per_token DESC;