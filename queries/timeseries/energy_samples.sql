-- queries/energy_samples.sql
-- 100Hz RAPL samples for one run
-- Named params: :run_id

SELECT
    sample_id,
    timestamp_ns,
    pkg_energy_uj,
    core_energy_uj,
    uncore_energy_uj,
    dram_energy_uj
FROM energy_samples
WHERE run_id = :run_id
ORDER BY timestamp_ns
