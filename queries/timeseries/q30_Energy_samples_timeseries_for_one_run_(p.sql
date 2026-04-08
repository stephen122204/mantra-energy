Energy samples timeseries for one run (power curve)
SELECT
    es.sample_id,
    es.timestamp_ns,
    (es.timestamp_ns - MIN(es.timestamp_ns) OVER ()) / 1e9         AS elapsed_s,
    es.pkg_energy_uj,
    es.core_energy_uj,
    es.uncore_energy_uj,
    -- Instantaneous power between samples
    (es.pkg_energy_uj - LAG(es.pkg_energy_uj) OVER (ORDER BY es.timestamp_ns)) /
    ((es.timestamp_ns - LAG(es.timestamp_ns) OVER (ORDER BY es.timestamp_ns)) / 1e9) / 1e6
                                                                   AS pkg_power_w
FROM energy_samples es
WHERE es.run_id = :run_id
ORDER BY es.timestamp_ns;