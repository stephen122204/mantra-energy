"""
Thermal repository – Handles thermal sample storage.
"""

import json
from typing import Any, Dict, List


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
