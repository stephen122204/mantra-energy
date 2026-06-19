"""
core.thermal — Thermal and cooling subsystem for A-LEMS.

Provides cross-platform thermal zone and cooling device measurement,
registry management, and normalized storage.

Public API:
    ThermalRoleMap        — zone_type -> canonical_role mapping
    CoolingRoleMap        — device_type -> canonical_role mapping
    ThermalDiscovery      — sysfs discovery + DB registry management
    ThermalReaderV2       — reads all active zones at 1Hz (ABC-backed)
    CoolingReader         — reads all cooling device states at 1Hz (ABC-backed)
    ThermalWriterV2       — writes thermal_samples_v2 rows (EEI compliant)
    CoolingWriter         — writes cooling_samples rows (EEI compliant)
"""
