"""
tool_failure_recorder.py — Single owner of all inserts to tool_failure_events.

Extracted from harness.py to keep that file clean and to give the recorder
a single place to enforce invariants (attempt_id and goal_id must be known
before recording — orphan rows are never created).

wasted_energy_uj is intentionally NULL at insert time.
The energy_attribution ETL populates it async after the run completes.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Valid failure_type values — must match tool_failure_events CHECK constraint
VALID_FAILURE_TYPES = frozenset({
    "timeout", "api_error", "malformed_input", "malformed_output",
    "rate_limit", "auth_error", "not_found", "other",
})

# Valid failure_phase values — must match tool_failure_events CHECK constraint
VALID_FAILURE_PHASES = frozenset({
    "selection", "execution", "parsing", "post_processing",
})


def record_tool_failure(
    conn,
    attempt_id: int,
    goal_id: int,
    tool_name: str,
    failure_type: str,
    failure_phase: Optional[str] = None,
    error_message: Optional[str] = None,
    retry_attempted: int = 0,
    retry_success: int = 0,
    recovery_strategy: Optional[str] = None,
    orchestration_event_id: Optional[int] = None,
) -> Optional[int]:
    """
    Insert one row into tool_failure_events.

    wasted_energy_uj is always NULL at insert — energy_attribution_etl
    populates it after the run completes (SC-4 ETL pattern).

    Args:
        conn:                   SQLite connection.
        attempt_id:             goal_attempt.attempt_id — must exist.
        goal_id:                goal_execution.goal_id — must exist.
        tool_name:              Name of the failing tool.
        failure_type:           Canonical type from tool_failure_events CHECK constraint.
        failure_phase:          Phase in which failure occurred, or None.
        error_message:          Raw error string. Prefix 'INJECTED:' for synthetic failures.
        retry_attempted:        1 if a retry was attempted for this tool call.
        retry_success:          1 if the retry succeeded.
        recovery_strategy:      Recovery action taken, or None.
        orchestration_event_id: FK to orchestration_events if available.

    Returns:
        failure_id (int) on success, None on failure.
    """
    # Guard: never create orphan rows — caller must have valid ids
    if attempt_id is None or goal_id is None:
        logger.warning(
            "record_tool_failure: skipping — attempt_id=%s goal_id=%s not set",
            attempt_id, goal_id,
        )
        return None

    # Normalise failure_type to CHECK-safe value
    if failure_type not in VALID_FAILURE_TYPES:
        logger.warning(
            "record_tool_failure: unrecognised failure_type=%r — coercing to 'other'",
            failure_type,
        )
        failure_type = "other"

    # Normalise failure_phase — NULL is valid, unknown strings are not
    if failure_phase is not None and failure_phase not in VALID_FAILURE_PHASES:
        logger.warning(
            "record_tool_failure: unrecognised failure_phase=%r — setting NULL",
            failure_phase,
        )
        failure_phase = None

    try:
        cur = conn.execute(
            """
            INSERT INTO tool_failure_events (
                attempt_id, goal_id, orchestration_event_id,
                tool_name, failure_type, failure_phase,
                error_message, retry_attempted, retry_success,
                recovery_strategy,
                wasted_energy_uj
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                attempt_id, goal_id, orchestration_event_id,
                tool_name, failure_type, failure_phase,
                error_message, retry_attempted, retry_success,
                recovery_strategy,
            ),
        )
        conn.commit()
        logger.debug(
            "record_tool_failure: failure_id=%d tool=%r type=%s",
            cur.lastrowid, tool_name, failure_type,
        )
        return cur.lastrowid

    except Exception as exc:
        # Log and return None — harness must continue even if recording fails
        logger.error("record_tool_failure: insert failed: %s", exc)
        return None
