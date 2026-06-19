"""
CoolingWriter — writes cooling_samples rows (EEI compliant).

Called by ExperimentHarness after cooling device readings at each 1Hz tick.
Engine never calls this directly — EEI boundary enforced.

cp to: core/thermal/cooling_writer.py
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class CoolingWriter:
    """
    Writes cooling device state readings to cooling_samples table.

    One call per 1Hz tick writes all device readings for that tick as a batch.
    """

    def __init__(self, db):
        """
        Args:
            db: SQLiteAdapter instance from DatabaseManager.
        """
        self._db = db

    def write_samples(
        self,
        run_id: int,
        readings: List[Dict],
        global_run_id: Optional[str] = None,
    ) -> None:
        """
        Write one 1Hz tick of cooling device readings to cooling_samples.

        Args:
            run_id:        Current experiment run_id.
            readings:      List of dicts from CoolingReader.read_all_devices().
                          Each dict: device_id, timestamp_ns, cur_state,
                          quality_flag, invalid_reason.
            global_run_id: Cross-machine run correlation ID. NULL until populated.
        """
        if not readings:
            return

        rows = [
            (
                run_id,
                r["device_id"],
                r["timestamp_ns"],
                r["cur_state"],
                r["quality_flag"],
                r.get("invalid_reason"),
                global_run_id,
            )
            for r in readings
        ]

        self._db.execute_many(
            """INSERT INTO cooling_samples
               (run_id, device_id, timestamp_ns, cur_state,
                quality_flag, invalid_reason, global_run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

        logger.debug(
            "CoolingWriter.write_samples: run_id=%d wrote %d device readings",
            run_id, len(rows)
        )
