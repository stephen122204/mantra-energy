"""
THERMAL_ROLE_MAP — compile-time registry mapping kernel zone_type strings
to canonical thermal roles. Analogous to BASELINE_DOMAIN_MAP for energy.

Adding a new platform = adding entries here. Zero reader code changes needed.

Canonical roles:
    CPU_PACKAGE     — direct CPU package temperature sensor (Intel x86_pkg_temp, AMD k10temp)
    SOC             — SoC-level zone (ARM Grace acpitz, Tegra zones)
    CPU_DIE         — CPU die sensor (may be unreliable, e.g. TCPU = -273.15 on Lenovo)
    GPU             — GPU temperature
    DPTF_AGGREGATE  — Intel DPTF platform aggregate (unreliable, role=OTHER for analysis)
    DPTF_SENSOR     — Intel DPTF individual sensor (SEN1/SEN2/SEN3/SEN4)
    WIFI            — WiFi module temperature
    PCH             — Platform Controller Hub
    AMBIENT         — Ambient / board temperature
    BOARD           — Board temperature (Tegra)
    DIODE           — Thermal diode (Tegra)
    STORAGE         — NVMe / storage device
    OTHER           — Unknown zone type (still sampled, never discarded)

cp to: core/thermal/thermal_role_map.py
"""

from typing import Dict


# Maps kernel zone_type string -> canonical_role.
# When zone_type alone is ambiguous (e.g. acpitz on GN100 where all 7 zones
# share the same type), the identity tuple (zone_type, zone_index) differentiates
# individual zones in the registry, but they all receive the same canonical_role.
THERMAL_ROLE_MAP: Dict[str, str] = {

    # ── Intel (UBUNTU2505 Lenovo IdeaPad) ─────────────────────────────────────
    "x86_pkg_temp":     "CPU_PACKAGE",   # reliable: Intel package temp
    "INT3400 Thermal":  "DPTF_AGGREGATE",# unreliable: DPTF platform aggregate
    "SEN1":             "DPTF_SENSOR",   # DPTF sensor (board-level)
    "SEN2":             "DPTF_SENSOR",
    "SEN3":             "DPTF_SENSOR",
    "SEN4":             "DPTF_SENSOR",
    "TCPU":             "CPU_DIE",       # BROKEN on Lenovo: reports -273.15
    "pch_skylake":      "PCH",
    "pch_cannonlake":   "PCH",
    "pch_tigerlake":    "PCH",
    "B0D4":             "DPTF_SENSOR",
    "TSKN":             "DPTF_SENSOR",
    "TAMB":             "AMBIENT",

    # ── AMD (Alex machine) ─────────────────────────────────────────────────────
    "k10temp":          "CPU_PACKAGE",   # AMD Ryzen CPU package
    "zenpower":         "CPU_PACKAGE",   # alternative AMD driver
    "amdgpu":           "GPU",           # AMD GPU
    "nct6775":          "AMBIENT",       # Nuvoton SuperIO chip (board)
    "it8792":           "AMBIENT",       # ITE SuperIO chip (board)

    # ── NVIDIA Grace GN100 / GB10 family (aarch64) ────────────────────────────
    "acpitz":           "SOC",           # GN100: all 7 zones are acpitz/SOC
    "CPU-therm":        "CPU_PACKAGE",
    "GPU-therm":        "GPU",
    "thermal-fan-est":  "AMBIENT",
    "Tboard_tegra":     "BOARD",
    "Tdiode_tegra":     "DIODE",
    "Tsoc_tegra":       "SOC",
    "Tcpu_tegra":       "CPU_PACKAGE",
    "Tgpu_tegra":       "GPU",

    # ── Apple Silicon (Stephen M1 Pro) ─────────────────────────────────────────
    # Apple does not expose /sys/class/thermal — discovery returns empty list.
    # IOKit path handled by separate IOKitThermalReader (future chunk 16-F).
    # No entries needed here — role assignment happens in IOKit reader directly.

    # ── Storage (cross-platform) ───────────────────────────────────────────────
    "nvme":             "STORAGE",
    "drivetemp":        "STORAGE",

    # ── WiFi (cross-platform) ──────────────────────────────────────────────────
    "iwlwifi_1":        "WIFI",
    "iwlwifi_2":        "WIFI",
    "ath10k_hwmon":     "WIFI",
}


def resolve_thermal_role(zone_type: str) -> str:
    """
    Map a kernel zone_type string to a canonical thermal role.

    Unknown zone types return 'OTHER' — they are still sampled and stored
    in thermal_samples_v2 with quality_flag=VALID. Never silently discarded.

    Args:
        zone_type: Kernel thermal zone type string from /sys/class/thermal/
                   thermal_zoneN/type file.

    Returns:
        Canonical role string. One of: CPU_PACKAGE, SOC, CPU_DIE, GPU,
        DPTF_AGGREGATE, DPTF_SENSOR, WIFI, PCH, AMBIENT, BOARD, DIODE,
        STORAGE, OTHER.
    """
    return THERMAL_ROLE_MAP.get(zone_type, "OTHER")


# Roles considered valid CPU temperature sources (in priority order).
# aggregate_run_stats uses this to select the right zones for package_temp_celsius.
CPU_THERMAL_ROLES_PRIORITY = ("CPU_PACKAGE", "SOC", "CPU_DIE")

# Roles excluded from paper-reported temperatures (unreliable or non-CPU).
EXCLUDED_FROM_ANALYSIS = {"DPTF_AGGREGATE", "DPTF_SENSOR", "WIFI", "AMBIENT",
                           "BOARD", "DIODE", "OTHER"}
