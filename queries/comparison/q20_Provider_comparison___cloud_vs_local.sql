Provider comparison — cloud vs local
SELECT
    e.provider,
    r.workflow_type,
    COUNT(*)                                                       AS run_count,
    AVG(r.pkg_energy_uj) / 1e6                                    AS avg_energy_j,
    AVG(r.dynamic_energy_uj / NULLIF(r.total_tokens, 0)) / 1e6   AS avg_j_per_token,
    AVG(r.api_latency_ms)                                         AS avg_api_latency_ms,
    AVG(r.dns_latency_ms)                                         AS avg_dns_latency_ms,
    AVG(r.total_tokens)                                           AS avg_tokens,
    AVG(r.carbon_g)                                               AS avg_carbon_g
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.experiment_valid = 1
GROUP BY e.provider, r.workflow_type
ORDER BY avg_energy_j;

-- ============================================================
-- SECTION 5: DATA QUALITY
-- ============================================================