"""
ThermalReaderV2 — unified cross-platform thermal zone reader.

Reads ALL active thermal zones at 1Hz via sysfs. Returns per-zone readings
with quality validation. Never averages, collapses, or selects zones —
that is the responsibility of aggregate_run_stats via v_thermal_cpu.

Replaces:
  - SensorReader thermal path (x86, where it returned broken cpu_temp)
  - ARMThermalReader (aarch64, Chunk 16D)
for per-zone thermal sampling. SensorReader energy path unchanged.

Implements ThermalReaderV2ABC from core/readers/interfaces.py.
Factory dispatches this on all Linux platforms (x86_64 and aarch64).

cp to: core/thermal/thermal_reader_v2.py
"""

import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

from core.readers.interfaces import ThermalReaderV2ABC

logger = logging.getLogger(__name__)

# Validity range — readings outside this range stored as OUT_OF_RANGE
TEMP_VALID_MIN = -10.0
TEMP_VALID_MAX = 125.0


class ThermalReaderV2(ThermalReaderV2ABC):
    """
    Reads all registered thermal zones via /sys/class/thermal/ sysfs.

    Initialized with registered_zones dict from thermal_discovery.
    Each zone dict must contain: zone_id (int), live_path (str), zone_type (str).

    Quality flag values:
        VALID        — temp within [-10, 125] Celsius
        OUT_OF_RANGE — temp outside validity range (stored for audit)
        READ_FAILED  — sysfs read raised exception
        MISSING      — zone was registered but temp file not found at init
    """

    def __init__(self, registered_zones: Dict[int, Dict]):
        """
        Args:
            registered_zones: Dict mapping zone_id (int) -> zone metadata dict.
                              Must include 'live_path' (sysfs dir) and 'zone_id'.
        """
        self._zones = registered_zones
        # Pre-open Path objects for performance — avoids repeated string ops
        self._temp_files: Dict[int, Path] = {}
        for zid, z in self._zones.items():
            temp_path = Path(z["live_path"]) / "temp"
            if temp_path.exists():
                self._temp_files[zid] = temp_path
            else:
                logger.warning(
                    "ThermalReaderV2: zone_id=%d (%s) temp file not found at %s",
                    zid, z.get("zone_type", "?"), temp_path
                )

    # ── ThermalReaderV2ABC interface ──────────────────────────────────────────

    def get_name(self) -> str:
        """Reader identifier for logging and provenance."""
        return "ThermalReaderV2"

    def is_available(self) -> bool:
        """Return True if at least one zone has a readable temp file."""
        return len(self._temp_files) > 0

    def initialize(self) -> None:
        """
        No-op initialize — zones discovered at __init__ time.
        Called by EnergyEngine after construction for interface compatibility.
        """
        logger.debug("ThermalReaderV2.initialize(): %d zones ready", len(self._zones))

    def read_all_zones(self) -> List[Dict]:
        """
        Read temperature from every registered zone at one instant.

        Returns list of dicts (one per zone):
            zone_id:        int   — FK to thermal_zones table
            timestamp_ns:   int   — epoch nanoseconds at read time
            temp_celsius:   float — raw temperature (may be invalid)
            quality_flag:   str   — VALID | OUT_OF_RANGE | READ_FAILED | MISSING
            invalid_reason: str|None — human-readable cause for non-VALID

        All zones are read and returned. Never discards any zone.
        Caller (ThermalWriterV2) stores all readings including invalid ones.
        """
        now_ns = time.time_ns()
        readings = []

        for zid, z in self._zones.items():

            # MISSING: zone was registered but temp file absent at init
            if zid not in self._temp_files:
                readings.append({
                    "zone_id":        zid,
                    "timestamp_ns":   now_ns,
                    "temp_celsius":   0.0,
                    "quality_flag":   "MISSING",
                    "invalid_reason": "TEMP_FILE_NOT_FOUND",
                })
                continue

            try:
                raw = self._temp_files[zid].read_text().strip()
                millideg = int(raw)
                temp_c = millideg / 1000.0

                # Range validation
                if temp_c < TEMP_VALID_MIN or temp_c > TEMP_VALID_MAX:
                    readings.append({
                        "zone_id":        zid,
                        "timestamp_ns":   now_ns,
                        "temp_celsius":   temp_c,
                        "quality_flag":   "OUT_OF_RANGE",
                        "invalid_reason": f"TEMP={temp_c:.1f}C_RANGE=[{TEMP_VALID_MIN},{TEMP_VALID_MAX}]",
                    })
                else:
                    readings.append({
                        "zone_id":        zid,
                        "timestamp_ns":   now_ns,
                        "temp_celsius":   temp_c,
                        "quality_flag":   "VALID",
                        "invalid_reason": None,
                    })

            except Exception as exc:
                readings.append({
                    "zone_id":        zid,
                    "timestamp_ns":   now_ns,
                    "temp_celsius":   0.0,
                    "quality_flag":   "READ_FAILED",
                    "invalid_reason": str(exc)[:200],
                })

        return readings

    # ── Legacy interface compatibility ────────────────────────────────────────
    # These methods exist so ThermalReaderV2 can also serve as a drop-in
    # for the old self.sensor in energy_engine.py during transition.

    def read_all_thermal(self) -> Dict[str, Optional[float]]:
        """
        Legacy interface: returns zone readings as {zone_type: celsius}.

        Used by the existing thermal sampling loop in energy_engine.py
        which puts readings into the queue for old thermal_samples inserts.
        During the transition period both old and new paths run in parallel.

        Returns VALID readings only. Invalid readings return None.
        """
        readings = self.read_all_zones()
        result: Dict[str, Optional[float]] = {}

        for r in readings:
            zid = r["zone_id"]
            zone_type = self._zones[zid].get("zone_type", f"zone_{zid}")
            if r["quality_flag"] == "VALID":
                result[zone_type] = r["temp_celsius"]
            else:
                result[zone_type] = None

        # Add standard keys consumed by legacy harness thermal pipeline
        cpu_temps = [
            r["temp_celsius"] for r in readings
            if r["quality_flag"] == "VALID"
            and self._zones[r["zone_id"]].get("canonical_role")
            in ("CPU_PACKAGE", "SOC")
        ]
        if cpu_temps:
            cpu_avg = sum(cpu_temps) / len(cpu_temps)
            result["cpu_temp"] = cpu_avg
            result["package_celsius"] = cpu_avg
        else:
            result["cpu_temp"] = None
            result["package_celsius"] = None

        return result

    def read_temperatures(self) -> Dict:
        """
        Legacy ThermalReaderABC interface — returns ThermalReadings-compatible dict.
        Consumed by energy_engine.py line 735 and line 975.
        """
        all_thermal = self.read_all_thermal()
        cpu_temp = all_thermal.get("cpu_temp")
        return {
            "package_celsius":  cpu_temp if cpu_temp is not None else 0.0,
            "core_temps":       [],
            "gpu_celsius":      0.0,    # GPU temp from DCGM, not sysfs
            "pch_celsius":      0.0,
            "throttle_events":  0,
            "prochot_events":   0,
            "is_throttling":    False,
        }

    # SensorReader compatibility attributes (used by energy_engine.py lines 308, 1426)
    @property
    def available_sensors(self) -> Dict:
        """Mirror SensorReader.available_sensors — maps zone_type to path."""
        return {
            self._zones[zid].get("zone_type", f"zone_{zid}"): str(p)
            for zid, p in self._temp_files.items()
        }

    @property
    def throttle_thresholds(self) -> Dict:
        """Mirror SensorReader.throttle_thresholds — empty dict = no threshold checks."""
        return {}
