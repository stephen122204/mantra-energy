"""
goal_tracker.py — Single owner of goal_execution and goal_attempt state transitions.

experiment_runner.py calls this module. No other file writes to goal tables directly.
All methods accept conn as first param — this module never owns a DB connection.
All methods are sync — no async, no threading.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Category mappings ─────────────────────────────────────────────────────────
# Maps task.category → goal_type CHECK constraint values in goal_execution.
# 'custom' catches any category not in this map via .get() default.
from core.ontology_registry import CATEGORY_TO_GOAL_TYPE


# Maps task.level (int) → difficulty_level CHECK values in goal_execution.
# Level 0 or missing → NULL difficulty (historical data compatibility).
LEVEL_TO_DIFFICULTY = {
    1: "easy",
    2: "medium",
    3: "hard",
}

# Outcome → attempt status mapping.
# outcome comes from harness result; status is the DB-stored terminal state.
OUTCOME_TO_STATUS = {
    "success":          "success",
    "failure":          "failed",
    "hallucination":    "failed",
    "timeout":          "timeout",
    "context_overflow": "crashed",
    "api_error":        "crashed",
}


def _now_utc() -> str:
    """Return current UTC timestamp as ISO string for TIMESTAMP columns."""
    return datetime.now(timezone.utc).isoformat(sep=" ", timespec="seconds")


class GoalTracker:
    """
    Single owner of all goal and attempt state transitions.

    Lifecycle per run:
        start_goal()     → INSERT goal_execution, status='running'
        start_attempt()  → INSERT goal_attempt, status='running'
        finish_attempt() → UPDATE goal_attempt with terminal state + snapshots
        finish_goal()    → UPDATE goal_execution with final outcome
        queue_etl()      → INSERT etl_queue entry for async-safe ETL pickup
    """

    # ── Public API ────────────────────────────────────────────────────────────

    def start_goal(
        self,
        conn,
        exp_id: int,
        task_id: str,
        task_name: str,
        goal_type: str,
        workflow_type: str,
        difficulty_level,
        first_run_id: int,
    ) -> int:
        """
        INSERT goal_execution with status='running'. Returns goal_id.

        workflow_type must be 'linear' or 'agentic' — never 'comparison'.
        first_run_id = -1 placeholder; updated by finish_goal() once run completes.
        difficulty_level: pass task.level int and mapping happens here, or pass
        string directly, or None for historical data without level.

        Args:
            conn:             Active DB connection — not owned by this method.
            exp_id:           Parent experiment ID.
            task_id:          Task identifier string (e.g. 'gsm8k_basic').
            task_name:        Human readable task name for goal_description.
            goal_type:        Must match goal_type CHECK constraint values.
            workflow_type:    'linear' or 'agentic' only.
            difficulty_level: int (1-3), string ('easy'/'medium'/'hard'), or None.
            first_run_id:     Pass -1 — updated when run_id is known.

        Returns:
            goal_id (int) of the inserted row.
        """
        # workflow_type guard — 'comparison' must never reach goal_execution
        if workflow_type not in ("linear", "agentic"):
            logger.warning(
                "start_goal: invalid workflow_type=%r for task=%s — skipping",
                workflow_type, task_id,
            )
            return None

        # Resolve difficulty from int level if caller passed an int
        resolved_difficulty = self._resolve_difficulty(difficulty_level)

        # Resolve goal_type — default to 'other' for unknown categories
        resolved_goal_type = self._resolve_goal_type(goal_type)

        now = _now_utc()
        sql = """
            INSERT INTO goal_execution (
                exp_id, first_run_id, goal_description, goal_type,
                workflow_type, difficulty_level, task_id,
                status, started_at, updated_at,
                total_attempts, success
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, 1, 0)
        """
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            cur = conn.execute(sql, (
                exp_id, 0, task_name, resolved_goal_type,
                workflow_type, resolved_difficulty, task_id,
                now, now,
            ))
            conn.commit()
            conn.execute("PRAGMA foreign_keys = ON")
            goal_id = cur.lastrowid
            logger.debug("start_goal: goal_id=%d task=%s wf=%s", goal_id, task_id, workflow_type)
            return goal_id
        except Exception as e:
            logger.warning("start_goal: INSERT failed task=%s: %s", task_id, e)
            return None

    def start_attempt(
        self,
        conn,
        goal_id: int,
        attempt_number: int,
        retry_of_attempt_id: int = None,
    ) -> int:
        """
        INSERT goal_attempt with status='running', started_at=NOW. Returns attempt_id.

        retry_of_attempt_id is None for first attempt — 8.5-B populates it for retries.

        Args:
            conn:                 Active DB connection.
            goal_id:              Parent goal_execution row.
            attempt_number:       1-indexed attempt counter per goal.
            retry_of_attempt_id:  None for attempt_number=1. 8.5-B sets this.

        Returns:
            attempt_id (int) of the inserted row, or None on failure.
        """
        if goal_id is None:
            logger.warning("start_attempt: goal_id is None — skipping")
            return None

        now = _now_utc()
        # outcome placeholder required by NOT NULL — will be overwritten by finish_attempt
        sql = """
            INSERT INTO goal_attempt (
                goal_id, run_id, attempt_number, is_winning,
                outcome, status, started_at, updated_at
            ) VALUES (?, -1, ?, 0, 'failure', 'running', ?, ?)
        """
        # run_id = -1 placeholder; finish_attempt() updates it with real run_id
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            cur = conn.execute(sql, (goal_id, attempt_number, now, now))
            conn.commit()
            conn.execute("PRAGMA foreign_keys = ON")
            attempt_id = cur.lastrowid
            logger.debug(
                "start_attempt: attempt_id=%d goal_id=%d attempt_number=%d",
                attempt_id, goal_id, attempt_number,
            )
            return attempt_id
        except Exception as e:
            logger.warning("start_attempt: INSERT failed goal_id=%d: %s", goal_id, e)
            return None

    def finish_attempt(
        self,
        conn,
        attempt_id: int,
        run_id: int,
        outcome: str,
        energy_uj: int,
        orchestration_uj: int,
        compute_uj: int,
        failure_cause: str = None,
        failure_type: str = None,
    ) -> None:
        """
        UPDATE goal_attempt with terminal state, run_id, and energy snapshots.

        Energy values are denormalized snapshots — ETL never re-reads these from attempt.
        outcome drives is_winning: 'success' → is_winning=1.

        Args:
            conn:             Active DB connection.
            attempt_id:       Row to update.
            run_id:           The run_id produced by save_pair()/save_single().
            outcome:          Terminal outcome string per goal_attempt CHECK constraint.
            energy_uj:        Total energy snapshot from runs.pkg_energy_uj.
            orchestration_uj: Snapshot from energy_attribution.orchestration_energy_uj.
            compute_uj:       Snapshot from energy_attribution.compute_energy_uj.
            failure_cause:    Populated on failure — maps to failure_cause CHECK values.
            failure_type:     8.5-B classifier output. NULL in 8.5-A.
        """
        if attempt_id is None:
            logger.warning("finish_attempt: attempt_id is None — skipping")
            return

        # Derive status from outcome using canonical mapping
        status = OUTCOME_TO_STATUS.get(outcome, "crashed")
        is_winning = 1 if outcome == "success" else 0
        now = _now_utc()

        sql = """
            UPDATE goal_attempt SET
                run_id           = ?,
                outcome          = ?,
                status           = ?,
                is_winning       = ?,
                energy_uj        = ?,
                orchestration_uj = ?,
                compute_uj       = ?,
                failure_cause    = ?,
                finished_at      = ?,
                updated_at       = ?
            WHERE attempt_id = ?
        """
        try:
            conn.execute(sql, (
                run_id, outcome, status, is_winning,
                energy_uj, orchestration_uj, compute_uj,
                failure_cause, now, now,
                attempt_id,
            ))
            conn.commit()
            logger.debug(
                "finish_attempt: attempt_id=%d run_id=%d outcome=%s",
                attempt_id, run_id, outcome,
            )
        except Exception as e:
            logger.warning(
                "finish_attempt: UPDATE failed attempt_id=%d: %s", attempt_id, e,
            )

    def finish_goal(
        self,
        conn,
        goal_id: int,
        success: bool,
        winning_run_id: int = None,
        total_attempts: int = 1,
    ) -> None:
        """
        UPDATE goal_execution with final outcome and winning_run_id.

        Also sets first_run_id to the minimum run_id across all attempts —
        resolving the -1 placeholder set at start_goal() time.

        Args:
            conn:           Active DB connection.
            goal_id:        Row to update.
            success:        True → status='solved', False → status='failed'.
            winning_run_id: run_id of the successful attempt. NULL if no success.
            total_attempts: Total attempt count including failures.
        """
        if goal_id is None:
            logger.warning("finish_goal: goal_id is None — skipping")
            return

        status = "solved" if success else "failed"
        success_int = 1 if success else 0
        now = _now_utc()

        # Resolve first_run_id from minimum run_id across all attempts for this goal.
        # This replaces the -1 placeholder inserted at start_goal() time.
        first_run_id = self._resolve_first_run_id(conn, goal_id, winning_run_id)

        sql = """
            UPDATE goal_execution SET
                status         = ?,
                success        = ?,
                winning_run_id = ?,
                first_run_id   = ?,
                total_attempts = ?,
                finished_at    = ?,
                updated_at     = ?
            WHERE goal_id = ?
        """
        try:
            conn.execute(sql, (
                status, success_int, winning_run_id,
                first_run_id, total_attempts,
                now, now,
                goal_id,
            ))
            conn.commit()
            logger.debug(
                "finish_goal: goal_id=%d success=%s status=%s",
                goal_id, success, status,
            )
        except Exception as e:
            logger.warning(
                "finish_goal: UPDATE failed goal_id=%d: %s", goal_id, e,
            )

    def queue_etl(
        self,
        conn,
        entity_type: str,
        entity_id: int,
        etl_name: str,
    ) -> None:
        """
        INSERT into etl_queue — marks an entity as pending ETL processing.

        ETL runner reads this table and processes entries. This method never
        calls ETL directly — decoupling is the whole point of this table.

        Args:
            conn:        Active DB connection.
            entity_type: 'goal_execution' or 'run'.
            entity_id:   goal_id or run_id depending on entity_type.
            etl_name:    ETL script name e.g. 'goal_execution_etl'.
        """
        if entity_type not in ("goal_execution", "run"):
            logger.warning("queue_etl: invalid entity_type=%r — skipping", entity_type)
            return

        sql = """
            INSERT INTO etl_queue (entity_type, entity_id, etl_name, status)
            VALUES (?, ?, ?, 'pending')
        """
        try:
            conn.execute(sql, (entity_type, entity_id, etl_name))
            conn.commit()
            logger.debug(
                "queue_etl: queued %s entity_id=%d etl=%s",
                entity_type, entity_id, etl_name,
            )
        except Exception as e:
            # Non-fatal — ETL queue failure must not block experiment results
            logger.warning(
                "queue_etl: INSERT failed entity_type=%s entity_id=%d: %s",
                entity_type, entity_id, e,
            )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _resolve_difficulty(self, difficulty_level) -> str:
        """
        Normalise difficulty_level input to DB-valid string or None.
        Accepts int (1-3), string ('easy'/'medium'/'hard'), or None.
        Unknown int or string → None with a warning.
        """
        if difficulty_level is None:
            return None
        if isinstance(difficulty_level, int):
            resolved = LEVEL_TO_DIFFICULTY.get(difficulty_level)
            if resolved is None:
                logger.warning(
                    "_resolve_difficulty: unknown level int=%d → NULL", difficulty_level,
                )
            return resolved
        # Already a string — validate against known values
        if difficulty_level in ("easy", "medium", "hard"):
            return difficulty_level
        logger.warning(
            "_resolve_difficulty: unknown difficulty string=%r → NULL", difficulty_level,
        )
        return None

    def _resolve_goal_type(self, goal_type: str) -> str:
        """
        Map raw category string to goal_type CHECK constraint value.
        Falls through CATEGORY_TO_GOAL_TYPE; unknown categories → 'other'.
        """
        if goal_type in ("factual", "reasoning", "tool_use", "multi_step", "code", "other"):
            # Caller already passed a valid goal_type directly
            return goal_type
        # Treat as a category string and map it
        resolved = CATEGORY_TO_GOAL_TYPE.get(goal_type, "other")
        if resolved == "other" and goal_type not in CATEGORY_TO_GOAL_TYPE:
            logger.debug(
                "_resolve_goal_type: unknown category=%r → 'other'", goal_type,
            )
        return resolved

    def _resolve_first_run_id(
        self, conn, goal_id: int, winning_run_id: int
    ) -> int:
        """
        Find the minimum run_id across all goal_attempt rows for this goal.
        Falls back to winning_run_id if no attempts found (should not happen).
        Returns winning_run_id as last resort — never returns -1 to caller.
        """
        try:
            row = conn.execute(
                "SELECT MIN(run_id) FROM goal_attempt WHERE goal_id = ? AND run_id != -1",
                (goal_id,),
            ).fetchone()
            if row and row[0] is not None:
                return row[0]
        except Exception as e:
            logger.warning(
                "_resolve_first_run_id: query failed goal_id=%d: %s", goal_id, e,
            )
        # Fallback — winning_run_id is always valid in the single-attempt path
        return winning_run_id
