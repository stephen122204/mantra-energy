-- s002_energy_domains.sql
-- Canonical energy domain catalog. All 29 domains, all platforms.
-- Every platform gets every row. Unused domains on a given platform
-- are catalog entries, not active config (same way GN100 has UNIFIED
-- and Mac has SOC_PKG). INSERT OR IGNORE: fully idempotent.
--
-- Source of truth: GN100 live DB, 2026-07-05, verified against
-- schema.py CREATE TABLE (with reader_keys/legacy_column fix applied).
-- Replaces original s002 which had 23 rows and no reader_keys column.
--
-- See SPEC_SEED_DATA_COMPLETE.md for classification rules.

INSERT OR IGNORE INTO energy_domains
    (domain_id, name, description, parent_domain_id, is_leaf, is_cumulative, unit, reader_keys, legacy_column) VALUES
-- PACKAGE root: Intel/AMD/ARM CPU package hierarchy
(1,  'PACKAGE',     'Total SoC package energy',                                      NULL, 0, 1, 'uj', 'package-0,pkg',  'package_power_watts'),
(2,  'CORE',        'CPU core complex (Intel x86)',                                   1,   1, 1, 'uj', 'core,cpu',        'core_power_watts'),
(3,  'UNCORE',      'Uncore / system agent (Intel)',                                  1,   1, 1, 'uj', 'uncore',          'uncore_power_watts'),
(4,  'DRAM',        'Memory subsystem (Intel RAPL)',                                  1,   1, 1, 'uj', 'dram',            'dram_power_watts'),
(5,  'CPU_P',       'Performance cores (ARM Grace X925)',                             1,   1, 1, 'uj', 'cpu_p',           'core_power_watts'),
(6,  'CPU_E',       'Efficiency cores (ARM Grace A725)',                              1,   1, 1, 'uj', 'cpu_e',           NULL),
(7,  'GPU',         'GPU energy domain',                                              1,   1, 1, 'uj', 'gpu',             'gpu_power_watts'),
(8,  'CCD0',        'Core complex die 0 (AMD EPYC)',                                 1,   1, 1, 'uj', 'ccd0',            NULL),
(9,  'CCD1',        'Core complex die 1 (AMD EPYC)',                                 1,   1, 1, 'uj', 'ccd1',            NULL),
(10, 'IODIE',       'IO die (AMD EPYC)',                                              1,   1, 1, 'uj', NULL,              NULL),
-- UNIFIED root: Apple unified memory (CPU+GPU share one domain)
(11, 'UNIFIED',     'Unified CPU+GPU package (Apple M1/M2)',                          NULL, 0, 1, 'uj', NULL,              NULL),
(12, 'CPU_APPLE',   'Apple CPU cluster energy',                                       11,  1, 1, 'uj', 'cpu',             'core_power_watts'),
(13, 'GPU_APPLE',   'Apple GPU cluster energy',                                       11,  1, 1, 'uj', 'gpu_apple',       NULL),
-- NETWORK root: interconnect energy independent of CPU package
(14, 'NETWORK',     'Network interconnect energy root',                               NULL, 0, 1, 'uj', NULL,              NULL),
(15, 'NVLINK_C2C',  'NVLink-C2C die-to-die (GN100 GB10)',                            14,  1, 1, 'uj', NULL,              NULL),
(16, 'NVLINK',      'NVLink between discrete GPUs',                                   14,  1, 1, 'uj', NULL,              NULL),
(17, 'RDMA',        'RDMA operation energy',                                          14,  1, 1, 'uj', NULL,              NULL),
(18, 'INFINIBAND',  'InfiniBand link energy',                                         14,  1, 1, 'uj', NULL,              NULL),
-- ACCELERATOR root: on-chip accelerators
(19, 'ACCELERATOR', 'Accelerator energy root',                                        NULL, 0, 1, 'uj', NULL,              NULL),
(20, 'DLA',         'Deep Learning Accelerator (GN100 SPBM)',                         19,  1, 1, 'uj', NULL,              NULL),
(21, 'NPU',         'Neural Processing Unit (future)',                                 19,  1, 1, 'uj', NULL,              NULL),
-- STORAGE root
(22, 'STORAGE',     'Storage device energy root',                                      NULL, 0, 1, 'uj', NULL,              NULL),
(23, 'NVME',        'NVMe SSD energy',                                                 22,  1, 1, 'uj', NULL,              NULL),
-- GPU_DCGM: separate domain from GPU, DCGM field 156 compute-only
(24, 'GPU_DCGM',    'GPU compute-only energy via DCGM field 156 (GN100) or MSR PP1 (Tiger Lake)', 1, 1, 1, 'uj', 'gpu_dcgm', NULL),
-- SPBM power-channel telemetry domains (v76, instantaneous power not cumulative energy)
(25, 'SOC_PKG',     'SPBM soc_pkg power rail, sub-rail of package boundary',          1,   1, 0, 'mW', 'soc_pkg',         NULL),
(26, 'CPU_GPU',     'SPBM cpu_gpu combined power rail, sub-rail of package boundary', 1,   1, 0, 'mW', 'cpu_gpu',         NULL),
(27, 'VCORE',       'SPBM vcore voltage rail, sub-rail of package boundary',          1,   1, 0, 'mW', 'vcore',           NULL),
(28, 'DC_INPUT',    'SPBM dc_input rail, outermost system measurement boundary',      NULL, 1, 0, 'mW', 'dc_input',        NULL),
(29, 'PREREG',      'SPBM prereg power rail, sub-rail of package boundary',           1,   1, 0, 'mW', 'prereg',          NULL);
