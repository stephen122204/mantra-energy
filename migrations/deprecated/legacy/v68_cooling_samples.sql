-- =============================================================================
-- MIGRATION v68: cooling_samples
-- =============================================================================
-- Purpose:
--   1Hz cooling device state samples. One row per device per tick.
--   Enables throttle detection, PCIe link speed monitoring, and
--   thermal management correlation with energy and temperature data.
--
-- Design:
--   - device_id FK to cooling_devices (stable identity)
--   - cur_state: raw kernel value (may be negative on GN100 — captured as
--     OUT_OF_RANGE for audit, never used in throttle detection)
--   - quality_flag: VALID | OUT_OF_RANGE | READ_FAILED | MISSING
--
-- Throttle detection query:
--   SELECT COUNT(*) FROM cooling_samples cs
--   JOIN cooling_devices cd ON cs.device_id = cd.device_id
--   WHERE cs.run_id = ? AND cd.canonical_role = 'CPU_FREQ_THROTTLE'
--     AND cs.quality_flag = 'VALID' AND cs.cur_state > 0
--
-- SC-7: schema_version bump at bottom.
-- Run AFTER v67 on every machine DB.
-- =============================================================================

CREATE TABLE IF NOT EXISTS cooling_samples (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL,
    device_id       INTEGER NOT NULL,
    timestamp_ns    INTEGER NOT NULL,
    cur_state       INTEGER NOT NULL,
    quality_flag    TEXT    NOT NULL DEFAULT 'VALID',
    invalid_reason  TEXT,
    global_run_id   TEXT,
    FOREIGN KEY(run_id)    REFERENCES runs(run_id),
    FOREIGN KEY(device_id) REFERENCES cooling_devices(device_id)
);

CREATE INDEX IF NOT EXISTS idx_cooling_samples_run_time
    ON cooling_samples(run_id, timestamp_ns);

CREATE INDEX IF NOT EXISTS idx_cooling_samples_device_time
    ON cooling_samples(device_id, timestamp_ns);

-- Fast throttle detection query
CREATE INDEX IF NOT EXISTS idx_cooling_samples_throttle
    ON cooling_samples(run_id, quality_flag, cur_state);

-- =============================================================================
-- SC-7: schema_version bump
INSERT INTO schema_version (version, applied_at, description)
VALUES (68, datetime('now'),
    'cooling_samples: 1Hz cooling device state, throttle detection, PCIe link speed tracking');
