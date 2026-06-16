-- v59: Run Power Limits
-- Firmware/driver power limits captured ONCE per run at experiment start.
-- These are operating constraints, not measurements.
-- If limits change mid-run (thermal throttle etc), see power_limit_events (v60).

CREATE TABLE IF NOT EXISTS run_power_limits (
    run_id    INTEGER NOT NULL,
    limit_id  INTEGER NOT NULL REFERENCES power_limits(limit_id),
    value_mw  REAL NOT NULL,
    PRIMARY KEY (run_id, limit_id)
);

INSERT OR IGNORE INTO schema_version VALUES
(59, datetime('now'), 'Run configuration: run_power_limits');
