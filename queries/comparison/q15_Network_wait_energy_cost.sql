Network wait energy cost
-- Energy wasted waiting for API response
SELECT
    e.provider,
    r.workflow_type,
    COUNT(*)                                                       AS run_count,
    AVG(r.api_latency_ms)                                         AS avg_api_latency_ms,
    AVG(r.dns_latency_ms)                                         AS avg_dns_latency_ms,
    -- Energy during network wait = power × wait_time
    AVG(r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9)
        * r.api_latency_ms / 1e3)                                 AS avg_network_wait_j,
    AVG(r.api_latency_ms * 100.0 / NULLIF(r.duration_ns / 1e6, 0)) AS api_wait_pct,
    AVG(r.bytes_sent)                                             AS avg_bytes_sent,
    AVG(r.bytes_recv)                                             AS avg_bytes_recv
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.api_latency_ms > 0
  AND r.experiment_valid = 1
GROUP BY e.provider, r.workflow_type
ORDER BY avg_network_wait_j DESC;

-- ============================================================
-- SECTION 4: COMPARISON
-- Linear vs agentic, model vs model, task vs task
-- ============================================================