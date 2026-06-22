-- v76_spbm_full_telemetry.sql
-- SPEC_SPBM_FULL_TELEMETRY implementation
-- Adds 6 new power-channel telemetry domains, a firmware power-limit
-- snapshot table (kept separate from telemetry per spec Section 3/6b),
-- and run-level sampling quality columns.
--
-- Verified prerequisites (2026-06-21, GN100):
--   - energy_domains MAX(domain_id) = 24 before v75; this migration runs
--     after v75, so next available id is 25 for 5 of the 6 new channels.
--   - DLA is the exception: core/readers/energy_sample_v2.py already
--     defines DOMAIN_DLA = 20 (comment: "(GN100 SPBM)"), reserved but
--     never seeded into energy_domains or wired up. This migration uses
--     id 20 for DLA, not a new id, to avoid two domain_ids both meaning
--     "DLA". Found during prerequisite grep of energy_sample_v2.py,
--     lines 15-45, before writing this migration — not assumed.
--   - hardware_config table exists but is a per-machine detection snapshot
--     (cpu_model, gpu_driver, rapl_domains, detected_at) — NOT the right
--     table for per-run firmware limits. New table used instead, named
--     to avoid collision with the existing hardware_config table.
--   - runs already has phase_sample_coverage_pct and energy_sample_coverage_pct
--     (temporal coverage: sample_span_ns / task_duration_ns). New
--     spbm_sample_coverage_pct is COUNT-based (samples_observed /
--     samples_expected) — a different definition, documented as such
--     to avoid confusion with the existing temporal-coverage columns.

-- 1. New telemetry domains. is_cumulative=0: these are instantaneous power
--    readings requiring integration, unlike the 4 existing cumulative
--    energy-counter domains (pkg, cpu_p, cpu_e, gpu).
INSERT INTO energy_domains (domain_id, name, description, parent_domain_id, is_leaf, is_cumulative, unit, reader_keys)
VALUES
    (25, 'SOC_PKG',  'SPBM soc_pkg power rail, sub-rail of package boundary',          1,    1, 0, 'mW', 'soc_pkg'),
    (26, 'CPU_GPU',  'SPBM cpu_gpu combined power rail, sub-rail of package boundary', 1,    1, 0, 'mW', 'cpu_gpu'),
    (27, 'VCORE',    'SPBM vcore voltage rail, sub-rail of package boundary',          1,    1, 0, 'mW', 'vcore'),
    (28, 'DC_INPUT', 'SPBM dc_input rail, outermost system measurement boundary. Physical measurement point not yet verified against vendor docs (see SPEC_SPBM_FULL_TELEMETRY Section 7b)', NULL, 1, 0, 'mW', 'dc_input'),
    (29, 'PREREG',   'SPBM prereg power rail, sub-rail of package boundary',           1,    1, 0, 'mW', 'prereg');

-- DLA uses domain_id 20, NOT a new id. core/readers/energy_sample_v2.py
-- already reserves DOMAIN_DLA = 20 with comment "(GN100 SPBM)" — this
-- slot was anticipated but never seeded into energy_domains or wired up.
-- Found 2026-06-21 during prerequisite verification. Using the existing
-- reserved id avoids two domain_ids both meaning "DLA".
-- CORRECTION (applied on UBUNTU2505 2026-06-22): domain_id 20 already
-- existed as a live row ("DLA", "Deep Learning Accelerator (GN100
-- SPBM)") before this migration ran — someone had already seeded it,
-- matching the reserved constant but never connected to a reader.
-- INSERT OR IGNORE used so this statement is a correct no-op on a
-- machine where the row already exists, instead of erroring.
INSERT OR IGNORE INTO energy_domains (domain_id, name, description, parent_domain_id, is_leaf, is_cumulative, unit, reader_keys)
VALUES
    (20, 'DLA', 'SPBM dla (deep learning accelerator) power rail, sub-rail of package boundary. domain_id 20 was already reserved as DOMAIN_DLA in core/readers/energy_sample_v2.py prior to this spec.', 1, 1, 0, 'mW', 'dla');

-- 2. Firmware power-limit snapshot table. Explicitly NOT energy_sample_domains
--    or energy_domains — these are configuration values (firmware-enforced
--    caps), not consumption telemetry. Named run_power_limits to avoid
--    confusion with the existing hardware_config table (per-machine
--    detection snapshot, unrelated purpose).
CREATE TABLE IF NOT EXISTS run_power_limits (
    limit_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL,
    limit_key       TEXT NOT NULL,      -- 'pl1' | 'pl2' | 'syspl1' | 'syspl2'
    limit_value_mw  REAL,
    captured_at     REAL DEFAULT (unixepoch()),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_run_power_limits_run
    ON run_power_limits(run_id);

-- 3. Sampling quality columns on runs. COUNT-based coverage, distinct from
--    existing TEMPORAL coverage columns (phase_sample_coverage_pct,
--    energy_sample_coverage_pct). Scoped to SPBM power-channel sampling
--    specifically (sys_total/cpu_p/cpu_e/gpu/soc_pkg/cpu_gpu/vcore/
--    dc_input/prereg/dla), not the cumulative energy counters which need
--    no integration and therefore no coverage tracking.
ALTER TABLE runs ADD COLUMN spbm_power_sampling_freq_hz REAL    DEFAULT NULL;
ALTER TABLE runs ADD COLUMN spbm_samples_expected        INTEGER DEFAULT NULL;
ALTER TABLE runs ADD COLUMN spbm_samples_observed        INTEGER DEFAULT NULL;
ALTER TABLE runs ADD COLUMN spbm_sample_coverage_pct     REAL    DEFAULT NULL;
ALTER TABLE runs ADD COLUMN spbm_integration_method      TEXT    DEFAULT NULL;

-- 4. Derived conversion metrics (computed at ETL time from dc_input + pkg).
ALTER TABLE runs ADD COLUMN spbm_conversion_loss_uj      INTEGER DEFAULT NULL;
ALTER TABLE runs ADD COLUMN spbm_conversion_efficiency   REAL    DEFAULT NULL;

INSERT INTO schema_version (version, applied_at, description)
VALUES (
    76,
    datetime('now'),
    'SPBM full power telemetry: 6 new power-channel domains (SOC_PKG 25, CPU_GPU 26, VCORE 27, DC_INPUT 28, PREREG 29, DLA 20 [reusing pre-existing reserved id from energy_sample_v2.py]), run_power_limits table for firmware caps (pl1/pl2/syspl1/syspl2, kept separate from telemetry), spbm_sample_coverage_pct (count-based, distinct from existing temporal coverage columns), spbm_conversion_loss_uj + spbm_conversion_efficiency derived from dc_input vs pkg. dc_input physical meaning not yet verified against vendor docs - rail referred to only by SPBM driver label until confirmed.'
);
