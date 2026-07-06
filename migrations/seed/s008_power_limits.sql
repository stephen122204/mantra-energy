-- s008_power_limits.sql
-- Power limit type definitions. Universal, all platforms.
-- These are abstract limit categories (PL1/PL2/SYSPL1/SYSPL2),
-- not hardware-specific values. Actual limit values per run are
-- stored in run_power_limits (populated by SPBM reader at runtime).
-- Source of truth: GN100 live DB, 2026-07-05.
-- See SPEC_SEED_DATA_COMPLETE.md for classification rules.

INSERT OR IGNORE INTO power_limits
    (limit_id, limit_name, description, units) VALUES
(1, 'PL1',    'Sustained power limit (SOC)',    'mw'),
(2, 'PL2',    'Burst power limit (SOC)',        'mw'),
(3, 'SYSPL1', 'Sustained power limit (system)', 'mw'),
(4, 'SYSPL2', 'Burst power limit (system)',     'mw');
