-- =============================================================================
-- MIGRATION v62: energy_domains mapping metadata (documentation only)
-- =============================================================================
-- Purpose:
--   Adds reader_keys and legacy_column to energy_domains as audit trail.
--   These columns are NEVER queried at runtime.
--   BASELINE_DOMAIN_MAP in core/utils/idle_baseline.py is the runtime authority.
--   These columns exist so a paper reviewer can query:
--       SELECT name, reader_keys, legacy_column FROM energy_domains
--   and understand exactly how raw reader output maps to canonical domains
--   and which idle_baselines fixed column each domain populates.
--
-- Migration history invariant: v50 is never modified. This is v62.
-- SC-7: schema_version bump at bottom.
-- Run AFTER v61 on every machine DB.
-- =============================================================================

ALTER TABLE energy_domains ADD COLUMN reader_keys   TEXT;
ALTER TABLE energy_domains ADD COLUMN legacy_column TEXT;

-- Populate mapping metadata for all 23 domains
-- reader_keys: comma-separated raw keys any reader may return for this domain
-- legacy_column: fixed column in idle_baselines that this domain populates,
--                NULL means domain has no legacy column (stored only in idle_baseline_domains)

UPDATE energy_domains
SET reader_keys = 'package-0,pkg', legacy_column = 'package_power_watts'
WHERE name = 'PACKAGE';

UPDATE energy_domains
SET reader_keys = 'core,cpu', legacy_column = 'core_power_watts'
WHERE name = 'CORE';

-- CPU_P (SPBM P-cores) maps to core_power_watts — analogous to RAPL core
UPDATE energy_domains
SET reader_keys = 'cpu_p', legacy_column = 'core_power_watts'
WHERE name = 'CPU_P';

-- CPU_E (SPBM E-cores) has no legacy column — stored only in idle_baseline_domains
UPDATE energy_domains
SET reader_keys = 'cpu_e', legacy_column = NULL
WHERE name = 'CPU_E';

UPDATE energy_domains
SET reader_keys = 'dram', legacy_column = 'dram_power_watts'
WHERE name = 'DRAM';

UPDATE energy_domains
SET reader_keys = 'uncore', legacy_column = 'uncore_power_watts'
WHERE name = 'UNCORE';

-- GPU covers MSR PP1 (Tiger Lake) and DCGM f156 (GN100) and SPBM gpu rail
-- gpu_method column in idle_baselines distinguishes which measurement was used
UPDATE energy_domains
SET reader_keys = 'gpu,gpu_dcgm', legacy_column = 'gpu_power_watts'
WHERE name = 'GPU';

-- AMD domains — no legacy columns, future Chunk 16E
UPDATE energy_domains
SET reader_keys = 'ccd0', legacy_column = NULL
WHERE name = 'CCD0';

UPDATE energy_domains
SET reader_keys = 'ccd1', legacy_column = NULL
WHERE name = 'CCD1';

-- Apple Silicon — no legacy columns, future Chunk 16F
UPDATE energy_domains
SET reader_keys = 'gpu_apple', legacy_column = NULL
WHERE name = 'GPU_APPLE';

UPDATE energy_domains
SET reader_keys = 'cpu', legacy_column = 'core_power_watts'
WHERE name = 'CPU_APPLE';

-- Remaining domains: no current reader, legacy_column NULL
-- UNCORE, IODIE, UNIFIED, NETWORK, NVLINK_C2C, NVLINK, RDMA,
-- INFINIBAND, ACCELERATOR, DLA, NPU, STORAGE, NVME
-- reader_keys and legacy_column left NULL — populated when readers ship

-- SC-7: schema_version bump
INSERT INTO schema_version (version, applied_at, description)
VALUES (62, datetime('now'),
    'energy_domains reader_keys and legacy_column documentation metadata (not queried at runtime)');
