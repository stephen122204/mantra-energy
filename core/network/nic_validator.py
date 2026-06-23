"""
core/network/nic_validator.py
NIC activity validator for network energy attribution.

SPEC_03A: Validates SPEC_03 energy attribution windows using NIC
telemetry from nic_samples table. Adjusts confidence scores based
on observed byte transfer during LLM blocking windows.

Uses delta(tx_bytes + rx_bytes) as primary signal — direct observable,
no interpretation required. Does NOT multiply energy by NIC active
fraction (stacking assumptions is indefensible for paper claims).

If nic_samples table does not exist (SPEC_03A not deployed), returns
base confidence unmodified — graceful degradation (PAC-4).

DC-1: 30% inline comment coverage.
"""

import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Confidence penalty multiplier for windows with no observed NIC activity.
# Window had a blocking call but NIC bytes did not move — possible causes:
# GIL contention, DNS lookup, TCP retransmit with NIC idle, loopback traffic.
_NO_ACTIVITY_PENALTY = 0.75


def validate_windows_with_nic(
    run_id: int,
    windows: List[dict],
    base_confidence: float,
    db_conn: "sqlite3.Connection",
) -> Tuple[float, Optional[bool], float]:
    """
    Validate blocking windows against NIC byte counter telemetry.

    Checks whether NIC byte counters moved during each blocking window.
    Returns adjusted confidence, validation flag, and NIC coverage fraction.

    Args:
        run_id:          The run to validate.
        windows:         List of blocking window dicts with request_start_ns
                         and first_token_time_ns keys.
        base_confidence: Strategy base confidence (e.g. 0.93 for Strategy A).
        db_conn:         Open SQLite connection.

    Returns:
        Tuple of (adjusted_confidence, nic_validated, nic_coverage_fraction).
        adjusted_confidence:  base_confidence if all windows validated,
                              reduced by _NO_ACTIVITY_PENALTY otherwise.
        nic_validated:        True if at least one window had NIC activity,
                              None if nic_samples not available (not checked).
        nic_coverage_fraction: fraction of windows with NIC telemetry data.
    """
    # No windows = local inference, nothing to validate
    if not windows:
        return (base_confidence, None, 0.0)

    # Check SPEC_03A deployment — graceful fallback if not deployed
    if not _nic_samples_available(run_id, db_conn):
        return (base_confidence, None, 0.0)

    windows_with_nic_data = 0
    windows_with_activity = 0

    for w in windows:
        t_start = w.get("request_start_ns")
        t_end   = w.get("first_token_time_ns")

        # Skip malformed windows
        if t_start is None or t_end is None or t_end <= t_start:
            continue

        delta = _nic_byte_delta(run_id, t_start, t_end, db_conn)

        if delta is not None:
            windows_with_nic_data += 1
            if delta > 0:
                # NIC byte counters moved — confirmed network activity
                windows_with_activity += 1

    total = len(windows)
    nic_coverage = windows_with_nic_data / total if total > 0 else 0.0

    # No NIC samples overlapped any window — timing mismatch or no data
    if windows_with_nic_data == 0:
        return (base_confidence, None, 0.0)

    # Compute validated fraction — how many covered windows had activity
    validated_fraction = (
        windows_with_activity / windows_with_nic_data
        if windows_with_nic_data > 0 else 0.0
    )

    # Confidence adjustment: full weight for validated, penalized for idle
    adjusted = base_confidence * (
        validated_fraction + (1.0 - validated_fraction) * _NO_ACTIVITY_PENALTY
    )

    nic_validated = windows_with_activity > 0

    logger.info(
        "nic_validator: run=%d windows=%d with_data=%d active=%d "
        "base=%.3f adjusted=%.3f validated=%s coverage=%.2f",
        run_id, total, windows_with_nic_data, windows_with_activity,
        base_confidence, adjusted, nic_validated, nic_coverage,
    )

    return (round(adjusted, 4), nic_validated, round(nic_coverage, 4))


def _nic_samples_available(run_id: int, db_conn: "sqlite3.Connection") -> bool:
    """
    Check if nic_samples table exists and has data for this run.

    Returns False if table missing (SPEC_03A not deployed) — never raises.
    """
    try:
        row = db_conn.execute(
            "SELECT 1 FROM nic_samples WHERE run_id = ? LIMIT 1",
            (run_id,),
        ).fetchone()
        return row is not None
    except Exception:
        # Table does not exist — SPEC_03A not deployed, graceful degradation
        return False


def _nic_byte_delta(
    run_id: int,
    t_start: int,
    t_end: int,
    db_conn: "sqlite3.Connection",
) -> Optional[int]:
    """
    Compute delta(tx_bytes + rx_bytes) during [t_start, t_end].

    Returns total byte movement in window, or None if no NIC samples
    overlap. This is the primary validation signal — direct observable,
    no modelling required.

    Clamps negative values to 0 to handle counter wrap-around edge case.
    """
    sql = """
        SELECT
            MAX(tx_bytes) + MAX(rx_bytes)
            - MIN(tx_bytes) - MIN(rx_bytes)
        FROM nic_samples
        WHERE run_id = ?
          AND sample_ns BETWEEN ? AND ?
          AND tx_bytes IS NOT NULL
          AND rx_bytes IS NOT NULL
    """
    try:
        row = db_conn.execute(sql, (run_id, t_start, t_end)).fetchone()
        if row is None or row[0] is None:
            return None
        # Clamp negative — counter wrap or interface restart during window
        return max(0, int(row[0]))
    except Exception as exc:
        logger.debug("nic_validator: byte delta query failed: %s", exc)
        return None
