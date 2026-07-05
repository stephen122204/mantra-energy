-- =============================================================================
-- MIGRATION v67: thermal_samples_v2
-- =============================================================================
-- Purpose:
--   Normalized per-zone thermal samples. One row per zone per 1Hz tick.
--   Replaces the single cpu_temp float in thermal_samples with full zone
--   topology. Old thermal_samples kept read-only for provenance.
--
-- Design:
--   - zone_id FK to thermal_zones (stable identity, not sysfs path)
--   - quality_flag: VALID | OUT_OF_RANGE | READ_FAILED | MISSING
--   - invalid_reason: human-readable cause for non-VALID samples
--   - OUT_OF_RANGE samples stored for degradation audit (< -10 or > 125 C)
--   - global_run_id: cross-machine run correlation (NULL until populated)
--
-- Supports:
--   - Cross-platform thermal characterization of agentic AI workloads
--   - Per-zone thermal topology (which zone heats first under inference)
--   - Hardware degradation study via thermal stress cycle counting
--   - Rainbow library integration for rare earth metal lifetime modeling
--
-- SC-7: schema_version bump at bottom.
-- Run AFTER v66 on every machine DB.
-- =============================================================================

CREATE TABLE IF NOT EXISTS thermal_samples_v2 (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL,
    zone_id         INTEGER NOT NULL,
    timestamp_ns    INTEGER NOT NULL,
    temp_celsius    REAL    NOT NULL,
    quality_flag    TEXT    NOT NULL DEFAULT 'VALID',
    invalid_reason  TEXT,
    global_run_id   TEXT,
    FOREIGN KEY(run_id)  REFERENCES runs(run_id),
    FOREIGN KEY(zone_id) REFERENCES thermal_zones(zone_id)
);

-- Primary query pattern: all samples for a run in time order
CREATE INDEX IF NOT EXISTS idx_thermal_v2_run_time
    ON thermal_samples_v2(run_id, timestamp_ns);

-- Zone-level query: degradation study, per-zone time series
CREATE INDEX IF NOT EXISTS idx_thermal_v2_zone_time
    ON thermal_samples_v2(zone_id, timestamp_ns);

-- Quality filter: fast retrieval of VALID samples only
CREATE INDEX IF NOT EXISTS idx_thermal_v2_quality
    ON thermal_samples_v2(run_id, quality_flag);

-- =============================================================================
-- SC-7: schema_version bump
INSERT INTO schema_version (version, applied_at, description)
VALUES (67, datetime('now'),
    'thermal_samples_v2: normalized per-zone samples with quality_flag, supports degradation study');
