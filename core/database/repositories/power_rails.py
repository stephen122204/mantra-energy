"""
core/database/repositories/power_rails.py

Repository methods for power rail schema (v57-v60).
All methods PAC-2 compliant: caller wraps in try/except.

Tables written:
    power_rail_samples   — high-frequency power time series
    run_power_limits     — once-per-run firmware limit snapshot
    power_limit_events   — mid-run limit change events (rare)
"""

from __future__ import annotations

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


def insert_power_rail_samples(conn, run_id: int, samples) -> int:
    """
    Insert PowerRailSample list into power_rail_samples.
    Returns number of rows inserted.

    Args:
        conn:    sqlite3 connection
        run_id:  current run id
        samples: List[PowerRailSample] from PowerRailSampler.stop()
    """
    if not samples:
        return 0
    rows = [
        (run_id, s.timestamp_ns, s.interval_ns, s.rail_id, s.power_mw)
        for s in samples
    ]
    conn.executemany(
        """INSERT INTO power_rail_samples
           (run_id, timestamp_ns, interval_ns, rail_id, power_mw)
           VALUES (?, ?, ?, ?, ?)""",
        rows,
    )
    logger.debug("insert_power_rail_samples: %d rows for run %d", len(rows), run_id)
    return len(rows)


def insert_run_power_limits(conn, run_id: int, limits_snapshot: Dict[int, float]) -> int:
    """
    Insert power limits snapshot into run_power_limits.
    limits_snapshot: {limit_id -> value_mw}
    Returns number of rows inserted.
    """
    if not limits_snapshot:
        return 0
    rows = [(run_id, limit_id, value_mw) for limit_id, value_mw in limits_snapshot.items()]
    conn.executemany(
        """INSERT OR IGNORE INTO run_power_limits (run_id, limit_id, value_mw)
           VALUES (?, ?, ?)""",
        rows,
    )
    logger.debug("insert_run_power_limits: %d rows for run %d", len(rows), run_id)
    return len(rows)


def insert_power_limit_event(
    conn,
    run_id: int,
    timestamp_ns: int,
    limit_id: int,
    old_value_mw,
    new_value_mw: float,
) -> None:
    """
    Insert a single mid-run limit change event.
    old_value_mw may be None if limit was not previously read.
    """
    conn.execute(
        """INSERT INTO power_limit_events
           (run_id, timestamp_ns, limit_id, old_value_mw, new_value_mw)
           VALUES (?, ?, ?, ?, ?)""",
        (run_id, timestamp_ns, limit_id, old_value_mw, new_value_mw),
    )
    logger.debug(
        "insert_power_limit_event: run %d limit %d %.1f->%.1f mW",
        run_id, limit_id, old_value_mw or 0, new_value_mw,
    )
