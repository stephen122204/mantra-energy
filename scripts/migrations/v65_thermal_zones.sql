-- =============================================================================
-- MIGRATION v65: thermal_zones registry
-- =============================================================================
-- Purpose:
--   Creates thermal_zones registry table. One row per unique thermal zone
--   per machine. Identity is (machine_id, zone_type, zone_index) — stable
--   across reboots even when kernel renumbers sysfs paths.
--
--   Adding a new platform = zero schema change. Just new rows at discovery.
--
-- Design:
--   - live sysfs path is NEVER stored (changes after reboot)
--   - canonical_role from THERMAL_ROLE_MAP (compile-time registry)
--   - active=0 for zones that disappeared since last discovery
--   - first_seen/last_seen for audit trail and degradation timeline
--
-- SC-7: schema_version bump at bottom.
-- Run AFTER v64 on every machine DB.
-- =============================================================================

CREATE TABLE IF NOT EXISTS thermal_zones (
    zone_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id          TEXT    NOT NULL,
    zone_type           TEXT    NOT NULL,
    zone_index          INTEGER NOT NULL,
    driver              TEXT,
    device              TEXT,
    canonical_role      TEXT    NOT NULL,
    source_subsystem    TEXT    NOT NULL DEFAULT 'thermal_zone',
    first_seen          TEXT    NOT NULL,
    last_seen           TEXT    NOT NULL,
    active              INTEGER NOT NULL DEFAULT 1,
    UNIQUE(machine_id, zone_type, zone_index)
);

-- Fast lookup for experiment queries
CREATE INDEX IF NOT EXISTS idx_thermal_zones_machine_role
    ON thermal_zones(machine_id, canonical_role);

CREATE INDEX IF NOT EXISTS idx_thermal_zones_active
    ON thermal_zones(machine_id, active);

-- =============================================================================
-- SC-7: schema_version bump
INSERT INTO schema_version (version, applied_at, description)
VALUES (65, datetime('now'),
    'thermal_zones registry: stable zone identity across reboots, canonical_role mapping');
