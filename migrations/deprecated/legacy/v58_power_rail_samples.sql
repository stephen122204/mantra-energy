-- v58: Power Rail Samples
-- High-frequency instantaneous power time series.
-- Decoupled from energy_samples_v2 — independent timestamp, independent frequency.
-- ETL integrates power_mw x interval_ns -> energy_derived_metrics.

CREATE TABLE IF NOT EXISTS power_rail_samples (
    rail_sample_id INTEGER PRIMARY KEY,
    run_id         INTEGER NOT NULL,
    timestamp_ns   INTEGER NOT NULL,
    interval_ns    INTEGER,             -- NULL for first sample (no prior tick)
    rail_id        INTEGER NOT NULL REFERENCES power_rails(rail_id),
    power_mw       REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prs_run_time
    ON power_rail_samples(run_id, timestamp_ns);

CREATE INDEX IF NOT EXISTS idx_prs_rail
    ON power_rail_samples(rail_id, run_id);

INSERT OR IGNORE INTO schema_version VALUES
(58, datetime('now'), 'Power rail time series: power_rail_samples');
