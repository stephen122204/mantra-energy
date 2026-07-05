-- ============================================================
-- MIGRATION 014: Add raw start/end columns to sample tables
-- Chunk 2: Sample Tables Schema Update
-- ============================================================
-- Design principle:
--   Keep ALL old columns for backward compatibility.
--   Add raw start/end values for reproducibility.
--   Add interval_ns for exact timing (no assumptions).
--   Tick columns go into interrupt_samples (same /proc/stat
--   read as interrupts — Chunk 3 promotes to proc_samples).
-- ============================================================

-- ------------------------------------------------------------
-- 1. energy_samples — add raw RAPL start/end per domain
-- ------------------------------------------------------------
ALTER TABLE energy_samples ADD COLUMN pkg_start_uj   INTEGER;
ALTER TABLE energy_samples ADD COLUMN pkg_end_uj     INTEGER;
ALTER TABLE energy_samples ADD COLUMN core_start_uj  INTEGER;
ALTER TABLE energy_samples ADD COLUMN core_end_uj    INTEGER;
ALTER TABLE energy_samples ADD COLUMN dram_start_uj  INTEGER;
ALTER TABLE energy_samples ADD COLUMN dram_end_uj    INTEGER;
ALTER TABLE energy_samples ADD COLUMN uncore_start_uj INTEGER;
ALTER TABLE energy_samples ADD COLUMN uncore_end_uj  INTEGER;
ALTER TABLE energy_samples ADD COLUMN interval_ns    INTEGER;
-- pkg_energy_uj, core_energy_uj etc kept for backward compat

-- ------------------------------------------------------------
-- 2. cpu_samples — add interval_ns only
--    (tick columns go to interrupt_samples — Option B decision)
-- ------------------------------------------------------------
ALTER TABLE cpu_samples ADD COLUMN interval_ns INTEGER;

-- ------------------------------------------------------------
-- 3. interrupt_samples — add raw count + ticks + interval
--    Ticks here because scheduler_monitor reads /proc/stat
--    for both interrupts and CPU ticks in same call (Chunk 2).
--    Chunk 3 (ProcReader) will promote ticks to proc_samples.
-- ------------------------------------------------------------
ALTER TABLE interrupt_samples ADD COLUMN interrupts_raw      INTEGER;
ALTER TABLE interrupt_samples ADD COLUMN user_ticks_start    INTEGER;
ALTER TABLE interrupt_samples ADD COLUMN user_ticks_end      INTEGER;
ALTER TABLE interrupt_samples ADD COLUMN system_ticks_start  INTEGER;
ALTER TABLE interrupt_samples ADD COLUMN system_ticks_end    INTEGER;
ALTER TABLE interrupt_samples ADD COLUMN interval_ns         INTEGER;
-- interrupts_per_sec kept for backward compat

-- ------------------------------------------------------------
-- 4. thermal_samples — add interval_ns
-- ------------------------------------------------------------
ALTER TABLE thermal_samples ADD COLUMN interval_ns INTEGER;

-- ------------------------------------------------------------
-- 5. Indexes — use IF NOT EXISTS (safe to re-run)
-- ------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_energy_samples_run_timestamp
    ON energy_samples(run_id, timestamp_ns);

CREATE INDEX IF NOT EXISTS idx_cpu_samples_run_timestamp
    ON cpu_samples(run_id, timestamp_ns);

CREATE INDEX IF NOT EXISTS idx_interrupt_samples_run_timestamp
    ON interrupt_samples(run_id, timestamp_ns);

CREATE INDEX IF NOT EXISTS idx_thermal_samples_run_timestamp
    ON thermal_samples(run_id, timestamp_ns);
