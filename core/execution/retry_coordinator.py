"""
retry_coordinator.py — Owns the retry loop for goal execution.

experiment_runner delegates all retry decisions here.
RetryCoordinator calls goal_tracker for every state transition —
it never writes to the DB directly.

Design: policy resolution is separate from execution so experiment configs
can override per-task-category without changing the execution loop.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from core.execution.failure_classifier import FailureClassifier

logger = logging.getLogger(__name__)

# Policy name used when DB lookup fails — safe minimum behaviour
DEFAULT_POLICY_NAME = "default"


@dataclass
class RetryPolicy:
    """
    Loaded from retry_policy table. Immutable after construction.
    All bool fields stored as int in SQLite — coerced on load.
    """
    policy_name:           str
    max_retries:           int
    retry_on_timeout:      bool
    retry_on_tool_error:   bool
    retry_on_api_error:    bool
    retry_on_wrong_answer: bool
    backoff_seconds:       float


@dataclass
class ExecutionResult:
    """
    Returned by execute_with_policy().
    Caller uses winning_run_id to link goal_execution.winning_run_id.
    """
    success:        bool
    winning_run_id: Optional[int]
    total_attempts: int
    final_outcome:  str
    all_run_ids:    list = field(default_factory=list)


class RetryCoordinator:
    """
    Runs the harness up to policy.max_retries + 1 times per goal.
    Stops on first success or on a non-retryable failure.
    Never implements energy measurement or DB writes directly.
    """

    def __init__(self):
        self._classifier = FailureClassifier()

    # ── Policy loading ────────────────────────────────────────────────────────

    def load_policy(self, conn, policy_name: str) -> RetryPolicy:
        """
        Load retry policy from DB by name.
        Falls back to DEFAULT_POLICY_NAME if requested name not found.

        Args:
            conn:        SQLite connection.
            policy_name: Name key into retry_policy table.

        Returns:
            RetryPolicy dataclass. Never returns None.
        """
        row = conn.execute(
            "SELECT * FROM retry_policy WHERE policy_name = ?", (policy_name,)
        ).fetchone()

        if row is None:
            logger.warning(
                "RetryCoordinator: policy %r not found — loading %r",
                policy_name, DEFAULT_POLICY_NAME,
            )
            row = conn.execute(
                "SELECT * FROM retry_policy WHERE policy_name = ?",
                (DEFAULT_POLICY_NAME,),
            ).fetchone()

        if row is None:
            # DB has no policies at all — return hardcoded safe minimum
            logger.error("RetryCoordinator: no policies in DB — using hardcoded default")
            return RetryPolicy(
                policy_name="default", max_retries=1,
                retry_on_timeout=True, retry_on_tool_error=True,
                retry_on_api_error=True, retry_on_wrong_answer=False,
                backoff_seconds=0.0,
            )

        return RetryPolicy(
            policy_name=row["policy_name"],
            max_retries=row["max_retries"],
            retry_on_timeout=bool(row["retry_on_timeout"]),
            retry_on_tool_error=bool(row["retry_on_tool_error"]),
            retry_on_api_error=bool(row["retry_on_api_error"]),
            retry_on_wrong_answer=bool(row["retry_on_wrong_answer"]),
            backoff_seconds=row["backoff_seconds"],
        )

    def resolve_policy(
        self,
        conn,
        template_policy_name: str,
        task_category: str,
    ) -> RetryPolicy:
        """
        Resolve final policy with per-category override applied.

        Resolution order:
          1. Load template policy by name
          2. Check task_retry_override for task_category
          3. If override exists, replace max_retries only — other flags unchanged

        This design keeps override minimal: only max_retries is overridden,
        not the full policy, so failure-type flags remain consistent.

        Args:
            conn:                 SQLite connection.
            template_policy_name: Base policy name from experiment config.
            task_category:        Task category string for override lookup.

        Returns:
            Resolved RetryPolicy.
        """
        policy = self.load_policy(conn, template_policy_name)

        override = conn.execute(
            "SELECT max_retries FROM task_retry_override WHERE task_category = ?",
            (task_category,),
        ).fetchone()

        if override is not None:
            logger.debug(
                "RetryCoordinator: override max_retries=%d for category %r",
                override["max_retries"], task_category,
            )
            # Replace only max_retries — construct new dataclass to keep immutability
            policy = RetryPolicy(
                policy_name=policy.policy_name,
                max_retries=override["max_retries"],
                retry_on_timeout=policy.retry_on_timeout,
                retry_on_tool_error=policy.retry_on_tool_error,
                retry_on_api_error=policy.retry_on_api_error,
                retry_on_wrong_answer=policy.retry_on_wrong_answer,
                backoff_seconds=policy.backoff_seconds,
            )

        return policy

    # ── Retry decision ────────────────────────────────────────────────────────

    def is_retryable(self, failure_type: str, policy: RetryPolicy) -> bool:
        """
        Return True only if this failure_type is enabled for retry in policy.
        'crashed' is never retryable — unknown failures should not loop.

        Args:
            failure_type: Canonical string from FailureClassifier.
            policy:       Active retry policy.

        Returns:
            bool — whether another attempt should be made.
        """
        if failure_type == "crashed":
            return False

        mapping = {
            "timeout":          policy.retry_on_timeout,
            "api_error":        policy.retry_on_api_error,
            "rate_limit":       policy.retry_on_api_error,   # rate_limit treated as api_error
            "tool_error":       policy.retry_on_tool_error,
            "wrong_answer":     policy.retry_on_wrong_answer,
            "context_overflow": False,  # never retry — prompt won't shrink on its own
        }
        return mapping.get(failure_type, False)

    # ── Execution loop ────────────────────────────────────────────────────────

    def execute_with_policy(
        self,
        conn,
        harness,
        task: dict,
        goal_id: int,
        policy: RetryPolicy,
        goal_tracker,
        attempt_number_start: int = 1,
    ) -> ExecutionResult:
        """
        Run harness up to policy.max_retries + 1 times for one goal.

        Each iteration:
          start_attempt() → harness.run() → classify → finish_attempt()

        Stops on first success or non-retryable failure or max attempts reached.
        goal_tracker owns all DB state transitions — coordinator never writes directly.

        Args:
            conn:                 SQLite connection for goal_tracker calls.
            harness:              Harness instance with a run(task) method.
            task:                 Task dict passed to harness.run().
            goal_id:              Already-created goal_execution row id.
            policy:               Resolved RetryPolicy for this goal.
            goal_tracker:         GoalTracker instance.
            attempt_number_start: Starting attempt number (1 for fresh goals).

        Returns:
            ExecutionResult with outcome summary.
        """
        max_attempts  = policy.max_retries + 1
        all_run_ids   = []
        prev_attempt_id = None
        final_outcome = "failure"
        winning_run_id = None

        for attempt_num in range(attempt_number_start, attempt_number_start + max_attempts):
            is_retry = attempt_num > attempt_number_start

            # Register attempt with goal_tracker before running harness
            attempt_id = goal_tracker.start_attempt(
                conn=conn,
                goal_id=goal_id,
                attempt_number=attempt_num,
                is_retry=is_retry,
                retry_of_attempt_id=prev_attempt_id if is_retry else None,
            )
            if attempt_id is None:
                logger.warning(
                    "execute_with_policy: start_attempt returned None for goal %d attempt %d",
                    goal_id, attempt_num,
                )
                break

            # Run harness — classify exception or result outcome
            result       = None
            failure_type = None
            exc_caught   = None

            try:
                result = harness.run(task)
            except Exception as exc:
                exc_caught   = exc
                failure_type = self._classifier.classify(exception=exc)
                logger.warning(
                    "execute_with_policy: attempt %d raised %s → %s",
                    attempt_num, type(exc).__name__, failure_type,
                )

            # Classify result-based failures when no exception was raised
            if result is not None:
                outcome = result.get("execution", {}).get("status", "failure")
                if outcome != "success":
                    failure_type = self._classifier.classify(run_result=result)
            else:
                outcome = "failure"

            success = (outcome == "success" and exc_caught is None)

            # Energy snapshots for attempt row — zero if run never produced them
            energy_uj        = 0
            orchestration_uj = 0
            compute_uj       = 0
            run_id           = None

            if result is not None:
                try:
                    energy_uj        = result["layer3_derived"]["energy_uj"]["workload"]
                    orchestration_uj = result["layer3_derived"]["energy_uj"].get("orchestration_tax", 0)
                except (KeyError, TypeError):
                    pass
                run_id = result.get("run_id")

            if run_id:
                all_run_ids.append(run_id)

            goal_tracker.finish_attempt(
                conn=conn,
                attempt_id=attempt_id,
                run_id=run_id or 0,
                outcome=outcome if not exc_caught else failure_type,
                energy_uj=energy_uj,
                orchestration_uj=orchestration_uj,
                compute_uj=compute_uj,
                failure_type=failure_type,
            )

            prev_attempt_id = attempt_id

            if success:
                final_outcome  = "success"
                winning_run_id = run_id
                logger.info(
                    "execute_with_policy: goal %d succeeded on attempt %d",
                    goal_id, attempt_num,
                )
                break

            # Decide whether to retry
            if failure_type and self.is_retryable(failure_type, policy):
                if attempt_num < attempt_number_start + max_attempts - 1:
                    if policy.backoff_seconds > 0:
                        logger.debug(
                            "execute_with_policy: backing off %.1fs before retry",
                            policy.backoff_seconds,
                        )
                        time.sleep(policy.backoff_seconds)
                    continue

            # Non-retryable or exhausted — stop
            final_outcome = failure_type or "failure"
            logger.info(
                "execute_with_policy: goal %d stopped after %d attempt(s) — %s",
                goal_id, attempt_num - attempt_number_start + 1, final_outcome,
            )
            break

        total_attempts = len(all_run_ids) if all_run_ids else (
            attempt_number_start  # at least one attempt was made
        )

        return ExecutionResult(
            success=winning_run_id is not None,
            winning_run_id=winning_run_id,
            total_attempts=total_attempts,
            final_outcome=final_outcome,
            all_run_ids=all_run_ids,
        )
