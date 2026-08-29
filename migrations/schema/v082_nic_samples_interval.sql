-- v082: Add sample_start_ns and sample_end_ns to nic_samples
-- Root cause: v078 created nic_samples with sample_ns (point timestamp only).
-- Phase interval joins require sample_start_ns and sample_end_ns.
-- All other sample tables (cpu_samples, gpu_samples, interrupt_samples)
-- already have interval columns. This brings nic_samples into alignment.
-- Applies to: ALL platforms
--
-- Verify current version before applying:
--   sqlite3 $DB "SELECT MAX(version) FROM schema_version;"
-- Expected: 81

ALTER TABLE nic_samples ADD COLUMN sample_start_ns INTEGER;
ALTER TABLE nic_samples ADD COLUMN sample_end_ns INTEGER;

-- Backfill existing rows: NIC collector runs at 1 Hz so
-- sample_start_ns = sample_ns - 1 second, sample_end_ns = sample_ns
UPDATE nic_samples
SET sample_start_ns = sample_ns - 1000000000,
    sample_end_ns   = sample_ns
WHERE sample_start_ns IS NULL;

CREATE INDEX IF NOT EXISTS idx_nic_samples_interval
    ON nic_samples(run_id, sample_start_ns, sample_end_ns);
