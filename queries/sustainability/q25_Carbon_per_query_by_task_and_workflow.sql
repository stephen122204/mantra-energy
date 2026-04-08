Carbon per query by task and workflow
SELECT
    e.task_name,
    e.country_code,
    r.workflow_type,
    COUNT(*)                                                       AS run_count,
    AVG(r.carbon_g)                                               AS avg_carbon_g,
    AVG(r.carbon_g) * 1000                                        AS avg_carbon_mg,
    AVG(r.water_ml)                                               AS avg_water_ml,
    AVG(r.methane_mg)                                             AS avg_methane_mg,
    -- Per token sustainability
    AVG(r.carbon_g / NULLIF(r.total_tokens, 0)) * 1000           AS avg_carbon_mg_per_token,
    -- Agentic carbon tax
    AVG(CASE WHEN r.workflow_type='agentic' THEN r.carbon_g END) /
    NULLIF(AVG(CASE WHEN r.workflow_type='linear'
        THEN r.carbon_g END), 0)                                   AS carbon_multiplier
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
WHERE r.carbon_g > 0
  AND r.experiment_valid = 1
GROUP BY e.task_name, e.country_code, r.workflow_type
ORDER BY avg_carbon_g DESC;