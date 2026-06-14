-- v14_idle_baseline_gpu.sql
-- Add GPU idle power to idle_baselines for baseline subtraction in ETL
-- Measured via MSR 0x641 during idle measurement. NULL on non-Tiger-Lake.

ALTER TABLE idle_baselines ADD COLUMN gpu_power_watts REAL;
-- GPU idle power in Watts. NULL if not measured on this platform.

ALTER TABLE idle_baselines ADD COLUMN gpu_std REAL;
-- Standard deviation of GPU idle power samples.

INSERT INTO schema_version (version, applied_at, description)
VALUES (45, datetime('now'), 'idle_baselines: gpu_power_watts + gpu_std columns');
