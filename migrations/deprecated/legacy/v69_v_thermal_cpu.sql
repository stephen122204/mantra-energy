-- =============================================================================
-- MIGRATION v69: v_thermal_cpu backward compatibility view
-- =============================================================================
-- Purpose:
--   Maps thermal_samples_v2 to a cpu_temp interface that aggregate_run_stats
--   can query without platform-conditional logic. Only VALID samples from
--   CPU_PACKAGE or SOC zones are included.
--
-- Platform behavior:
--   Intel (UBUNTU2505): zone x86_pkg_temp has role CPU_PACKAGE.
--     One row per tick. cpu_temp = direct package temperature.
--
--   AMD (Alex): zone k10temp/zenpower has role CPU_PACKAGE.
--     Same as Intel.
--
--   GN100 (Grace aarch64): all 7 zones have role SOC.
--     Multiple rows per tick. aggregate_run_stats takes MAX() per timestamp
--     to get peak SoC temperature. This derivation rule is documented here,
--     NOT baked into the view — view returns all qualifying rows.
--
--   Apple M1 (Stephen): future. IOKit source_subsystem, role CPU_PACKAGE.
--
-- Note: v_thermal_cpu is a READ-ONLY view. Never INSERT into it.
--
-- SC-7: schema_version bump at bottom.
-- Run AFTER v68 on every machine DB.
-- =============================================================================

CREATE VIEW IF NOT EXISTS v_thermal_cpu AS
SELECT
    ts.run_id,
    ts.timestamp_ns,
    ts.temp_celsius     AS cpu_temp,
    tz.machine_id,
    tz.zone_id,
    tz.zone_type,
    tz.canonical_role
FROM thermal_samples_v2 ts
JOIN thermal_zones tz ON ts.zone_id = tz.zone_id
WHERE tz.canonical_role IN ('CPU_PACKAGE', 'SOC')
  AND ts.quality_flag = 'VALID'
  AND tz.active = 1;

-- =============================================================================
-- SC-7: schema_version bump
INSERT INTO schema_version (version, applied_at, description)
VALUES (69, datetime('now'),
    'v_thermal_cpu: backward compat view mapping thermal_samples_v2 CPU/SOC zones to cpu_temp');
