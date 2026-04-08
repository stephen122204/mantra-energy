Task domain energy profile
SELECT
    e.task_name,
    COUNT(*)                                                       AS total_runs,
    -- Energy
    AVG(r.pkg_energy_uj) / 1e6                                    AS avg_energy_j,
    AVG(r.pkg_energy_uj / 1e6 / (r.duration_ns / 1e9))           AS avg_power_w,
    AVG(r.dynamic_energy_uj / NULLIF(r.total_tokens, 0)) / 1e6   AS avg_j_per_token,
    -- Performance
    AVG(r.ipc)                                                    AS avg_ipc,
    AVG(r.frequency_mhz)                                          AS avg_freq_mhz,
    AVG(r.cache_miss_rate * 100)                                  AS avg_cache_miss_pct,
    -- Agentic tax
    AVG(CASE WHEN r.workflow_type='agentic'
        THEN r.pkg_energy_uj END) /
    NULLIF(AVG(CASE WHEN r.workflow_type='linear'
        THEN r.pkg_energy_uj END), 0)                             AS tax_multiplier,
    -- Sustainability
    AVG(r.carbon_g)                                               AS avg_carbon_g,
    AVG(r.water_ml)                                               AS avg_water_ml
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.experiment_valid = 1
GROUP BY e.task_name
ORDER BY avg_energy_j DESC;