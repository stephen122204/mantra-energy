Thermal impact on energy
SELECT
    CASE
        WHEN r.package_temp_celsius < 50 THEN 'cool (<50C)'
        WHEN r.package_temp_celsius < 70 THEN 'warm (50-70C)'
        ELSE 'hot (>70C)'
    END                                                            AS temp_band,
    r.workflow_type,
    COUNT(*)                                                       AS run_count,
    AVG(r.package_temp_celsius)                                    AS avg_temp_c,
    AVG(r.thermal_delta_c)                                         AS avg_thermal_rise_c,
    AVG(r.pkg_energy_uj) / 1e6                                    AS avg_pkg_j,
    SUM(CASE WHEN r.thermal_throttle_flag = 1 THEN 1 ELSE 0 END)  AS throttled_count
FROM runs r
WHERE r.package_temp_celsius IS NOT NULL
  AND r.experiment_valid = 1
GROUP BY temp_band, r.workflow_type
ORDER BY avg_temp_c;

-- ============================================================
-- SECTION 3: ORCHESTRATION ATTRIBUTION
-- Agentic overhead — planning / execution / synthesis
-- ============================================================