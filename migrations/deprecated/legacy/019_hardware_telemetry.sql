-- Migration 019: Hardware Telemetry (Cache, I/O, Voltage, Fan)
-- Adds L1/L2/L3 cache to cpu_samples, creates io_samples,
-- adds voltage/fan to thermal_samples, adds 7 aggregate cols to runs.

-- 1. Cache columns on cpu_samples
ALTER TABLE cpu_samples ADD COLUMN l1d_cache_misses BIGINT;
ALTER TABLE cpu_samples ADD COLUMN l2_cache_misses  BIGINT;
ALTER TABLE cpu_samples ADD COLUMN l3_cache_hits    BIGINT;
ALTER TABLE cpu_samples ADD COLUMN l3_cache_misses  BIGINT;

-- 2. Voltage + fan on thermal_samples
ALTER TABLE thermal_samples ADD COLUMN voltage_vcore REAL;
ALTER TABLE thermal_samples ADD COLUMN fan_rpm       INTEGER;

-- 3. Run-level aggregates on runs
ALTER TABLE runs ADD COLUMN l1d_cache_misses_total  BIGINT;
ALTER TABLE runs ADD COLUMN l2_cache_misses_total   BIGINT;
ALTER TABLE runs ADD COLUMN l3_cache_hits_total     BIGINT;
ALTER TABLE runs ADD COLUMN l3_cache_misses_total   BIGINT;
ALTER TABLE runs ADD COLUMN disk_read_bytes_total   BIGINT;
ALTER TABLE runs ADD COLUMN disk_write_bytes_total  BIGINT;
ALTER TABLE runs ADD COLUMN voltage_vcore_avg       REAL;

-- 4. io_samples table (new)
CREATE TABLE IF NOT EXISTS io_samples (
    sample_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL,
    sample_start_ns INTEGER NOT NULL,
    sample_end_ns   INTEGER NOT NULL,
    interval_ns     INTEGER NOT NULL,
    device          TEXT,
    disk_read_bytes  BIGINT,
    disk_write_bytes BIGINT,
    io_block_time_ms REAL,
    disk_latency_ms  REAL,
    minor_page_faults INTEGER,
    major_page_faults INTEGER,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

-- 5. Indexes
CREATE INDEX IF NOT EXISTS idx_io_samples_run      ON io_samples(run_id);
CREATE INDEX IF NOT EXISTS idx_io_samples_run_time ON io_samples(run_id, sample_start_ns);
CREATE INDEX IF NOT EXISTS idx_cpu_samples_run     ON cpu_samples(run_id);
CREATE INDEX IF NOT EXISTS idx_thermal_samples_run ON thermal_samples(run_id);
