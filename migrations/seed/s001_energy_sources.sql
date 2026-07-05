-- s001_energy_sources.sql
-- Initial energy_sources rows. Split from the old v49 file, which mixed
-- DDL and seed data (see SPEC_MIGRATION_SYSTEM.md Chunk M3).

INSERT OR IGNORE INTO energy_sources
    (source_id, name, description, confidence, provenance, layer) VALUES
(1, 'RAPL',       'Intel RAPL sysfs uJ counters',                1.00, 'MEASURED', 'silicon'),
(2, 'SPBM',       'NVIDIA spark_hwmon SoC uJ accumulators',       1.00, 'MEASURED', 'silicon'),
(3, 'NVML',       'NVIDIA NVML cumulative mJ counter',            1.00, 'MEASURED', 'silicon'),
(4, 'DCGM',       'NVIDIA DCGM field 156 cumulative mJ',          1.00, 'MEASURED', 'silicon'),
(5, 'IOKIT',      'Apple IOKit power sensor W to uJ integration', 0.90, 'MEASURED', 'os'),
(6, 'AMD_ENERGY', 'AMD amd_energy kernel module uJ counters',     1.00, 'MEASURED', 'silicon'),
(7, 'SMI_INTEG',  'nvidia-smi power W x dt integration',          0.85, 'INFERRED', 'os'),
(8, 'MSR_PP1',    'Intel MSR 0x641 PP1 GPU domain uJ',            0.95, 'MEASURED', 'silicon'),
(9, 'SPBM_V2',    'NVIDIA spark_hwmon v2 SoC uJ (GH200)',         1.00, 'MEASURED', 'silicon');
