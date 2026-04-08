OOI — Orchestration Overhead Index
-- ooi_time = orchestration_cpu_ms / total_time_ms
-- ooi_cpu  = orchestration_cpu_ms / compute_time_ms
SELECT
    e.task_name,
    e.provider,
    COUNT(*)                                                       AS run_count,
    AVG(r.orchestration_cpu_ms / NULLIF(r.duration_ns / 1e6, 0)) AS avg_ooi_time,
    AVG(r.orchestration_cpu_ms / NULLIF(r.compute_time_ms, 0))   AS avg_ooi_cpu,
    AVG(r.compute_time_ms / NULLIF(r.duration_ns / 1e6, 0))      AS avg_ucr,
    AVG(r.orchestration_cpu_ms)                                   AS avg_orch_ms,
    AVG(r.compute_time_ms)                                        AS avg_compute_ms
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.workflow_type = 'agentic'
  AND r.orchestration_cpu_ms > 0
  AND r.compute_time_ms > 0
  AND r.experiment_valid = 1
GROUP BY e.task_name, e.provider
ORDER BY avg_ooi_time DESC;