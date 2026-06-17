-- =============================================================================
-- MIGRATION v61: Normalized idle baseline domain storage
-- =============================================================================
-- Purpose:
--   idle_baselines had fixed RAPL columns (package_power_watts, core_power_watts).
--   GN100 SPBM exposes pkg, cpu_p, cpu_e, gpu. cpu_e had no column — silent drop.
--   This migration adds the normalized companion table idle_baseline_domains so
--   every domain every platform measures is stored, and three views so existing
--   queries against idle_baselines continue to work unchanged.
--
-- SC-7: schema_version bump at bottom of this file.
-- SC-5: no existing columns dropped or renamed.
-- Run on EVERY machine DB after git pull.
-- =============================================================================

-- Step 1: Add gpu_method and std_dev_json to idle_baselines
--   gpu_method: 'msr_pp1' (Tiger Lake MSR 0x641) | 'dcgm_f156' (GN100 DCGM)
--               | 'iokit' (Apple) | NULL (no GPU measurement)
--   std_dev_json: full JSON dump of std_dev_watts for all domains including
--                 those with no legacy std column (cpu_e, ccd0, etc.)
ALTER TABLE idle_baselines ADD COLUMN gpu_method   TEXT;
ALTER TABLE idle_baselines ADD COLUMN std_dev_json TEXT;

-- Step 2: Normalized domain table
--   One row per (baseline, domain). Stores power_watts and std_watts for
--   every domain read_energy() returned — nothing is filtered or dropped.
--   UNIQUE(baseline_id, domain_id) makes insert idempotent.
CREATE TABLE IF NOT EXISTS idle_baseline_domains (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    baseline_id TEXT    NOT NULL REFERENCES idle_baselines(baseline_id),
    domain_id   INTEGER NOT NULL REFERENCES energy_domains(domain_id),
    power_watts REAL    NOT NULL,
    std_watts   REAL    NOT NULL DEFAULT 0.0,
    UNIQUE(baseline_id, domain_id)
);

CREATE INDEX IF NOT EXISTS idx_ibd_baseline_id
    ON idle_baseline_domains(baseline_id);

CREATE INDEX IF NOT EXISTS idx_ibd_domain_id
    ON idle_baseline_domains(domain_id);

-- Step 3: v_idle_baselines — backward-compatible view
--   Reconstructs the old fixed-column shape from normalized storage.
--   COALESCE: if legacy column has a value use it (old rows before v61),
--   else reconstruct from idle_baseline_domains join.
--   Users query this exactly like the old table — SELECT * works unchanged.
CREATE VIEW IF NOT EXISTS v_idle_baselines AS
SELECT
    ib.baseline_id,
    ib.timestamp,
    ib.duration_seconds,
    ib.sample_count,
    ib.method,
    ib.gpu_method,
    ib.governor,
    ib.turbo,
    ib.background_cpu,
    ib.process_count,
    -- PACKAGE: covers RAPL 'package-0' and SPBM 'pkg' — both map to PACKAGE domain
    COALESCE(
        ib.package_power_watts,
        (SELECT ibd.power_watts
         FROM idle_baseline_domains ibd
         JOIN energy_domains ed ON ed.domain_id = ibd.domain_id
         WHERE ibd.baseline_id = ib.baseline_id AND ed.name = 'PACKAGE')
    ) AS package_power_watts,
    -- CORE: covers RAPL 'core' and SPBM 'cpu_p' — both map to core_power_watts
    COALESCE(
        ib.core_power_watts,
        (SELECT ibd.power_watts
         FROM idle_baseline_domains ibd
         JOIN energy_domains ed ON ed.domain_id = ibd.domain_id
         WHERE ibd.baseline_id = ib.baseline_id AND ed.name IN ('CORE', 'CPU_P')
         LIMIT 1)
    ) AS core_power_watts,
    COALESCE(
        ib.dram_power_watts,
        (SELECT ibd.power_watts
         FROM idle_baseline_domains ibd
         JOIN energy_domains ed ON ed.domain_id = ibd.domain_id
         WHERE ibd.baseline_id = ib.baseline_id AND ed.name = 'DRAM')
    ) AS dram_power_watts,
    COALESCE(
        ib.uncore_power_watts,
        (SELECT ibd.power_watts
         FROM idle_baseline_domains ibd
         JOIN energy_domains ed ON ed.domain_id = ibd.domain_id
         WHERE ibd.baseline_id = ib.baseline_id AND ed.name = 'UNCORE')
    ) AS uncore_power_watts,
    -- GPU: covers MSR PP1 (Tiger Lake) and DCGM f156 (GN100) — gpu_method tells which
    COALESCE(
        ib.gpu_power_watts,
        (SELECT ibd.power_watts
         FROM idle_baseline_domains ibd
         JOIN energy_domains ed ON ed.domain_id = ibd.domain_id
         WHERE ibd.baseline_id = ib.baseline_id AND ed.name = 'GPU')
    ) AS gpu_power_watts,
    ib.package_std,
    ib.core_std,
    ib.dram_std,
    ib.uncore_std,
    ib.gpu_std
FROM idle_baselines ib;

-- Step 4: v_idle_baseline_domains — full domain coverage per baseline
--   Shows every domain every platform measured. Used for paper methodology docs
--   and cross-platform baseline comparison queries.
CREATE VIEW IF NOT EXISTS v_idle_baseline_domains AS
SELECT
    ibd.baseline_id,
    ed.name         AS domain_name,
    ibd.power_watts,
    ibd.std_watts,
    ib.timestamp,
    ib.method,
    ib.gpu_method
FROM idle_baseline_domains ibd
JOIN energy_domains  ed ON ed.domain_id   = ibd.domain_id
JOIN idle_baselines  ib ON ib.baseline_id = ibd.baseline_id;

-- Step 5: v_platform_baseline_summary — per-platform overview
--   domain_count and domains_measured show which platform this baseline came from.
--   GN100: domain_count=4, domains_measured='PACKAGE,CPU_P,CPU_E,GPU'
--   UBUNTU2505: domain_count=2..4 depending on RAPL availability
CREATE VIEW IF NOT EXISTS v_platform_baseline_summary AS
SELECT
    ib.baseline_id,
    ib.timestamp,
    COUNT(ibd.id)               AS domain_count,
    GROUP_CONCAT(ed.name, ', ') AS domains_measured,
    ib.method,
    ib.gpu_method,
    ib.governor
FROM idle_baselines ib
LEFT JOIN idle_baseline_domains ibd ON ibd.baseline_id = ib.baseline_id
LEFT JOIN energy_domains        ed  ON ed.domain_id    = ibd.domain_id
GROUP BY ib.baseline_id;

-- SC-7: schema_version bump
INSERT INTO schema_version (version, applied_at, description)
VALUES (61, datetime('now'),
    'idle_baseline_domains normalized domain table + v_idle_baselines + gpu_method + std_dev_json');
