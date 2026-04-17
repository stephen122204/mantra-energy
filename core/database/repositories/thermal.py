"""
Thermal repository – Handles thermal sample storage.
"""

import json
from typing import Any, Dict, List


class ThermalRepository:
    """Repository for thermal samples."""

    def __init__(self, db):
        self.db = db

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
