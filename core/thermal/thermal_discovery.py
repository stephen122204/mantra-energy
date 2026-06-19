"""
Thermal zone and cooling device discovery for A-LEMS.

Scans /sys/class/thermal/ at reader init time. Populates thermal_zones
and cooling_devices registry tables via upsert. Called from:

  1. scripts/detect_hardware.py  — machine setup time (first run only)
  2. ExperimentHarness.__init__  — every experiment session (reboot-resilient)

Key design decisions:
  - Live sysfs paths are in-memory only. NEVER stored in DB.
  - Identity = (machine_id, zone_type, zone_index) — stable across reboots
    even when kernel renumbers /sys/class/thermal/thermal_zoneN paths.
  - Zones not found at re-discovery are marked active=0, not deleted.
  - DB connection passed in — discovery itself has no DB dependency (testable).

cp to: core/thermal/thermal_discovery.py
"""

import logging
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.thermal.thermal_role_map import resolve_thermal_role
from core.thermal.cooling_role_map import resolve_cooling_role

logger = logging.getLogger(__name__)

# Temperature validity range (Celsius).
# Outside this range → quality_flag='OUT_OF_RANGE', still stored for audit.
TEMP_VALID_MIN = -10.0
TEMP_VALID_MAX = 125.0


def get_machine_id() -> str:
    """
    Return stable machine identifier. Uses socket.gethostname() — same
    source as line 1158 in energy_engine.py (platform.node() is identical).

    Returns:
        Lowercase hostname string, e.g. 'gn100-2b96', 'ubuntu2505'.
    """
    return socket.gethostname().lower()


# ─────────────────────────────────────────────────────────────────────────────
# Zone discovery
# ─────────────────────────────────────────────────────────────────────────────

def discover_thermal_zones(machine_id: Optional[str] = None) -> List[Dict]:
    """
    Scan /sys/class/thermal/thermal_zone* and return zone metadata dicts.

    Each dict contains:
        machine_id:       str  — from get_machine_id()
        zone_type:        str  — kernel type string from /type file
        zone_index:       int  — integer from path (thermal_zone3 -> 3)
        canonical_role:   str  — from THERMAL_ROLE_MAP
        source_subsystem: str  — always 'thermal_zone' for sysfs
        live_path:        str  — current sysfs dir path (in-memory only)
        driver:           str  — kernel driver name if discoverable
        device:           str  — device descriptor if available

    live_path is NEVER stored in DB (changes after reboot).

    Args:
        machine_id: Override for testing. Defaults to get_machine_id().

    Returns:
        List of zone metadata dicts, sorted by zone_index.
    """
    machine_id = machine_id or get_machine_id()
    thermal_base = Path("/sys/class/thermal")
    zones = []

    if not thermal_base.exists():
        logger.warning("discover_thermal_zones: /sys/class/thermal not found — "
                       "thermal subsystem unavailable on this platform")
        return zones

    for zone_dir in sorted(thermal_base.glob("thermal_zone*")):
        try:
            zone_name = zone_dir.name   # e.g. "thermal_zone3"
            zone_index = int(zone_name.replace("thermal_zone", ""))

            type_file = zone_dir / "type"
            if not type_file.exists():
                logger.debug("discover_thermal_zones: no type file in %s, skipping", zone_dir)
                continue
            zone_type = type_file.read_text().strip()

            # Verify temp file is readable — skip unreadable zones
            temp_file = zone_dir / "temp"
            if not temp_file.exists():
                logger.debug("discover_thermal_zones: no temp file in %s, skipping", zone_dir)
                continue

            # Attempt to read driver name (best effort)
            driver = None
            try:
                driver_link = zone_dir / "device" / "driver"
                if driver_link.exists():
                    driver = Path(driver_link.resolve()).name
            except Exception:
                pass

            # Attempt to read device descriptor (best effort)
            device = None
            try:
                name_file = zone_dir / "device" / "name"
                if name_file.exists():
                    device = name_file.read_text().strip()
            except Exception:
                pass

            zones.append({
                "machine_id":       machine_id,
                "zone_type":        zone_type,
                "zone_index":       zone_index,
                "canonical_role":   resolve_thermal_role(zone_type),
                "source_subsystem": "thermal_zone",
                "live_path":        str(zone_dir),
                "driver":           driver,
                "device":           device,
            })

        except Exception as exc:
            logger.error("discover_thermal_zones: failed on %s: %s", zone_dir, exc)

    logger.info("discover_thermal_zones: found %d zones on %s", len(zones), machine_id)
    return zones


def discover_cooling_devices(machine_id: Optional[str] = None) -> List[Dict]:
    """
    Scan /sys/class/thermal/cooling_device* and return device metadata dicts.

    Each dict contains:
        machine_id:       str  — from get_machine_id()
        device_type:      str  — kernel type string from /type file
        device_index:     int  — integer from path (cooling_device3 -> 3)
        canonical_role:   str  — from COOLING_ROLE_MAP
        source_subsystem: str  — always 'thermal_zone'
        max_state:        int  — maximum throttle level
        live_path:        str  — current sysfs dir path (in-memory only)
        driver:           str  — driver name if available
        device:           str  — device descriptor if available

    Note: GN100 cooling_device26 has cur_state=-231 (kernel bug).
    This device is discovered and registered normally. The invalid reading
    is caught at sample time and stored as OUT_OF_RANGE.

    Args:
        machine_id: Override for testing. Defaults to get_machine_id().

    Returns:
        List of device metadata dicts, sorted by device_index.
    """
    machine_id = machine_id or get_machine_id()
    thermal_base = Path("/sys/class/thermal")
    devices = []

    if not thermal_base.exists():
        return devices

    for dev_dir in sorted(thermal_base.glob("cooling_device*")):
        try:
            dev_name = dev_dir.name   # e.g. "cooling_device3"
            dev_index = int(dev_name.replace("cooling_device", ""))

            type_file = dev_dir / "type"
            if not type_file.exists():
                continue
            dev_type = type_file.read_text().strip()

            max_state_file = dev_dir / "max_state"
            if not max_state_file.exists():
                continue
            try:
                max_state = int(max_state_file.read_text().strip())
            except ValueError:
                max_state = 0

            driver = None
            try:
                driver_link = dev_dir / "device" / "driver"
                if driver_link.exists():
                    driver = Path(driver_link.resolve()).name
            except Exception:
                pass

            devices.append({
                "machine_id":       machine_id,
                "device_type":      dev_type,
                "device_index":     dev_index,
                "canonical_role":   resolve_cooling_role(dev_type),
                "source_subsystem": "thermal_zone",
                "max_state":        max_state,
                "live_path":        str(dev_dir),
                "driver":           driver,
                "device":           None,
            })

        except Exception as exc:
            logger.error("discover_cooling_devices: failed on %s: %s", dev_dir, exc)

    logger.info("discover_cooling_devices: found %d devices on %s",
                len(devices), machine_id)
    return devices


# ─────────────────────────────────────────────────────────────────────────────
# DB registration
# ─────────────────────────────────────────────────────────────────────────────

def register_thermal_zones(db_conn, zones: List[Dict]) -> Dict[int, Dict]:
    """
    Upsert discovered zones into thermal_zones table.

    For each zone:
      - If (machine_id, zone_type, zone_index) already exists:
          update last_seen=now, active=1, refresh driver/device/canonical_role
      - If new: insert with first_seen=last_seen=now
      - Zones from this machine NOT in current discovery: set active=0

    Args:
        db_conn:  Raw sqlite3 connection (from DatabaseManager.db.conn or
                  short-lived connection in detect_hardware).
        zones:    List of dicts from discover_thermal_zones().

    Returns:
        Dict mapping zone_id (int) -> zone dict with 'zone_id' and 'live_path'
        added. This is the registered_zones dict consumed by ThermalReaderV2.
    """
    now = datetime.now(timezone.utc).isoformat()
    machine_id = zones[0]["machine_id"] if zones else None
    registered: Dict[int, Dict] = {}

    for zone in zones:
        row = db_conn.execute(
            """SELECT zone_id FROM thermal_zones
               WHERE machine_id = ? AND zone_type = ? AND zone_index = ?""",
            (zone["machine_id"], zone["zone_type"], zone["zone_index"])
        ).fetchone()

        if row:
            zone_id = row[0]
            db_conn.execute(
                """UPDATE thermal_zones
                   SET last_seen = ?, active = 1,
                       driver = COALESCE(?, driver),
                       device = COALESCE(?, device),
                       canonical_role = ?
                   WHERE zone_id = ?""",
                (now, zone["driver"], zone["device"],
                 zone["canonical_role"], zone_id)
            )
        else:
            cursor = db_conn.execute(
                """INSERT INTO thermal_zones
                   (machine_id, zone_type, zone_index, driver, device,
                    canonical_role, source_subsystem, first_seen, last_seen, active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (zone["machine_id"], zone["zone_type"], zone["zone_index"],
                 zone["driver"], zone["device"], zone["canonical_role"],
                 zone["source_subsystem"], now, now)
            )
            zone_id = cursor.lastrowid

        zone_with_id = dict(zone)
        zone_with_id["zone_id"] = zone_id
        registered[zone_id] = zone_with_id

    # Mark zones for this machine that were NOT found this time as inactive
    if machine_id and registered:
        active_ids = list(registered.keys())
        placeholders = ",".join("?" * len(active_ids))
        db_conn.execute(
            f"""UPDATE thermal_zones SET active = 0
                WHERE machine_id = ? AND zone_id NOT IN ({placeholders})""",
            [machine_id] + active_ids
        )

    db_conn.commit()
    logger.info("register_thermal_zones: registered %d zones", len(registered))
    return registered


def register_cooling_devices(db_conn, devices: List[Dict]) -> Dict[int, Dict]:
    """
    Upsert discovered cooling devices into cooling_devices table.

    Same upsert logic as register_thermal_zones.

    Args:
        db_conn:  Raw sqlite3 connection.
        devices:  List of dicts from discover_cooling_devices().

    Returns:
        Dict mapping device_id (int) -> device dict with 'device_id' and
        'live_path' added. Consumed by CoolingReader.
    """
    now = datetime.now(timezone.utc).isoformat()
    machine_id = devices[0]["machine_id"] if devices else None
    registered: Dict[int, Dict] = {}

    for dev in devices:
        row = db_conn.execute(
            """SELECT device_id FROM cooling_devices
               WHERE machine_id = ? AND device_type = ? AND device_index = ?""",
            (dev["machine_id"], dev["device_type"], dev["device_index"])
        ).fetchone()

        if row:
            device_id = row[0]
            db_conn.execute(
                """UPDATE cooling_devices
                   SET last_seen = ?, active = 1, max_state = ?,
                       driver = COALESCE(?, driver),
                       canonical_role = ?
                   WHERE device_id = ?""",
                (now, dev["max_state"], dev["driver"],
                 dev["canonical_role"], device_id)
            )
        else:
            cursor = db_conn.execute(
                """INSERT INTO cooling_devices
                   (machine_id, device_type, device_index, driver, device,
                    canonical_role, source_subsystem, max_state,
                    first_seen, last_seen, active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (dev["machine_id"], dev["device_type"], dev["device_index"],
                 dev["driver"], dev["device"], dev["canonical_role"],
                 dev["source_subsystem"], dev["max_state"], now, now)
            )
            device_id = cursor.lastrowid

        dev_with_id = dict(dev)
        dev_with_id["device_id"] = device_id
        registered[device_id] = dev_with_id

    # Mark devices for this machine not found this time as inactive
    if machine_id and registered:
        active_ids = list(registered.keys())
        placeholders = ",".join("?" * len(active_ids))
        db_conn.execute(
            f"""UPDATE cooling_devices SET active = 0
                WHERE machine_id = ? AND device_id NOT IN ({placeholders})""",
            [machine_id] + active_ids
        )

    db_conn.commit()
    logger.info("register_cooling_devices: registered %d devices", len(registered))
    return registered


def validate_cpu_package(registered_zones: Dict[int, Dict]) -> int:
    """
    Verify at least one CPU thermal zone exists. Hard error if none found.

    Selection priority:
      1. CPU_PACKAGE — direct package sensor (Intel x86_pkg_temp, AMD k10temp)
      2. SOC         — SoC zones (GN100 acpitz)
      3. CPU_DIE     — die sensor (may be broken but role is correct)

    Args:
        registered_zones: Dict from register_thermal_zones().

    Returns:
        zone_id of the primary CPU thermal zone.

    Raises:
        RuntimeError: If no CPU thermal zone found. This is a hard error —
                      experiment cannot proceed without CPU thermal measurement.
    """
    from core.thermal.thermal_role_map import CPU_THERMAL_ROLES_PRIORITY

    for role in CPU_THERMAL_ROLES_PRIORITY:
        candidates = [
            (zid, z) for zid, z in registered_zones.items()
            if z["canonical_role"] == role
        ]
        if candidates:
            primary_id, primary_zone = candidates[0]
            logger.info(
                "validate_cpu_package: primary zone zone_id=%d role=%s type=%s",
                primary_id, role, primary_zone["zone_type"]
            )
            return primary_id

    raise RuntimeError(
        "HARD ERROR: No thermal zone with role CPU_PACKAGE, SOC, or CPU_DIE found. "
        "Cannot proceed without CPU thermal measurement. "
        "Check /sys/class/thermal/ and THERMAL_ROLE_MAP in core/thermal/thermal_role_map.py."
    )
