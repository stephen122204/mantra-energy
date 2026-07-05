-- s002_energy_domains.sql
-- Initial energy_domains rows. Split from the old v50 file, which mixed
-- DDL and seed data (see SPEC_MIGRATION_SYSTEM.md Chunk M3).

INSERT OR IGNORE INTO energy_domains
    (domain_id, name, description, parent_domain_id, is_leaf, is_cumulative) VALUES
-- PACKAGE root: Intel/AMD/ARM CPU package hierarchy
(1,  'PACKAGE',    'Total SoC package energy',               NULL, 0, 1),
(2,  'CORE',       'CPU core complex (Intel x86)',            1,    1, 1),
(3,  'UNCORE',     'Uncore / system agent (Intel)',           1,    1, 1),
(4,  'DRAM',       'Memory subsystem (Intel RAPL)',           1,    1, 1),
(5,  'CPU_P',      'Performance cores (ARM Grace X925)',      1,    1, 1),
(6,  'CPU_E',      'Efficiency cores (ARM Grace A725)',       1,    1, 1),
(7,  'GPU',        'GPU energy domain',                      1,    1, 1),
(8,  'CCD0',       'Core complex die 0 (AMD EPYC)',           1,    1, 1),
(9,  'CCD1',       'Core complex die 1 (AMD EPYC)',           1,    1, 1),
(10, 'IODIE',      'IO die (AMD EPYC)',                       1,    1, 1),
-- UNIFIED root: Apple unified memory (CPU+GPU share one domain)
(11, 'UNIFIED',    'Unified CPU+GPU package (Apple M1/M2)',   NULL, 0, 1),
(12, 'CPU_APPLE',  'Apple CPU cluster energy',                11,   1, 1),
(13, 'GPU_APPLE',  'Apple GPU cluster energy',                11,   1, 1),
-- NETWORK root: interconnect energy independent of CPU package
(14, 'NETWORK',    'Network interconnect energy root',        NULL, 0, 1),
(15, 'NVLINK_C2C', 'NVLink-C2C die to die (GN100 GB10)',     14,   1, 1),
(16, 'NVLINK',     'NVLink between discrete GPUs',            14,   1, 1),
(17, 'RDMA',       'RDMA operation energy',                   14,   1, 1),
(18, 'INFINIBAND', 'InfiniBand link energy',                  14,   1, 1),
-- ACCELERATOR root: on chip accelerators (may be independent rail)
(19, 'ACCELERATOR','Accelerator energy root',                 NULL, 0, 1),
(20, 'DLA',        'Deep Learning Accelerator (GN100 SPBM)', 19,   1, 1),
(21, 'NPU',        'Neural Processing Unit (future)',         19,   1, 1),
-- STORAGE root: future NVMe/SSD energy measurement
(22, 'STORAGE',    'Storage device energy root',              NULL, 0, 1),
(23, 'NVME',       'NVMe SSD energy',                         22,   1, 1);
