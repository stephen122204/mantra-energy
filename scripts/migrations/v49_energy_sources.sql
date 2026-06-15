-- v49_energy_sources.sql
-- Creates energy_sources lookup table.
-- One row per measurement interface (RAPL, SPBM, DCGM, NVML etc).
-- Adding a new platform = one INSERT here. Zero schema change.
-- cp to: scripts/migrations/v49_energy_sources.sql

CREATE TABLE IF NOT EXISTS energy_sources (
    source_id    INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL UNIQUE,
    description  TEXT,
    confidence   REAL    NOT NULL DEFAULT 1.0,
    provenance   TEXT    NOT NULL DEFAULT 'MEASURED',
    layer        TEXT    NOT NULL DEFAULT 'silicon'
);

INSERT OR IGNORE INTO energy_sources
    (source_id, name, description, confidence, provenance, layer) VALUES
(1, 'RAPL',       'Intel RAPL sysfs µJ counters',                1.00, 'MEASURED', 'silicon'),
(2, 'SPBM',       'NVIDIA spark_hwmon SoC µJ accumulators',       1.00, 'MEASURED', 'silicon'),
(3, 'NVML',       'NVIDIA NVML cumulative mJ counter',            1.00, 'MEASURED', 'silicon'),
(4, 'DCGM',       'NVIDIA DCGM field 156 cumulative mJ',          1.00, 'MEASURED', 'silicon'),
(5, 'IOKIT',      'Apple IOKit power sensor W to µJ integration', 0.90, 'MEASURED', 'os'),
(6, 'AMD_ENERGY', 'AMD amd_energy kernel module µJ counters',     1.00, 'MEASURED', 'silicon'),
(7, 'SMI_INTEG',  'nvidia-smi power W x dt integration',          0.85, 'INFERRED', 'os'),
(8, 'MSR_PP1',    'Intel MSR 0x641 PP1 GPU domain µJ',            0.95, 'MEASURED', 'silicon'),
(9, 'SPBM_V2',    'NVIDIA spark_hwmon v2 SoC µJ (GH200)',         1.00, 'MEASURED', 'silicon');

PRAGMA foreign_key_check;
PRAGMA integrity_check;

INSERT INTO schema_version (version, applied_at, description)
VALUES (49, datetime('now'), 'Unified energy schema: energy_sources lookup table');
