-- v54_device_telemetry.sql
-- Instantaneous device state: power, temperature, utilization, clock.
-- Replaces gpu_samples concept going forward (gpu_samples stays untouched).
-- energy_uj nullable: present for NVML/DCGM, NULL for SMI_INTEG.
-- device_type: 'GPU', 'SOC', 'CPU', 'NETWORK', 'STORAGE'
-- dc_input_mw: wall power from SPBM dc_input channel (SOC device_type).
-- run_id and global_run_id denormalized for sync_client fetch.
-- cp to: scripts/migrations/v54_device_telemetry.sql

CREATE TABLE IF NOT EXISTS device_telemetry (
    telemetry_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES runs(run_id),
    global_run_id TEXT,
    source_id     INTEGER NOT NULL REFERENCES energy_sources(source_id),
    timestamp_ns  BIGINT  NOT NULL,
    interval_ns   BIGINT  NOT NULL,
    device_type   TEXT    NOT NULL,
    power_mw      REAL,
    energy_uj     REAL,
    util_pct      REAL,
    temp_c        REAL,
    clock_mhz     REAL,
    dc_input_mw   REAL,
    mem_util_pct  REAL
);

CREATE INDEX IF NOT EXISTS idx_dt_run
    ON device_telemetry(run_id);
CREATE INDEX IF NOT EXISTS idx_dt_run_device
    ON device_telemetry(run_id, device_type);
CREATE INDEX IF NOT EXISTS idx_dt_time
    ON device_telemetry(run_id, timestamp_ns);

PRAGMA foreign_key_check;
PRAGMA integrity_check;

INSERT INTO schema_version (version, applied_at, description)
VALUES (54, datetime('now'), 'Unified energy schema: device_telemetry table');
