-- v57: Power Rail Registries
-- power_rails: dynamic measurement rails (POWER/ESTIMATE kinds)
-- power_limits: firmware/driver configuration limits (LIMIT kind)
-- GN100 seed data included. Other platforms add rows here with no schema change.

CREATE TABLE IF NOT EXISTS power_rails (
    rail_id        INTEGER PRIMARY KEY,
    rail_name      TEXT NOT NULL UNIQUE,
    device_type    TEXT NOT NULL,        -- SOC, CPU, GPU, BOARD, ACCELERATOR
    parent_rail_id INTEGER REFERENCES power_rails(rail_id),
    rail_kind      TEXT NOT NULL DEFAULT 'POWER', -- POWER, ESTIMATE, CONTROL
    hwmon_channel  TEXT,                 -- e.g. power7 (informational only)
    hw_config_key  TEXT,                 -- key in hw_config.json power_paths dict
    notes          TEXT
);

CREATE TABLE IF NOT EXISTS power_limits (
    limit_id    INTEGER PRIMARY KEY,
    limit_name  TEXT NOT NULL UNIQUE,
    description TEXT,
    units       TEXT NOT NULL DEFAULT 'mw'
);

-- GN100 power_rails seed (10 POWER rails only, no limits)
-- Topology: dc_input -> sys_total -> soc_pkg -> cpu_gpu -> {cpu_p, cpu_e, vcore, gpu}
--                                            -> prereg
--                                            -> dla
INSERT OR IGNORE INTO power_rails VALUES
(1,  'dc_input',  'BOARD',       NULL, 'POWER', 'power7',  'dc_input',  'DC wall input after adapter'),
(2,  'sys_total', 'BOARD',       1,    'POWER', 'power1',  'sys_total', 'Total system draw'),
(3,  'soc_pkg',   'SOC',         2,    'POWER', 'power2',  'soc_pkg',   'Full SoC package'),
(4,  'cpu_gpu',   'SOC',         3,    'POWER', 'power3',  'cpu_gpu',   'CPU+GPU combined rail'),
(5,  'cpu_p',     'CPU',         4,    'POWER', 'power4',  'cpu_p',     'CPU performance cores'),
(6,  'cpu_e',     'CPU',         4,    'POWER', 'power5',  'cpu_e',     'CPU efficiency cores'),
(7,  'vcore',     'CPU',         4,    'POWER', 'power6',  'vcore',     'CPU vcore rail'),
(8,  'gpu',       'GPU',         4,    'POWER', 'power8',  'gpu',       'GPU compute rail'),
(9,  'prereg',    'BOARD',       3,    'POWER', 'power9',  'prereg',    'Pre-regulator board input'),
(10, 'dla',       'ACCELERATOR', 3,    'POWER', 'power10', 'dla',       'Deep Learning Accelerator');

-- power_limits seed (GN100 firmware limits)
INSERT OR IGNORE INTO power_limits VALUES
(1, 'PL1',    'Sustained power limit (SOC)',      'mw'),
(2, 'PL2',    'Burst power limit (SOC)',           'mw'),
(3, 'SYSPL1', 'Sustained power limit (system)',   'mw'),
(4, 'SYSPL2', 'Burst power limit (system)',        'mw');

INSERT OR IGNORE INTO schema_version VALUES
(57, datetime('now'), 'Power rail registries: power_rails + power_limits');
