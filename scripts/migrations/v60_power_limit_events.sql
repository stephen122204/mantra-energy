-- v60: Power Limit Events
-- Optional history table for mid-run limit changes.
-- Most runs will have zero rows here.
-- Created now for schema completeness. Populated only when firmware
-- dynamically adjusts limits (thermal throttle, driver intervention etc).
-- Avoids retrofitting schema later when this case is encountered.

CREATE TABLE IF NOT EXISTS power_limit_events (
    event_id     INTEGER PRIMARY KEY,
    run_id       INTEGER NOT NULL,
    timestamp_ns INTEGER NOT NULL,
    limit_id     INTEGER NOT NULL REFERENCES power_limits(limit_id),
    old_value_mw REAL,
    new_value_mw REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ple_run_time
    ON power_limit_events(run_id, timestamp_ns);

INSERT OR IGNORE INTO schema_version VALUES
(60, datetime('now'), 'Power limit history: power_limit_events (future-proof)');
