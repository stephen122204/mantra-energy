-- Migration v78: SPEC_03A NIC Observability
-- Adds nic_samples table for NIC byte counter telemetry
-- Adds NIC validation columns to network_energy_attribution
--
-- Verify current version before applying:
--   sqlite3 $DB "SELECT MAX(version) FROM schema_version;"
-- Expected: 77

-- NIC byte counter samples — one row per sample interval per run
-- Collected at same cadence as energy_samples (100Hz target)
-- tx_bytes/rx_bytes are cumulative kernel counters (monotonic)
CREATE TABLE IF NOT EXISTS nic_samples (
    sample_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL,
    sample_ns    INTEGER NOT NULL,   -- timestamp_ns at sample time
    interface    TEXT,               -- e.g. wlp0s20f3, eth0
    tx_bytes     INTEGER,            -- cumulative bytes transmitted
    rx_bytes     INTEGER,            -- cumulative bytes received
    tx_packets   INTEGER,            -- cumulative packets transmitted
    rx_packets   INTEGER,            -- cumulative packets received
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_nic_samples_run_ns
    ON nic_samples(run_id, sample_ns);

-- Add NIC validation columns to network_energy_attribution
-- NULL = SPEC_03A not deployed or not checked (MIC-3 compliant)
ALTER TABLE network_energy_attribution
    ADD COLUMN nic_activity_validated INTEGER;
    -- 1=True (NIC active in at least one window)
    -- 0=False (NIC idle in all windows)
    -- NULL=not checked (SPEC_03A not deployed)

ALTER TABLE network_energy_attribution
    ADD COLUMN nic_adjusted_confidence REAL;
    -- Confidence after NIC validation adjustment
    -- NULL if SPEC_03A not checked

ALTER TABLE network_energy_attribution
    ADD COLUMN nic_coverage_fraction REAL;
    -- Fraction of blocking windows with NIC telemetry data
    -- NULL if SPEC_03A not checked

INSERT INTO schema_version (version, applied_at, description)
VALUES (78, datetime('now'), 'SPEC_03A NIC observability: nic_samples table + validation columns');
