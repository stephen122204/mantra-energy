-- v56_v_energy_view.sql
-- Unified flat pivot view over legacy energy_samples and new energy_samples_v2.
-- Students and paper macros query this view only — never raw tables.
-- Pivot design: one row per sample, all domains as named columns.
-- NULL where platform does not measure that domain.
-- SUM(), AVG(), MIN(), MAX() skip NULL automatically — no filter needed.
-- Legacy RAPL rows (4.9M) appear with same column names as new rows.
-- DROP VIEW ensures clean replacement on every migration run.
-- cp to: scripts/migrations/v56_v_energy_view.sql

DROP VIEW IF EXISTS v_energy;

CREATE VIEW v_energy AS

-- NEW normalized rows (GN100, Apple, AMD, TAMU, all future platforms)
-- Pivot: one row per sample_id, domains spread into named columns.
-- GPU domain appears multiple times: one column per source.
SELECT
    esv2.sample_id,
    esv2.run_id,
    esv2.timestamp_ns,
    esv2.interval_ns,
    src.name                                                        AS source_name,
    MAX(CASE WHEN esd.domain_id = 1  THEN esd.energy_uj END)       AS package_energy_uj,
    MAX(CASE WHEN esd.domain_id = 2  THEN esd.energy_uj END)       AS core_energy_uj,
    MAX(CASE WHEN esd.domain_id = 3  THEN esd.energy_uj END)       AS uncore_energy_uj,
    MAX(CASE WHEN esd.domain_id = 4  THEN esd.energy_uj END)       AS dram_energy_uj,
    MAX(CASE WHEN esd.domain_id = 5  THEN esd.energy_uj END)       AS cpu_p_energy_uj,
    MAX(CASE WHEN esd.domain_id = 6  THEN esd.energy_uj END)       AS cpu_e_energy_uj,
    MAX(CASE WHEN esd.domain_id = 7 AND esd.source_id = 2
             THEN esd.energy_uj END)                                AS gpu_spbm_energy_uj,
    MAX(CASE WHEN esd.domain_id = 7 AND esd.source_id = 4
             THEN esd.energy_uj END)                                AS gpu_dcgm_energy_uj,
    MAX(CASE WHEN esd.domain_id = 7 AND esd.source_id = 3
             THEN esd.energy_uj END)                                AS gpu_nvml_energy_uj,
    MAX(CASE WHEN esd.domain_id = 7 AND esd.source_id = 7
             THEN esd.energy_uj END)                                AS gpu_smi_energy_uj,
    MAX(CASE WHEN esd.domain_id = 7 AND esd.source_id = 8
             THEN esd.energy_uj END)                                AS gpu_pp1_energy_uj,
    MAX(CASE WHEN esd.domain_id = 11 THEN esd.energy_uj END)       AS unified_energy_uj,
    MAX(CASE WHEN esd.domain_id = 12 THEN esd.energy_uj END)       AS cpu_apple_energy_uj,
    MAX(CASE WHEN esd.domain_id = 13 THEN esd.energy_uj END)       AS gpu_apple_energy_uj,
    MAX(CASE WHEN esd.domain_id = 15 THEN esd.energy_uj END)       AS nvlink_c2c_energy_uj,
    MAX(CASE WHEN esd.domain_id = 8  THEN esd.energy_uj END)       AS ccd0_energy_uj,
    MAX(CASE WHEN esd.domain_id = 9  THEN esd.energy_uj END)       AS ccd1_energy_uj,
    MAX(CASE WHEN esd.domain_id = 10 THEN esd.energy_uj END)       AS iodie_energy_uj,
    MAX(CASE WHEN esd.domain_id = 20 THEN esd.energy_uj END)       AS dla_energy_uj
FROM energy_samples_v2 esv2
JOIN energy_sources        src ON src.source_id = esv2.source_id
JOIN energy_sample_domains esd ON esd.sample_id = esv2.sample_id
GROUP BY
    esv2.sample_id,
    esv2.run_id,
    esv2.timestamp_ns,
    esv2.interval_ns,
    src.name

UNION ALL

-- LEGACY RAPL rows (4.9M rows, UBUNTU2505 history — untouched forever)
-- pkg_energy_uj mapped to package_energy_uj for uniform column name.
-- Non-RAPL columns are NULL — SUM/AVG skip them automatically.
SELECT
    es.sample_id,
    es.run_id,
    es.timestamp_ns,
    es.interval_ns,
    'RAPL'                  AS source_name,
    es.pkg_energy_uj        AS package_energy_uj,
    es.core_energy_uj,
    es.uncore_energy_uj,
    es.dram_energy_uj,
    NULL                    AS cpu_p_energy_uj,
    NULL                    AS cpu_e_energy_uj,
    NULL                    AS gpu_spbm_energy_uj,
    NULL                    AS gpu_dcgm_energy_uj,
    NULL                    AS gpu_nvml_energy_uj,
    NULL                    AS gpu_smi_energy_uj,
    es.gpu_energy_uj        AS gpu_pp1_energy_uj,
    NULL                    AS unified_energy_uj,
    NULL                    AS cpu_apple_energy_uj,
    NULL                    AS gpu_apple_energy_uj,
    NULL                    AS nvlink_c2c_energy_uj,
    NULL                    AS ccd0_energy_uj,
    NULL                    AS ccd1_energy_uj,
    NULL                    AS iodie_energy_uj,
    NULL                    AS dla_energy_uj
FROM energy_samples es;

PRAGMA integrity_check;

INSERT OR IGNORE INTO schema_version (version, applied_at, description)
VALUES (56, datetime('now'),
    'Unified energy schema: v_energy flat pivot view over legacy + new tables');
