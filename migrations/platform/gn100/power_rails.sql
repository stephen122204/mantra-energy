-- power_rails.sql (GN100 platform-specific)
-- SPBM hwmon power rail hierarchy for NVIDIA Grace GB10.
-- hwmon_channel and hw_config_key are hardware-specific: these rows
-- only apply to machines with the SPBM spark_hwmon driver.
-- Source of truth: GN100 live DB, 2026-07-05.

INSERT OR IGNORE INTO power_rails
    (rail_id, rail_name, device_type, parent_rail_id, rail_kind,
     hwmon_channel, hw_config_key, notes) VALUES
(1,  'dc_input',  'BOARD',        NULL, 'POWER', 'power7',  'dc_input',  'DC wall input after adapter'),
(2,  'sys_total', 'BOARD',        1,    'POWER', 'power1',  'sys_total', 'Total system draw'),
(3,  'soc_pkg',   'SOC',          2,    'POWER', 'power2',  'soc_pkg',   'Full SoC package'),
(4,  'cpu_gpu',   'SOC',          3,    'POWER', 'power3',  'cpu_gpu',   'CPU+GPU combined rail'),
(5,  'cpu_p',     'CPU',          4,    'POWER', 'power4',  'cpu_p',     'CPU performance cores'),
(6,  'cpu_e',     'CPU',          4,    'POWER', 'power5',  'cpu_e',     'CPU efficiency cores'),
(7,  'vcore',     'CPU',          4,    'POWER', 'power6',  'vcore',     'CPU vcore rail'),
(8,  'gpu',       'GPU',          4,    'POWER', 'power8',  'gpu',       'GPU compute rail'),
(9,  'prereg',    'BOARD',        3,    'POWER', 'power9',  'prereg',    'Pre-regulator board input'),
(10, 'dla',       'ACCELERATOR',  3,    'POWER', 'power10', 'dla',       'Deep Learning Accelerator');
