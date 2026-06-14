-- v13_gpu_pp1_energy.sql
-- GPU energy via MSR 0x641 (MSR_PP1_ENERGY_STATUS, Intel Iris Xe)
-- Read at run start/end using msr_read binary. Unit: 61.0352 µJ/LSB.
-- Platform: UBUNTU2505 (i7-1165G7, Tiger Lake). NULL on other platforms.

-- Part A1: energy_samples — store raw MSR counters + delta per sample
ALTER TABLE energy_samples ADD COLUMN gpu_start_uj  INTEGER;
ALTER TABLE energy_samples ADD COLUMN gpu_end_uj    INTEGER;
ALTER TABLE energy_samples ADD COLUMN gpu_energy_uj INTEGER;
-- gpu_energy_uj = (gpu_end_uj - gpu_start_uj) * 61.0352, stored in µJ
-- NULL when MSR 0x641 not readable on platform

-- Part A2: runs — ETL-populated GPU summary columns
ALTER TABLE runs ADD COLUMN gpu_total_energy_uj    INTEGER;
-- SUM(gpu_energy_uj) over all energy_samples for this run — ETL populated

ALTER TABLE runs ADD COLUMN gpu_baseline_energy_uj INTEGER;
-- baseline_rate_gpu_uj_per_ns * run_duration_ns — ETL populated

ALTER TABLE runs ADD COLUMN gpu_dynamic_energy_uj  INTEGER;
-- gpu_total_energy_uj - gpu_baseline_energy_uj — ETL populated

ALTER TABLE runs ADD COLUMN gpu_pct_of_pkg         REAL;
-- gpu_dynamic_energy_uj / dynamic_energy_uj * 100 — ETL populated

-- Schema version entry (DDL change)
INSERT INTO schema_version (version, applied_at, description)
VALUES (44, datetime('now'), 'GPU PP1 energy via MSR 0x641: energy_samples + runs columns');
