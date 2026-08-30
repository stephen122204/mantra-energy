"""
Thermal repository – Handles thermal sample storage.
"""

import json
from typing import Any, Dict, List
import logging as _logging
import socket as _socket
import time as _time
from pathlib import Path as _Path
 
logger = _logging.getLogger(__name__)

class ThermalRepository:
    """Repository for thermal samples."""

    def __init__(self, db):
        self.db = db
        self._zone_cache = {}   # (machine_id, zone_type) -> list of zone_ids

    def _get_zone_ids(self, machine_id, zone_type):
        # type: (str, str) -> list
        """
        Look up zone_ids for (machine_id, zone_type). Cached per session.
        Multiple zones may share a type (e.g. 7 acpitz zones on GN100).
        Returns list of zone_ids ordered by zone_index.
        """
        key = (machine_id, zone_type)
        if key not in self._zone_cache:
            rows = self.db.conn.execute(
                """SELECT zone_id FROM thermal_zones
                   WHERE machine_id = ? AND zone_type = ? AND active = 1
                   ORDER BY zone_index""",
                (machine_id, zone_type)
            ).fetchall()
            self._zone_cache[key] = [r[0] for r in rows]
        return self._zone_cache[key]

    def insert_thermal_samples_v2(self, run_id, thermal_samples, machine_id):
        # type: (int, list, str) -> None
        """
        Write per-zone rows to thermal_samples_v2 from legacy thermal_samples dicts.

        Reads all_zones dict from each sample and writes one row per zone.
        zone_id looked up from thermal_zones registry by (machine_id, zone_type).
        Zones not in registry are skipped with a warning.

        Args:
            run_id:          FK to runs table.
            thermal_samples: List of thermal sample dicts (from harness).
                            Each must have 'all_zones' dict and 'timestamp_ns'.
            machine_id:      From socket.gethostname().lower().
        """
        if not thermal_samples:
            return

        import time as _time
        TEMP_VALID_MIN = -10.0
        TEMP_VALID_MAX = 125.0
        rows = []

        for sample in thermal_samples:
            all_zones = sample.get("all_zones") or {}
            if isinstance(all_zones, str):
                import json as _json
                try:
                    all_zones = _json.loads(all_zones)
                except Exception:
                    continue

            timestamp_ns = sample.get("timestamp_ns") or int(_time.time_ns())

            for zone_type, temp in all_zones.items():
                # Skip derived keys added by read_all_thermal()
                if zone_type in ("cpu_temp", "package_celsius"):
                    continue

                zone_ids = self._get_zone_ids(machine_id, zone_type)
                if not zone_ids:
                    continue

                # Write one row per zone_id matching this zone_type
                for zone_id in zone_ids:
                    if temp is None:
                        quality_flag = "MISSING"
                        invalid_reason = "NULL_FROM_READER"
                        temp_val = 0.0
                    elif temp < TEMP_VALID_MIN or temp > TEMP_VALID_MAX:
                        quality_flag = "OUT_OF_RANGE"
                        invalid_reason = f"TEMP={temp:.1f}C"
                        temp_val = temp
                    else:
                        quality_flag = "VALID"
                        invalid_reason = None
                        temp_val = temp

                    rows.append((
                        run_id, zone_id, timestamp_ns, temp_val,
                        quality_flag, invalid_reason, None,
                    ))

        if rows:
            self.db.execute_many(
                """INSERT INTO thermal_samples_v2
                   (run_id, zone_id, timestamp_ns, temp_celsius,
                    quality_flag, invalid_reason, global_run_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )

    def insert_thermal_samples(
            self, run_id: int, thermal_samples: List[Dict[str, Any]]
        ) -> None:
            """
            Bulk insert thermal samples for a run.

            Chunk 2: adds sample_start_ns, sample_end_ns, interval_ns.
            all_zones serialised to JSON at insert time.
            cpu_temp reads from both 'cpu_temp' key and all_zones fallback.
            """
            if not thermal_samples:
                return

            rows = []
            for sample in thermal_samples:
                # all_zones may be dict or already JSON string
                all_zones = sample.get("all_zones") or sample.get("all_zones_json") or {}
                if isinstance(all_zones, str):
                    import json as _json
                    all_zones_dict = _json.loads(all_zones)
                else:
                    all_zones_dict = all_zones

                # cpu_temp: prefer direct key, fallback to all_zones
                cpu_temp    = sample.get("cpu_temp")    or all_zones_dict.get("cpu_package")
                system_temp = sample.get("system_temp") or all_zones_dict.get("system")
                wifi_temp   = sample.get("wifi_temp")   or all_zones_dict.get("wifi")

                rows.append((
                    run_id,
                    sample.get("timestamp_ns"),          # backward compat = end time
                    sample.get("sample_start_ns"),        # explicit start
                    sample.get("sample_end_ns"),          # explicit end
                    sample.get("interval_ns"),            # duration
                    sample.get("sample_time_s", 0),
                    cpu_temp,
                    system_temp,
                    wifi_temp,
                    sample.get("throttle_event", 0),
                    json.dumps(all_zones_dict) if all_zones_dict else None,
                    len(all_zones_dict),
                ))

            self.db.execute_many(
                """
                INSERT INTO thermal_samples (
                    run_id, timestamp_ns,
                    sample_start_ns, sample_end_ns, interval_ns,
                    sample_time_s,
                    cpu_temp, system_temp, wifi_temp,
                    throttle_event, all_zones_json, sensor_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

 
 
class CoolingRepository:
    """
    Repository for cooling device cur_state snapshots.
 
    Implements Option A from SPEC_16D2a: one snapshot per device at experiment
    end. Cooling device state changes on seconds-to-minutes timescales; a single
    end-of-run read captures throttle state accurately enough for paper-level
    analysis. Per-tick 1Hz sampling (Option B) is deferred to a future chunk.
 
    Schema: cooling_samples (v68 migration, already applied on all platforms).
    """
 
    def __init__(self, db):
        """
        Args:
            db: SQLiteAdapter instance — passed by DatabaseManager.
        """
        self.db = db
        # Cache (machine_id, device_type) → list of device_ids to avoid repeated
        # SELECT on the same DB connection during a single experiment save.
        self._device_cache = {}
 
    def _get_device_rows(self, machine_id):
        # type: (str) -> list
        """
        Fetch all active cooling devices for machine_id from cooling_devices table.
 
        Returns list of (device_id, device_type, device_index, max_state) tuples
        ordered by device_index for deterministic insertion order.
        """
        try:
            rows = self.db.conn.execute(
                """SELECT device_id, device_type, device_index, max_state
                   FROM cooling_devices
                   WHERE machine_id = ? AND active = 1
                   ORDER BY device_index""",
                (machine_id,)
            ).fetchall()
            return rows
        except Exception as exc:
            logger.warning(
                "CoolingRepository._get_device_rows: failed for machine=%s: %s",
                machine_id, exc
            )
            return []
 
    def snapshot_cooling_state(self, run_id, machine_id):
        # type: (int, str) -> int
        """
        Read current cooling device cur_state from sysfs and write to cooling_samples.
 
        Called once at experiment save time (end-of-run snapshot).
        Reads /sys/class/thermal/cooling_deviceN/cur_state live from sysfs.
        Not a measurement taken during the experiment — represents post-run
        thermal state. Adequate for throttle detection at paper resolution.
 
        Args:
            run_id:     FK to runs.id — must be valid before calling.
            machine_id: From socket.gethostname().lower().
 
        Returns:
            Number of rows written to cooling_samples.
        """
        now_ns = _time.time_ns()
        device_rows = self._get_device_rows(machine_id)
 
        if not device_rows:
            # No registered cooling devices for this machine — not an error on
            # macOS or Oracle Ampere where cooling discovery may not have run.
            logger.debug(
                "CoolingRepository: no active cooling_devices for machine=%s", machine_id
            )
            return 0
 
        rows = []
        for device_id, device_type, device_index, max_state in device_rows:
            # Reconstruct sysfs path from device_index stored at discovery time.
            # device_index is the N in /sys/class/thermal/cooling_deviceN/.
            state_path = _Path(
                "/sys/class/thermal/cooling_device{}/cur_state".format(device_index)
            )
 
            try:
                cur_state = int(state_path.read_text().strip())
                # Negative cur_state is an out-of-range kernel enum value.
                # Observed on GN100 cooling_device26 (NEGATIVE_STATE=-231).
                # Record with quality flag rather than discarding — the anomaly
                # is scientifically interesting for degradation research.
                if cur_state < 0:
                    quality_flag = "OUT_OF_RANGE"
                    invalid_reason = "NEGATIVE_STATE={}".format(cur_state)
                else:
                    quality_flag = "VALID"
                    invalid_reason = None
            except Exception as exc:
                # sysfs read failure — path may not exist if driver unloaded.
                cur_state = 0
                quality_flag = "READ_FAILED"
                invalid_reason = str(exc)[:200]
                logger.warning(
                    "CoolingRepository: sysfs read failed device_index=%d: %s",
                    device_index, exc
                )
 
            rows.append((
                run_id,
                device_id,
                now_ns,
                cur_state,
                quality_flag,
                invalid_reason,
                None,  # global_run_id — populated by federation layer if present
            ))
 
        if rows:
            try:
                self.db.execute_many(
                    """INSERT INTO cooling_samples
                       (run_id, device_id, timestamp_ns, cur_state,
                        quality_flag, invalid_reason, global_run_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
            except Exception as exc:
                logger.warning(
                    "CoolingRepository: execute_many failed run_id=%d: %s",
                    run_id, exc
                )
                return 0
 
        return len(rows)
 
 
class CPUIdleRepository:
    """
    Repository for cpu_idle_states — cross-platform normalized idle state residency.
 
    Design: normalized table with platform-native state names (C2, LPI-0 etc.)
    and depth_rank for cross-platform comparison without claiming equivalence.
    See SPEC_CPU_IDLE_STATES.md §2 for full rationale (Option C decision).
 
    Schema: cpu_idle_states (v70 migration).
 
    Platform support:
      intel_x86_64   — turbostat delta residency via write_from_turbostat()
      amd_x86_64     — cpuidle sysfs cumulative via write_from_cpuidle_sysfs()
                       (turbostat crashes on Zen 2, SIGABRT in rapl_perf_init)
      grace_aarch64  — cpuidle sysfs cumulative via write_from_cpuidle_sysfs()
      ampere_aarch64 — cpuidle sysfs cumulative via write_from_cpuidle_sysfs()
      apple_arm64    — IOKit (future, not yet implemented)
    """
 
    # ARM cpuidle sysfs base path — stable across Linux kernel versions
    _CPUIDLE_BASE = _Path("/sys/devices/system/cpu/cpu0/cpuidle")
 
    # Map Grace ARM LPI state directory names to (state_name, depth_rank).
    # depth_rank: 0=shallowest (WFI equivalent), higher=deeper.
    # Source: ARM Cortex-X925/A725 cpuidle driver state ordering.
    _ARM_STATE_MAP = {
        "state0": ("LPI-0", 0),
        "state1": ("LPI-1", 1),
        "state2": ("LPI-2", 2),
        "state3": ("LPI-3", 3),
    }
 
    # x86 Intel/AMD C-state depth ranking (shallower to deeper).
    # C2 is the first package state on modern Intel (C1 is core-only).
    _X86_DEPTH_MAP = {
        "C1":  0,
        "C1E": 1,
        "C2":  2,
        "C3":  3,
        "C6":  4,
        "C7":  5,
        "C8":  6,
        "C9":  7,
        "C10": 8,
    }
 
    def __init__(self, db):
        """
        Args:
            db: SQLiteAdapter instance — passed by DatabaseManager.
        """
        self.db = db
 
    def write_from_cpuidle_sysfs(self, run_id, platform="grace_aarch64"):
        # type: (int, str) -> int
        """
        Read ARM cpuidle sysfs residency and write to cpu_idle_states.
 
        ARM cpuidle reports cumulative microseconds since boot per idle state.
        residency_type = 'cumulative' — ETL must NOT treat as per-interval deltas.
        To get per-run residency: read before and after experiment, compute delta.
 
        This implementation reads at experiment END only (single snapshot).
        For run-level delta, the experiment runner should call this at both
        start and end, then compute delta via the ETL. Current implementation
        writes end-of-run cumulative values — sufficient for relative comparison
        across runs on same machine.
 
        Requires: /sys/devices/system/cpu/cpu0/cpuidle/stateN/ to exist.
        Gracefully returns 0 on non-ARM platforms where path does not exist.
 
        Args:
            run_id:   FK to runs.id.
            platform: Platform string stored in cpu_idle_states.platform column.
 
        Returns:
            Number of rows written.
        """
        if not self._CPUIDLE_BASE.exists():
            # Not ARM cpuidle-capable platform (x86 uses turbostat path instead).
            logger.debug(
                "CPUIdleRepository: cpuidle sysfs not found — skipping for platform=%s",
                platform
            )
            return 0
 
        rows = []
        now_ns = _time.time_ns()
 
        # Enumerate state directories: state0, state1, state2, state3
        for state_dir in sorted(self._CPUIDLE_BASE.iterdir()):
            dir_name = state_dir.name
            if not dir_name.startswith("state"):
                continue
 
            # Read the human-readable name from the kernel (e.g. "WFI", "HALT")
            name_path = state_dir / "name"
            time_path = state_dir / "time"  # cumulative residency in microseconds
 
            try:
                raw_name = name_path.read_text().strip()
                residency_us = int(time_path.read_text().strip())
            except Exception as exc:
                logger.warning(
                    "CPUIdleRepository: failed to read %s: %s", state_dir, exc
                )
                continue
 
            # Use depth_rank from ARM_STATE_MAP; fall back to directory ordinal.
            # This ensures depth_rank is always populated even on future ARM CPUs
            # with more than 4 LPI states.
            mapped = self._ARM_STATE_MAP.get(dir_name)
            if mapped:
                state_name, depth_rank = mapped
                # Use mapped canonical name (LPI-0 etc.) for cross-platform queries.
                # raw_name (WFI/HALT) stored in state_name gives paper-grade traceability.
                # Decision: use raw_name so paper shows exact hardware state.
                state_name = raw_name  # WFI, HALT, etc — exact as kernel reports
            else:
                # Unknown state directory — use ordinal as depth proxy
                state_name = raw_name
                try:
                    depth_rank = int(dir_name.replace("state", ""))
                except ValueError:
                    depth_rank = 99  # sentinel for unknown
 
            residency_seconds = residency_us / 1_000_000.0
 
            rows.append((
                run_id,
                platform,
                state_name,
                depth_rank,
                residency_seconds,
                "cumulative",    # ARM sysfs always cumulative since boot
                "cpuidle_sysfs",
            ))
 
        if rows:
            try:
                self.db.execute_many(
                    """INSERT OR IGNORE INTO cpu_idle_states
                       (run_id, platform, state_name, depth_rank,
                        residency_seconds, residency_type, measurement_source)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
            except Exception as exc:
                logger.warning(
                    "CPUIdleRepository: execute_many failed run_id=%d: %s",
                    run_id, exc
                )
                return 0
 
        return len(rows)
 
    def write_from_turbostat(self, run_id, cpu_samples, platform="intel_x86_64"):
        # type: (int, list, str) -> int
        """
        Derive idle state residency from turbostat cpu_samples and write to cpu_idle_states.
 
        turbostat reports per-interval delta C-state residency as fractions (0.0-1.0)
        in cpu_samples. This method aggregates across all samples for the run and
        writes one row per C-state to cpu_idle_states.
 
        residency_type = 'delta' because turbostat gives per-interval readings,
        not cumulative-since-boot values. ETL sums across rows for total run residency.

        Args:
            run_id:      FK to runs.run_id.
            cpu_samples: List of dicts from turbostat — keys like 'c2_residency', 'c6_residency'.
            platform:    Platform string for cpu_idle_states.platform.

        Returns:
            Number of rows written.
        """
        if not cpu_samples:
            logger.debug(
                "CPUIdleRepository.write_from_turbostat: empty cpu_samples run_id=%d",
                run_id
            )
            return 0

        # turbostat column name → (state_name, depth_rank)
        # Confirmed against live cpu_samples schema on UBUNTU2505 (2026-06-20):
        # columns are c1_residency, c2_residency, c3_residency, c6_residency,
        # c7_residency — fractions 0.0-1.0. No c1e/c8/c9/c10 columns exist.
        turbostat_col_map = {
            "c1_residency": ("C1", 0),
            "c2_residency": ("C2", 1),
            "c3_residency": ("C3", 2),
            "c6_residency": ("C6", 3),
            "c7_residency": ("C7", 4),
        }
 
        # Aggregate: sum fractional residency across all turbostat samples.
        # Divide by sample count to get mean per-interval residency fraction,
        # then multiply by total duration for approximate residency_seconds.
        # This is an approximation — turbostat sample intervals vary slightly.
        # For paper-level accuracy the ETL can recompute from raw cpu_samples.
        state_totals = {}
        for sample in cpu_samples:
            for col, (state_name, depth_rank) in turbostat_col_map.items():
                val = sample.get(col)
                if val is None:
                    continue
                if state_name not in state_totals:
                    state_totals[state_name] = {"sum": 0.0, "count": 0, "depth_rank": depth_rank}
                state_totals[state_name]["sum"] += float(val)
                state_totals[state_name]["count"] += 1
 
        if not state_totals:
            logger.debug(
                "CPUIdleRepository: no C-state columns in cpu_samples run_id=%d", run_id
            )
            return 0
 
        rows = []
        for state_name, agg in state_totals.items():
            # Store mean fraction as residency_seconds with type='percentage'
            # so ETL knows this is a fraction (0-1 scale), not elapsed seconds.
            mean_fraction = agg["sum"] / agg["count"] if agg["count"] > 0 else 0.0
            rows.append((
                run_id,
                platform,
                state_name,
                agg["depth_rank"],
                mean_fraction,
                "percentage",    # turbostat fraction, not absolute seconds
                "turbostat",
            ))
 
        if rows:
            try:
                self.db.execute_many(
                    """INSERT OR IGNORE INTO cpu_idle_states
                       (run_id, platform, state_name, depth_rank,
                        residency_seconds, residency_type, measurement_source)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
            except Exception as exc:
                logger.warning(
                    "CPUIdleRepository: turbostat execute_many failed run_id=%d: %s",
                    run_id, exc
                )
                return 0
 
        return len(rows)
 