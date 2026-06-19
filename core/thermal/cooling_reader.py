"""
CoolingReader — reads all cooling device states at 1Hz via sysfs.

Implements CoolingReaderABC from core/readers/interfaces.py.
Reads cur_state from /sys/class/thermal/cooling_deviceN/cur_state.
Detects CPU throttle state for real-time throttle monitoring.

cp to: core/thermal/cooling_reader.py
"""

import logging
import time
from pathlib import Path
from typing import Dict, List

from core.readers.interfaces import CoolingReaderABC
from core.thermal.cooling_role_map import THROTTLE_ROLES

logger = logging.getLogger(__name__)


class CoolingReader(CoolingReaderABC):
    """
    Reads cur_state from all registered cooling devices via sysfs.

    Initialized with registered_devices dict from thermal_discovery.
    Each device dict must contain: device_id (int), live_path (str),
    device_type (str), canonical_role (str), max_state (int).

    Quality flag values:
        VALID        — cur_state within [0, max_state]
        OUT_OF_RANGE — negative cur_state (GN100 cooling_device26 bug: -231)
        READ_FAILED  — sysfs read raised exception
        MISSING      — device registered but cur_state file not found
    """

    def __init__(self, registered_devices: Dict[int, Dict]):
        """
        Args:
            registered_devices: Dict mapping device_id (int) -> device metadata.
                               Must include 'live_path', 'device_id', 'max_state'.
        """
        self._devices = registered_devices
        # Pre-build Path objects for cur_state files
        self._state_files: Dict[int, Path] = {}
        for did, d in self._devices.items():
            state_path = Path(d["live_path"]) / "cur_state"
            if state_path.exists():
                self._state_files[did] = state_path
            else:
                logger.warning(
                    "CoolingReader: device_id=%d (%s) cur_state not found at %s",
                    did, d.get("device_type", "?"), state_path
                )

    # ── CoolingReaderABC interface ────────────────────────────────────────────

    def get_name(self) -> str:
        """Reader identifier for logging."""
        return "CoolingReader"

    def is_available(self) -> bool:
        """Return True if at least one cooling device is readable."""
        return len(self._state_files) > 0

    def read_all_devices(self) -> List[Dict]:
        """
        Read cur_state from every registered cooling device.

        Returns list of dicts (one per device):
            device_id:      int   — FK to cooling_devices table
            timestamp_ns:   int   — epoch nanoseconds
            cur_state:      int   — raw kernel state value
            quality_flag:   str   — VALID | OUT_OF_RANGE | READ_FAILED | MISSING
            invalid_reason: str|None

        Note on GN100 cooling_device26: cur_state=-231 is a kernel bug.
        This device is read and stored as OUT_OF_RANGE. detect_throttle()
        ignores OUT_OF_RANGE readings so this never triggers false throttle.
        """
        now_ns = time.time_ns()
        readings = []

        for did, d in self._devices.items():

            if did not in self._state_files:
                readings.append({
                    "device_id":      did,
                    "timestamp_ns":   now_ns,
                    "cur_state":      0,
                    "quality_flag":   "MISSING",
                    "invalid_reason": "CUR_STATE_FILE_NOT_FOUND",
                })
                continue

            try:
                raw = self._state_files[did].read_text().strip()
                cur_state = int(raw)

                # Negative states are invalid (GN100 kernel bug)
                if cur_state < 0:
                    readings.append({
                        "device_id":      did,
                        "timestamp_ns":   now_ns,
                        "cur_state":      cur_state,
                        "quality_flag":   "OUT_OF_RANGE",
                        "invalid_reason": f"NEGATIVE_STATE={cur_state}",
                    })
                else:
                    readings.append({
                        "device_id":      did,
                        "timestamp_ns":   now_ns,
                        "cur_state":      cur_state,
                        "quality_flag":   "VALID",
                        "invalid_reason": None,
                    })

            except Exception as exc:
                readings.append({
                    "device_id":      did,
                    "timestamp_ns":   now_ns,
                    "cur_state":      0,
                    "quality_flag":   "READ_FAILED",
                    "invalid_reason": str(exc)[:200],
                })

        return readings

    def detect_throttle(self, readings: List[Dict]) -> bool:
        """
        Check if any throttle-role device has cur_state > 0.

        Only checks VALID readings for devices with canonical_role in
        THROTTLE_ROLES (CPU_FREQ_THROTTLE, POWER_CLAMP, TCC_OFFSET).
        OUT_OF_RANGE readings (e.g. GN100 device26) never trigger throttle.

        Args:
            readings: Output of read_all_devices() for current tick.

        Returns:
            True if any throttle device is actively throttling.
        """
        for r in readings:
            if r["quality_flag"] != "VALID":
                continue
            did = r["device_id"]
            if did not in self._devices:
                continue
            d = self._devices[did]
            if d.get("canonical_role") in THROTTLE_ROLES and r["cur_state"] > 0:
                logger.debug(
                    "CoolingReader.detect_throttle: throttle detected "
                    "device_id=%d type=%s cur_state=%d",
                    did, d.get("device_type", "?"), r["cur_state"]
                )
                return True
        return False
