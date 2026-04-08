-- queries/research_metrics.sql
-- OOI, UCR, RAF and derived research metrics
-- Back-propagated from gui/report_engine/goals/orchestration_overhead.yaml
-- Named params: none (aggregate across all agentic runs)

SELECT
    -- OOI Time: fraction of wall-clock consumed by orchestration
    -- Formula from goals/orchestration_overhead.yaml:
    -- ooi_time = orchestration_cpu_ms / (duration_ns / 1e6)
    ROUND(
        AVG(CASE WHEN r.workflow_type = 'agentic' AND r.orchestration_cpu_ms > 0
            THEN r.orchestration_cpu_ms / (r.duration_ns / 1e6)
        END), 4
    )                                                       AS ooi_time,

    -- OOI CPU: fraction of active compute consumed by orchestration
    -- Formula: orchestration_cpu_ms / compute_time_ms
    ROUND(
        AVG(CASE WHEN r.workflow_type = 'agentic'
                  AND li.compute_time_ms > 0
                  AND r.orchestration_cpu_ms > 0
            THEN r.orchestration_cpu_ms / li.compute_time_ms
        END), 4
    )                                                       AS ooi_cpu,

    -- UCR: Useful Compute Ratio — fraction of time on actual LLM inference
    -- Formula: total_llm_compute_ms / (duration_ns / 1e6)
    ROUND(
        AVG(CASE WHEN r.workflow_type = 'agentic' AND li.compute_time_ms > 0
            THEN li.compute_time_ms / (r.duration_ns / 1e6)
        END), 4
    )                                                       AS ucr,

    -- Network Wait Ratio: fraction of time waiting on network
    -- Formula: total_wait_ms / (duration_ns / 1e6)
    ROUND(
        AVG(CASE WHEN r.workflow_type = 'agentic' AND li.non_local_ms > 0
            THEN li.non_local_ms / (r.duration_ns / 1e6)
        END), 4
    )                                                       AS network_ratio,

    -- Raw values for verification
    ROUND(AVG(CASE WHEN r.workflow_type='agentic'
        THEN r.orchestration_cpu_ms END), 2)                AS avg_orchestration_cpu_ms,

    ROUND(AVG(CASE WHEN r.workflow_type='agentic'
        THEN li.compute_time_ms END), 2)                    AS avg_compute_time_ms,

    ROUND(AVG(CASE WHEN r.workflow_type='agentic'
        THEN li.non_local_ms END), 2)                       AS avg_non_local_ms,

    ROUND(AVG(CASE WHEN r.workflow_type='agentic'
        THEN li.preprocess_ms END), 2)                      AS avg_preprocess_ms,

    ROUND(AVG(CASE WHEN r.workflow_type='agentic'
        THEN li.postprocess_ms END), 2)                     AS avg_postprocess_ms,

    COUNT(CASE WHEN r.workflow_type='agentic' THEN 1 END)   AS agentic_runs_used

FROM runs r
LEFT JOIN (
    -- Aggregate LLM interaction times per run
    SELECT
        run_id,
        SUM(compute_time_ms)  AS compute_time_ms,
        SUM(non_local_ms)     AS non_local_ms,
        SUM(preprocess_ms)    AS preprocess_ms,
        SUM(postprocess_ms)   AS postprocess_ms
    FROM llm_interactions
    WHERE status = 'success'
    GROUP BY run_id
) li ON li.run_id = r.run_id
WHERE r.workflow_type = 'agentic'
  AND r.experiment_valid = 1
  AND r.orchestration_cpu_ms IS NOT NULL
  AND r.duration_ns > 0
