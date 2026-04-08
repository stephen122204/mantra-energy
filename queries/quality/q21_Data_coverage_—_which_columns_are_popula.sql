Data coverage — which columns are populated
SELECT
    COUNT(*)                                                       AS total_runs,
    COUNT(CASE WHEN r.pkg_energy_uj > 0     THEN 1 END)           AS has_pkg_energy,
    COUNT(CASE WHEN r.core_energy_uj > 0    THEN 1 END)           AS has_core_energy,
    COUNT(CASE WHEN r.uncore_energy_uj > 0  THEN 1 END)           AS has_uncore_energy,
    COUNT(CASE WHEN r.dynamic_energy_uj > 0 THEN 1 END)           AS has_dynamic_energy,
    COUNT(CASE WHEN r.total_tokens > 0      THEN 1 END)           AS has_tokens,
    COUNT(CASE WHEN r.ipc > 0              THEN 1 END)            AS has_ipc,
    COUNT(CASE WHEN r.compute_time_ms > 0  THEN 1 END)            AS has_compute_time,
    COUNT(CASE WHEN r.orchestration_cpu_ms > 0 THEN 1 END)        AS has_orch_cpu,
    COUNT(CASE WHEN r.planning_time_ms > 0 THEN 1 END)            AS has_phases,
    COUNT(CASE WHEN r.baseline_id IS NOT NULL THEN 1 END)         AS has_baseline,
    COUNT(CASE WHEN r.experiment_valid = 1  THEN 1 END)           AS valid_runs,
    COUNT(CASE WHEN r.thermal_throttle_flag = 1 THEN 1 END)       AS throttled_runs,
    COUNT(CASE WHEN r.background_cpu_percent > 10 THEN 1 END)     AS noisy_runs
FROM runs r;