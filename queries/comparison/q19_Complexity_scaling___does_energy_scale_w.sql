Complexity scaling — does energy scale with complexity level?
SELECT
    r.complexity_level,
    r.workflow_type,
    COUNT(*)                                                       AS run_count,
    AVG(r.pkg_energy_uj) / 1e6                                    AS avg_energy_j,
    AVG(r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9))           AS avg_power_w,
    AVG(r.total_tokens)                                           AS avg_tokens,
    AVG(r.llm_calls)                                              AS avg_llm_calls,
    AVG(r.duration_ns) / 1e9                                      AS avg_duration_s
FROM runs r
WHERE r.complexity_level IS NOT NULL
  AND r.experiment_valid = 1
GROUP BY r.complexity_level, r.workflow_type
ORDER BY r.complexity_level, r.workflow_type;