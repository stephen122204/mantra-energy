Cache miss impact on energy
SELECT
    CASE
        WHEN r.cache_miss_rate < 0.01 THEN 'low (<1%)'
        WHEN r.cache_miss_rate < 0.05 THEN 'medium (1-5%)'
        ELSE 'high (>5%)'
    END                                                            AS cache_miss_band,
    r.workflow_type,
    COUNT(*)                                                       AS run_count,
    AVG(r.cache_miss_rate * 100)                                   AS avg_cache_miss_pct,
    AVG(r.pkg_energy_uj) / 1e6                                    AS avg_pkg_j,
    AVG(r.ipc)                                                     AS avg_ipc,
    AVG(r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9))           AS avg_power_w
FROM runs r
WHERE r.cache_miss_rate IS NOT NULL
  AND r.cache_miss_rate >= 0
  AND r.experiment_valid = 1
GROUP BY cache_miss_band, r.workflow_type
ORDER BY avg_cache_miss_pct;