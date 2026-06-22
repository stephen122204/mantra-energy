"""
core/network/overlap_utils.py
Shared interpolated overlap helper for network energy estimation.

All three strategies need to sum energy samples that fall within
[request_start_ns, first_token_time_ns] blocking windows.
This module centralises that logic so it is not duplicated.

Used by: rapl_slice_estimator.py, spbm_fraction_estimator.py, fallback_estimator.py
"""

import logging
from typing import List, Optional, Tuple
import sqlite3

logger = logging.getLogger(__name__)


def fetch_blocking_windows(
    db_conn: "sqlite3.Connection",
    run_id: int,
) -> List[dict]:
    """
    Load all LLM blocking windows for a run from llm_interactions.

    Only includes rows with both timestamps and non_local_ms > 0 —
    these are remote API calls where network wait energy is non-zero.

    Args:
        db_conn: Open SQLite connection.
        run_id:  Target run.

    Returns:
        List of dicts with keys: request_start_ns, first_token_time_ns, non_local_ms
        Empty list if no remote calls in this run (local inference).
    """
    cursor = db_conn.cursor()
    cursor.execute("""
        SELECT request_start_ns, first_token_time_ns, non_local_ms
        FROM llm_interactions
        WHERE run_id = ?
          AND request_start_ns IS NOT NULL
          AND first_token_time_ns IS NOT NULL
          AND non_local_ms > 0
        ORDER BY request_start_ns
    """, (run_id,))
    rows = cursor.fetchall()
    return [
        {
            "request_start_ns": r[0],
            "first_token_time_ns": r[1],
            "non_local_ms": r[2],
        }
        for r in rows
    ]


def sum_pkg_energy_in_windows(
    db_conn: "sqlite3.Connection",
    run_id: int,
    windows: List[dict],
) -> Tuple[Optional[int], int]:
    """
    Sum RAPL pkg energy samples within blocking windows.

    Uses sample_start_ns/sample_end_ns for precise window overlap.
    Does NOT multiply by cpu_fraction — that is the bug we are fixing.
    During network wait, CPU≈0 but pkg is non-zero due to NIC/PCH/uncore.

    Args:
        db_conn:  Open SQLite connection.
        run_id:   Target run.
        windows:  List of blocking window dicts.

    Returns:
        Tuple of (total_energy_uj, windows_with_data_count).
        total_energy_uj is None if no samples found in any window.
    """
    cursor = db_conn.cursor()
    total_uj = 0
    windows_with_data = 0

    for w in windows:
        start_ns = w["request_start_ns"]
        end_ns = w["first_token_time_ns"]

        if end_ns <= start_ns:
            # Malformed window — skip, do not count as coverage
            continue

        # Sum RAPL deltas within this blocking window
        # energy_samples stores cumulative counters — delta = end - start per interval
        cursor.execute("""
            SELECT COALESCE(SUM(pkg_end_uj - pkg_start_uj), 0) AS window_energy,
                   COUNT(*) AS n_samples
            FROM energy_samples
            WHERE run_id = ?
              AND sample_start_ns >= ?
              AND sample_end_ns <= ?
              AND pkg_end_uj > pkg_start_uj
        """, (run_id, start_ns, end_ns))
        row = cursor.fetchone()

        if row and row[1] > 0:
            # At least one sample fell in this window
            total_uj += int(row[0])
            windows_with_data += 1

    if total_uj == 0:
        # MIC-3: return None not zero when no data found
        return None, windows_with_data

    return total_uj, windows_with_data


def sum_domain_energy_in_windows(
    db_conn: "sqlite3.Connection",
    run_id: int,
    windows: List[dict],
    domain_id: int,
) -> Tuple[Optional[int], int]:
    """
    Sum energy from a specific SPBM domain within blocking windows.

    Used by Strategy B (GN100) to get DC_INPUT (domain_id=28) energy
    during network blocking periods.

    Args:
        db_conn:   Open SQLite connection.
        run_id:    Target run.
        windows:   List of blocking window dicts.
        domain_id: SPBM domain ID (28=DC_INPUT for GN100).

    Returns:
        Tuple of (total_energy_uj, windows_with_data_count).
        total_energy_uj is None if domain has no data in any window.
    """
    cursor = db_conn.cursor()
    total_uj = 0
    windows_with_data = 0

    for w in windows:
        start_ns = w["request_start_ns"]
        end_ns = w["first_token_time_ns"]

        if end_ns <= start_ns:
            continue

        # SPBM samples via energy_sample_domains joined to energy_samples_v2
        # energy_uj is the per-interval domain energy (not cumulative)
        cursor.execute("""
            SELECT COALESCE(SUM(esd.energy_uj), 0) AS domain_energy,
                   COUNT(*) AS n_samples
            FROM energy_sample_domains esd
            JOIN energy_samples_v2 esv ON esv.sample_id = esd.sample_id
            WHERE esv.run_id = ?
              AND esd.domain_id = ?
              AND esv.timestamp_ns >= ?
              AND esv.timestamp_ns <= ?
        """, (run_id, domain_id, start_ns, end_ns))
        row = cursor.fetchone()

        if row and row[1] > 0:
            total_uj += int(row[0])
            windows_with_data += 1

    if total_uj == 0:
        return None, windows_with_data

    return total_uj, windows_with_data
