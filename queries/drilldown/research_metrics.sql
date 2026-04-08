-- queries/research_metrics.sql
-- OOI, UCR, network ratio from research_metrics_view

SELECT
    r.run_id,
    r.exp_id,
    e.provider,
    e.task_name,
    r.workflow_type,
    r.duration_ns / 1e6                     AS total_time_ms,
    r.compute_time_ms,
    r.orchestration_cpu_ms,
    CASE WHEN r.duration_ns > 0
        THEN r.orchestration_cpu_ms * 1.0 / (r.duration_ns / 1e6)
        ELSE 0 END                           AS ooi_time,
    CASE WHEN r.compute_time_ms > 0
        THEN r.orchestration_cpu_ms * 1.0 / r.compute_time_ms
        ELSE 0 END                           AS ooi_cpu,
    r.total_energy_uj / 1e6                 AS energy_j,
    r.avg_power_watts,
    r.planning_time_ms,
    r.execution_time_ms,
    r.synthesis_time_ms
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.workflow_type = 'agentic'
  AND r.orchestration_cpu_ms IS NOT NULL
  AND r.compute_time_ms > 0
ORDER BY r.run_id DESC
LIMIT 200
