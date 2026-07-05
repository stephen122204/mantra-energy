-- =============================================================================
-- MIGRATION v66: cooling_devices registry
-- =============================================================================
-- Purpose:
--   Creates cooling_devices registry table. One row per unique cooling
--   actuator per machine. Mirrors thermal_zones design exactly.
--
--   Cooling devices include:
--     - CPU frequency throttle (Processor)
--     - PCIe link speed reduction (PCIe_Port_Link_Speed_*)
--     - Intel power clamp (intel_powerclamp)
--     - TCC offset (TCC Offset)
--     - Fans (Fan)
--
--   GN100 has cooling_device26 with cur_state=-231 (kernel bug).
--   OUT_OF_RANGE samples stored for audit — never used in analysis.
--
-- SC-7: schema_version bump at bottom.
-- Run AFTER v65 on every machine DB.
-- =============================================================================

CREATE TABLE IF NOT EXISTS cooling_devices (
    device_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id          TEXT    NOT NULL,
    device_type         TEXT    NOT NULL,
    device_index        INTEGER NOT NULL,
    driver              TEXT,
    device              TEXT,
    canonical_role      TEXT    NOT NULL,
    source_subsystem    TEXT    NOT NULL DEFAULT 'thermal_zone',
    max_state           INTEGER NOT NULL DEFAULT 0,
    first_seen          TEXT    NOT NULL,
    last_seen           TEXT    NOT NULL,
    active              INTEGER NOT NULL DEFAULT 1,
    UNIQUE(machine_id, device_type, device_index)
);

CREATE INDEX IF NOT EXISTS idx_cooling_devices_machine_role
    ON cooling_devices(machine_id, canonical_role);

CREATE INDEX IF NOT EXISTS idx_cooling_devices_active
    ON cooling_devices(machine_id, active);

-- =============================================================================
-- SC-7: schema_version bump
INSERT INTO schema_version (version, applied_at, description)
VALUES (66, datetime('now'),
    'cooling_devices registry: actuator identity, canonical_role, throttle state tracking');
