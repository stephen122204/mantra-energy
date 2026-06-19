"""
ThermalWriterV2 — writes thermal_samples_v2 rows (EEI compliant).

Called by ExperimentHarness after thermal readings collected at each 1Hz tick.
Engine never calls this directly — EEI boundary enforced.

Uses DatabaseManager's SQLiteAdapter interface (db.execute_many) matching
the pattern in core/database/repositories/thermal.py.

cp to: core/thermal/thermal_writer_v2.py
"""

import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class ThermalWriterV2:
    """
    Writes per-zone thermal readings to thermal_samples_v2 table.

    One call per 1Hz tick writes all zone readings for that tick as a batch.
    Uses executemany for efficiency.
    """

    def __init__(self, db):
        """
        Args:
            db: SQLiteAdapter instance from DatabaseManager.
                Must expose execute_many(query, rows) method.
        """
        self._db = db

    def write_samples(
        self,
        run_id: int,
        readings: List[Dict],
        global_run_id: Optional[str] = None,
    ) -> None:
        """
        Write one 1Hz tick of thermal readings to thermal_samples_v2.

        Args:
            run_id:        Current experiment run_id (FK to runs).
            readings:      List of dicts from ThermalReaderV2.read_all_zones().
                          Each dict: zone_id, timestamp_ns, temp_celsius,
                          quality_flag, invalid_reason.
            global_run_id: Cross-machine run correlation ID. NULL until populated.
        """
        if not readings:
            return

        rows = [
            (
                run_id,
                r["zone_id"],
                r["timestamp_ns"],
                r["temp_celsius"],
                r["quality_flag"],
                r.get("invalid_reason"),
                global_run_id,
            )
            for r in readings
        ]

        self._db.execute_many(
            """INSERT INTO thermal_samples_v2
               (run_id, zone_id, timestamp_ns, temp_celsius,
                quality_flag, invalid_reason, global_run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

        logger.debug(
            "ThermalWriterV2.write_samples: run_id=%d wrote %d zone readings",
            run_id, len(rows)
        )
