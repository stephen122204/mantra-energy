"""
goal_execution_manager.py — Retry-aware goal execution engine.

Single owner of the harness → run → goal → attempt lifecycle for one
workflow side. ExperimentRunner and test_harness delegate here when
max_retries > 0 so retry logic never leaks into callers.

Design (confirmed — do not change):
    execute_goal() owns: retry loop + goal_tracker state transitions + tool failure recording
    RunPersistenceService owns: all DB insertion + ETL chain
    No DB logic lives here — clean separation of orchestration vs persistence.

Dependency graph:
    ExperimentRunner
        ├── GoalExecutionManager   (this module)
        └── RunPersistenceService  (core/execution/run_persistence.py)

    GoalExecutionManager → RunPersistenceService  (correct direction)
    GoalExecutionManager does NOT import ExperimentRunner  (no inversion)

Energy accounting:
    goal_execution.overhead_energy_uj = total_energy_uj - successful_energy_uj
    Captures all wasted retry energy — core paper thesis signal.

Naming rationale:
    execute_goal() — research-concept name matching paper's unit of analysis.
    Not run_one_side() — that is implementation language, not research language.
"""

import logging
import time
from typing import Optional

from scripts.etl import goal_execution_etl, energy_attribution_etl
from core.execution.retry_coordinator import RetryCoordinator, RetryPolicy
from core.execution.failure_classifier import FailureClassifier
from core.database.tool_failure_recorder import record_tool_failure
from core.execution.run_persistence import insert_one_run

logger = logging.getLogger(__name__)

# Module-level singletons — stateless, safe to share across calls
_retry_coordinator = RetryCoordinator()
_failure_classifier = FailureClassifier()

# Maps FailureClassifier types to tool_failure_events CHECK constraint values.
# tool_failure_events CHECK differs from goal_attempt failure_type — normalize here.
_TOOL_FAILURE_TYPE_MAP = {
    "timeout":          "timeout",
    "api_error":        "api_error",
    "rate_limit":       "rate_limit",
    "tool_error":       "other",
    "context_overflow": "other",
    "wrong_answer":     "other",
    "crashed":          "other",
}


def execute_goal(
    db,
    exp_id: int,
    hw_id: int,
    harness,
    executor,
    task: dict,
    workflow_type: str,
    rep_num: int,
    goal_tracker,
    policy: RetryPolicy,
    failure_injector=None,
) -> Optional[int]:
    """
    Execute one goal (one workflow side) with full retry support.

    Flow per attempt:
        start_attempt() → [inject?] → harness.run_*() → classify →
        record_tool_failure() → insert_one_run() → finish_attempt() →
        [retry if policy allows] → finish_goal() → ETL

    Args:
        db:               DB adapter.
        exp_id:           Parent experiment ID.
        hw_id:            Hardware profile ID.
        harness:          ExperimentHarness instance.
        executor:         LinearExecutor or AgenticExecutor.
        task:             Task dict — keys: id, name, prompt, meta.
        workflow_type:    'linear' or 'agentic' — never 'comparison'.
        rep_num:          Repetition number (1-indexed) for run_number field.
        goal_tracker:     GoalTracker instance — owns all DB state transitions.
        policy:           Resolved RetryPolicy for this goal.
        failure_injector: FailureInjector or None. Only active for injection studies.

    Returns:
        goal_id (int) or None on unrecoverable failure.
    """
    if workflow_type not in ("linear", "agentic"):
        logger.warning("execute_goal: invalid workflow_type=%r — aborting", workflow_type)
        return None

    conn        = db.db.conn
    task_id     = task.get("id", "unknown")
    task_name   = task.get("name", task_id)
    task_meta   = task.get("meta", {}) or {}
    task_prompt = task.get("prompt", "")
    is_cloud    = not executor.config.get("is_local", False)

    # One goal_execution row covers all retry attempts on this workflow side.
    # first_run_id=-1 — unknown at start, goal_tracker.finish_goal() updates it.
    goal_id = goal_tracker.start_goal(
        conn=conn,
        exp_id=exp_id,
        task_id=task_id,
        task_name=task_name,
        goal_type=task_meta.get("category", "custom"),
        workflow_type=workflow_type,
        difficulty_level=task_meta.get("level"),
        first_run_id=-1,
    )
    if goal_id is None:
        logger.warning("execute_goal: start_goal returned None — aborting")
        return None

    max_attempts    = policy.max_retries + 1
    prev_attempt_id = None
    winning_run_id  = None
    all_run_ids     = []
    attempts_made   = 0  # all started attempts including failed-before-insert

    for attempt_num in range(1, max_attempts + 1):
        is_retry    = attempt_num > 1
        attempts_made += 1

        attempt_id = goal_tracker.start_attempt(
            conn=conn,
            goal_id=goal_id,
            attempt_number=attempt_num,
            is_retry=is_retry,
            retry_of_attempt_id=prev_attempt_id if is_retry else None,
        )
        if attempt_id is None:
            logger.warning(
                "execute_goal: start_attempt returned None goal=%d attempt=%d",
                goal_id, attempt_num,
            )
            break

        result       = None
        failure_type = None
        outcome      = "failure"
        run_id       = None

        try:
            # Injection only active for injection experiment types — never in normal runs
            if failure_injector and failure_injector.is_active():
                if failure_injector.maybe_inject_timeout(
                    run_id=rep_num, attempt_number=attempt_num
                ):
                    raise TimeoutError("INJECTED: simulated timeout")

            if workflow_type == "linear":
                result = harness.run_linear(
                    executor=executor,
                    prompt=task_prompt,
                    task_id=task_id,
                    is_cloud=is_cloud,
                    run_number=rep_num,
                )
            else:
                result = harness.run_agentic(
                    executor=executor,
                    task=task_prompt,
                    task_id=task_id,
                    is_cloud=is_cloud,
                    run_number=rep_num,
                )

        except Exception as exc:
            # Harness raised — classify and record before moving to finish_attempt
            failure_type = _failure_classifier.classify(exception=exc)
            logger.warning(
                "execute_goal: goal=%d attempt=%d raised %s → %s",
                goal_id, attempt_num, type(exc).__name__, failure_type,
            )
            _record_attempt_failure(conn, attempt_id, goal_id, failure_type, str(exc))

        if result is not None:
            # Normalize status — agentic returns 'failed', linear returns 'failure'
            # Treat anything other than 'success' as failure for goal tracking
            # agentic success path has no "status" key — only failure path sets it.
            # Treat missing status as success; explicit "failed"/"failure" as failure.
            exec_dict = result.get("execution", {}) or {}
            _status   = exec_dict.get("status", "success")  # absent = success
            outcome   = "success" if _status not in ("failed", "failure") else "failure"
            # Classify result-level failures — harness caught exception internally
            if outcome != "success" and failure_type is None:
                failure_type = _failure_classifier.classify(run_result=result)
                # Record provider errors caught by harness — excludes generic 'crashed'
                # which has no meaningful error_message to record
                if failure_type and failure_type not in ("crashed", "wrong_answer"):
                    exec_dict = result.get("execution", {}) or {}
                    _record_attempt_failure(
                        conn, attempt_id, goal_id, failure_type,
                        str(exec_dict.get("error_message", "")),
                    )

            # Persist run — all attempts with data get a run_id for energy accounting
            run_id = insert_one_run(db, exp_id, hw_id, result, workflow_type, rep_num)
            if run_id:
                all_run_ids.append(run_id)

        energy_uj, orchestration_uj = _extract_energy(result)

        goal_tracker.finish_attempt(
            conn=conn,
            attempt_id=attempt_id,
            run_id=run_id or 0,
            outcome=outcome,
            energy_uj=energy_uj,
            orchestration_uj=orchestration_uj,
            compute_uj=0,
            failure_type=failure_type,
        )

        prev_attempt_id = attempt_id

        if outcome == "success" and run_id:
            winning_run_id = run_id
            logger.info(
                "execute_goal: goal=%d succeeded attempt=%d run_id=%d",
                goal_id, attempt_num, run_id,
            )
            break

        # Non-retryable — stop immediately, preserve energy for next goal
        if failure_type and not _retry_coordinator.is_retryable(failure_type, policy):
            logger.info(
                "execute_goal: goal=%d non-retryable=%s after attempt=%d",
                goal_id, failure_type, attempt_num,
            )
            break

        if attempt_num >= max_attempts:
            logger.info(
                "execute_goal: goal=%d exhausted %d attempts",
                goal_id, max_attempts,
            )
            break

        # Backoff only when another attempt will follow — never sleep at loop end
        if policy.backoff_seconds > 0:
            logger.debug(
                "execute_goal: goal=%d backing off %.1fs before retry",
                goal_id, policy.backoff_seconds,
            )
            time.sleep(policy.backoff_seconds)

    # finish_goal always called — regardless of outcome or exception path
    goal_tracker.finish_goal(
        conn=conn,
        goal_id=goal_id,
        success=winning_run_id is not None,
        winning_run_id=winning_run_id,
        total_attempts=attempts_made,  # all started attempts, not just persisted runs
    )

    # ETL — goal energy rollup after all attempts recorded
    goal_execution_etl.process_one(goal_id, conn)
    goal_tracker.queue_etl(conn, "goal_execution", goal_id, "goal_execution_etl")

    # Attribution stubs on ALL runs — failed retry runs contain wasted energy signal
    # Paper thesis: overhead_energy_uj sums across all failed attempts per goal
    for rid in all_run_ids:
        energy_attribution_etl.populate_attribution_stubs(rid, conn)
        goal_tracker.queue_etl(conn, "run", rid, "energy_attribution_etl")

    return goal_id


def _record_attempt_failure(
    conn,
    attempt_id: int,
    goal_id: int,
    failure_type: str,
    error_message: str,
) -> None:
    """
    Insert one tool_failure_events row for a failed attempt.

    Called for both exception-path and result-path failures.
    tool_name='harness' is pragmatic — future chunks split by provider/planner/tool_dispatch.
    wasted_energy_uj is NULL at insert — energy_attribution_etl backfills after run completes.
    """
    record_tool_failure(
        conn=conn,
        attempt_id=attempt_id,
        goal_id=goal_id,
        tool_name="harness",
        failure_type=_TOOL_FAILURE_TYPE_MAP.get(failure_type, "other"),
        failure_phase="execution",
        error_message=error_message,
        retry_attempted=0,
        retry_success=0,
    )


def _extract_energy(result: dict) -> tuple[int, int]:
    """
    Extract workload and orchestration energy from harness result dict.

    Returns (energy_uj, orchestration_uj) as integers.
    Returns (0, 0) if result is None or keys missing — never raises.
    Denormalised into goal_attempt for fast paper queries without ETL joins.
    """
    if result is None:
        return 0, 0
    try:
        energy_uj        = result["layer3_derived"]["energy_uj"]["workload"]
        orchestration_uj = result["layer3_derived"]["energy_uj"].get(
            "orchestration_tax", 0
        )
        return int(energy_uj or 0), int(orchestration_uj or 0)
    except (KeyError, TypeError):
        logger.debug("_extract_energy: result missing layer3_derived — returning zeros")
        return 0, 0
