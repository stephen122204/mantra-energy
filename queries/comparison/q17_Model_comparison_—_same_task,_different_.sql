Model comparison — same task, different models
SELECT
    e.task_name,
    e.model_name,
    e.provider,
    r.workflow_type,
    COUNT(*)                                                       AS run_count,
    AVG(r.pkg_energy_uj)   / 1e6                                  AS avg_pkg_j,
    AVG(r.dynamic_energy_uj/ NULLIF(r.total_tokens, 0)) / 1e6    AS avg_j_per_token,
    AVG(r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9))           AS avg_power_w,
    AVG(r.total_tokens)                                           AS avg_tokens,
    AVG(r.duration_ns) / 1e9                                      AS avg_duration_s,
    AVG(r.ipc)                                                    AS avg_ipc
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.experiment_valid = 1
GROUP BY e.task_name, e.model_name, e.provider, r.workflow_type
ORDER BY e.task_name, avg_pkg_j;