C-state residency and energy efficiency
SELECT
    r.workflow_type,
    AVG(r.ipc)                                                     AS avg_ipc,
    AVG(r.frequency_mhz)                                           AS avg_freq_mhz,
    AVG(r.c2_time_seconds)                                         AS avg_c2_s,
    AVG(r.c3_time_seconds)                                         AS avg_c3_s,
    AVG(r.c6_time_seconds)                                         AS avg_c6_s,
    AVG(r.c7_time_seconds)                                         AS avg_c7_s,
    -- C-state sleep time as fraction of duration
    AVG((r.c2_time_seconds + r.c3_time_seconds + r.c6_time_seconds + r.c7_time_seconds)
        / NULLIF(r.duration_ns / 1e9, 0) * 100)                   AS sleep_time_pct,
    AVG(r.energy_per_instruction) * 1e9                           AS avg_nj_per_instruction
FROM runs r
WHERE r.ipc > 0
  AND r.experiment_valid = 1
GROUP BY r.workflow_type;