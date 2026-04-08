Phase energy attribution (proportional by time)
SELECT
    e.task_name,
    e.provider,
    COUNT(*)                                                       AS run_count,
    AVG(r.planning_time_ms)                                        AS avg_planning_ms,
    AVG(r.execution_time_ms)                                       AS avg_execution_ms,
    AVG(r.synthesis_time_ms)                                       AS avg_synthesis_ms,
    -- Phase shares of total time
    AVG(r.planning_time_ms * 100.0 /
        NULLIF(r.planning_time_ms + r.execution_time_ms + r.synthesis_time_ms, 0))  AS planning_time_pct,
    AVG(r.execution_time_ms * 100.0 /
        NULLIF(r.planning_time_ms + r.execution_time_ms + r.synthesis_time_ms, 0))  AS execution_time_pct,
    AVG(r.synthesis_time_ms * 100.0 /
        NULLIF(r.planning_time_ms + r.execution_time_ms + r.synthesis_time_ms, 0))  AS synthesis_time_pct,
    -- Energy attributed proportionally to each phase
    AVG(r.dynamic_energy_uj / 1e6 * r.planning_time_ms /
        NULLIF(r.planning_time_ms + r.execution_time_ms + r.synthesis_time_ms, 0))  AS planning_energy_j,
    AVG(r.dynamic_energy_uj / 1e6 * r.execution_time_ms /
        NULLIF(r.planning_time_ms + r.execution_time_ms + r.synthesis_time_ms, 0))  AS execution_energy_j,
    AVG(r.dynamic_energy_uj / 1e6 * r.synthesis_time_ms /
        NULLIF(r.planning_time_ms + r.execution_time_ms + r.synthesis_time_ms, 0))  AS synthesis_energy_j
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.workflow_type = 'agentic'
  AND r.planning_time_ms > 0
  AND r.experiment_valid = 1
GROUP BY e.task_name, e.provider
ORDER BY avg_planning_ms DESC;