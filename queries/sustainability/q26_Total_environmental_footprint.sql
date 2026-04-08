Total environmental footprint
SELECT
    SUM(r.carbon_g)                                               AS total_carbon_g,
    SUM(r.carbon_g) * 1000                                        AS total_carbon_mg,
    SUM(r.water_ml)                                               AS total_water_ml,
    SUM(r.water_ml) / 1000                                        AS total_water_l,
    SUM(r.methane_mg)                                             AS total_methane_mg,
    -- Agentic overhead footprint
    SUM(CASE WHEN r.workflow_type='agentic' THEN r.carbon_g ELSE 0 END) -
    SUM(CASE WHEN r.workflow_type='linear'  THEN r.carbon_g ELSE 0 END) AS agentic_carbon_overhead_g,
    COUNT(*)                                                       AS total_runs,
    SUM(r.pkg_energy_uj) / 1e6                                    AS total_energy_j,
    SUM(r.pkg_energy_uj) / 1e9                                    AS total_energy_kj
FROM runs r
WHERE r.experiment_valid = 1;

-- ============================================================
-- SECTION 7: TIME SERIES AND TRENDS
-- ============================================================