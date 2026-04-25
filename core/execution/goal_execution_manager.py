"""
goal_execution_manager.py — Retry-aware goal execution engine.

Single owner of the harness → run → goal → attempt lifecycle for one
workflow side. experiment_runner and test_harness delegate here when
max_retries > 0 so retry logic never leaks into callers.

Design rationale (Option A — confirmed):
    One goal_execution row per task per workflow side per repetition.
    One goal_attempt row per execution attempt (including retries).
    Retry loop lives here — callers remain thin coordinators.

Energy accounting:
    goal_execution.overhead_energy_uj = total_energy_uj - successful_energy_uj
    Captures all wasted retry energy in one field — core paper thesis signal.

Naming:
    execute_goal() — research-concept name matching paper's unit of analysis.
    Not "run_one_side" — that is implementation language, not research language.
"""

import logging
import time
from typing import Optional

from scripts.etl.phase_attribution_etl import compute_phase_attribution
from scripts.etl.aggregate_hardware_metrics import aggregate_hardware_metrics
from scripts.etl.energy_attribution_etl import compute_energy_attribution
from scripts.etl.duration_fix_etl import fix_run, fix_run_with_pretask
from scripts.etl.ttft_tpot_etl import populate_run as populate_ttft_tpot
from scripts.etl import goal_execution_etl, energy_attribution_etl
from core.execution.retry_coordinator import RetryCoordinator, RetryPolicy
from core.execution.failure_classifier import FailureClassifier
from core.database.tool_failure_recorder import record_tool_failure
from core.utils.provenance import record_run_provenance

logger = logging.getLogger(__name__)

# Module-level singletons — stateless, safe to share across calls
_retry_coordinator = RetryCoordinator()
_failure_classifier = FailureClassifier()

# Maps FailureClassifier types to tool_failure_events CHECK constraint values.
# tool_failure_events has its own CHECK — not identical to goal_attempt failure_type.
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
        start_attempt() → harness.run_*() → _insert_run_with_etl() →
        finish_attempt() → [retry if policy allows] → finish_goal()

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
    task_meta   = task.get("meta", {})
    task_prompt = task.get("prompt", "")
    is_cloud    = not executor.config.get("is_local", False)

    # Single goal_execution row covers all retry attempts on this side
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
    final_outcome   = "failure"

    for attempt_num in range(1, max_attempts + 1):
        is_retry = attempt_num > 1

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

        try:
            # Injection check — only active for injection experiment types
            if failure_injector and failure_injector.is_active():
                if failure_injector.maybe_inject_timeout(
                    run_id=attempt_num, attempt_number=attempt_num
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
            failure_type = _failure_classifier.classify(exception=exc)
            logger.warning(
                "execute_goal: goal=%d attempt=%d raised %s → %s",
                goal_id, attempt_num, type(exc).__name__, failure_type,
            )
            # Record harness-level failure in tool_failure_events for energy attribution
            record_tool_failure(
                conn=conn,
                attempt_id=attempt_id,
                goal_id=goal_id,
                tool_name="harness",
                failure_type=_TOOL_FAILURE_TYPE_MAP.get(failure_type, "other"),
                failure_phase="execution",
                error_message=str(exc),
                retry_attempted=0,
                retry_success=0,
            )

        # Outcome and run_id from result — zero values if harness raised
        outcome = "failure"
        run_id  = None

        if result is not None:
            outcome = result.get("execution", {}).get("status", "failure")
            # Classify result-based failures when no exception was raised
            if outcome != "success" and failure_type is None:
                failure_type = _failure_classifier.classify(run_result=result)

            result["ml_features"]["run_number"] = rep_num
            run_id = _insert_run_with_etl(db, exp_id, hw_id, result)
            if run_id:
                all_run_ids.append(run_id)

        # Energy snapshots — denormalised into attempt row for fast paper queries
        energy_uj = orchestration_uj = 0
        if result is not None:
            try:
                energy_uj        = result["layer3_derived"]["energy_uj"]["workload"]
                orchestration_uj = result["layer3_derived"]["energy_uj"].get(
                    "orchestration_tax", 0
                )
            except (KeyError, TypeError):
                pass

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
            final_outcome  = "success"
            logger.info(
                "execute_goal: goal=%d succeeded attempt=%d run_id=%d",
                goal_id, attempt_num, run_id,
            )
            break

        # Non-retryable failure — stop immediately, don't waste energy
        if failure_type and not _retry_coordinator.is_retryable(failure_type, policy):
            final_outcome = failure_type
            logger.info(
                "execute_goal: goal=%d non-retryable=%s after attempt=%d",
                goal_id, failure_type, attempt_num,
            )
            break

        # Max attempts exhausted
        if attempt_num >= max_attempts:
            final_outcome = failure_type or "failure"
            logger.info(
                "execute_goal: goal=%d exhausted %d attempts — %s",
                goal_id, max_attempts, final_outcome,
            )
            break

        # Backoff before retry — only when another attempt will follow
        if policy.backoff_seconds > 0:
            logger.debug("execute_goal: backing off %.1fs before retry", policy.backoff_seconds)
            time.sleep(policy.backoff_seconds)

    # Finish goal — always called, regardless of outcome
    goal_tracker.finish_goal(
        conn=conn,
        goal_id=goal_id,
        success=winning_run_id is not None,
        winning_run_id=winning_run_id,
        total_attempts=len(all_run_ids) or 1,
    )

    # ETL — goal energy rollup after all attempts recorded
    goal_execution_etl.process_one(goal_id, conn)
    goal_tracker.queue_etl(conn, "goal_execution", goal_id, "goal_execution_etl")

    if all_run_ids:
        energy_attribution_etl.populate_attribution_stubs(all_run_ids[-1], conn)
        goal_tracker.queue_etl(conn, "run", all_run_ids[-1], "energy_attribution_etl")

    return goal_id


def _insert_run_with_etl(
    db,
    exp_id: int,
    hw_id: int,
    result: dict,
) -> Optional[int]:
    """
    Insert run row, all sample tables, and run ETL chain for one attempt.
    Mirrors save_pair() ETL sequence exactly — single source of truth.

    Returns run_id or None on failure.
    """
    result_copy = result.copy()
    result_copy["baseline_id"] = result_copy.get("ml_features", {}).get("baseline_id")

    with db.transaction():
        run_id = db.insert_run(exp_id, hw_id, result)
        if run_id is None:
            logger.warning("_insert_run_with_etl: insert_run returned None")
            return None

        record_run_provenance(db, run_id, result, reader_mode=result.get("reader_mode"))

        # Energy samples — handle old tuple format for backward compat
        if "energy_samples" in result:
            converted = []
            for sample in result["energy_samples"]:
                if isinstance(sample, dict):
                    converted.append(sample)
                elif len(sample) == 2 and isinstance(sample[1], dict):
                    ts, ed = sample
                    converted.append({
                        "timestamp_ns":     int(ts * 1_000_000_000),
                        "pkg_energy_uj":    ed.get("package-0", 0),
                        "core_energy_uj":   ed.get("core", 0),
                        "uncore_energy_uj": ed.get("uncore", 0),
                        "dram_energy_uj":   0,
                    })
            if converted:
                db.insert_energy_samples(run_id, converted)

        if "cpu_samples" in result:
            db.insert_cpu_samples(run_id, result["cpu_samples"])
        if "interrupt_samples" in result:
            db.insert_interrupt_samples(run_id, result["interrupt_samples"])
        if "io_samples" in result:
            db.insert_io_samples(run_id, result["io_samples"])
        if "thermal_samples" in result:
            db.insert_thermal_samples(run_id, result["thermal_samples"])
        if "orchestration_events" in result:
            db.insert_orchestration_events(run_id, result["orchestration_events"])

        # LLM interactions — key is pending_interactions, run_id set per interaction
        if result.get("pending_interactions"):
            for interaction in result["pending_interactions"]:
                interaction["run_id"] = run_id
                db.insert_llm_interaction(interaction)

    # ETL chain — same order as save_pair()
    compute_phase_attribution(run_id)
    aggregate_hardware_metrics(run_id)
    compute_energy_attribution(run_id)
    populate_ttft_tpot(run_id)

    # Duration fix — mirrors save_pair() fix block exactly
    _ml = result.get("ml_features", {})
    if _ml.get("rapl_before_pretask") is not None:
        fix_run_with_pretask(
            run_id,
            _ml.get("rapl_before_pretask"),
            _ml.get("rapl_after_task"),
            _ml.get("pre_task_duration_sec", 0.0),
            _ml.get("post_task_duration_sec", 0.0),
            _ml.get("cpu_frac_pre", 0.0),
            _ml.get("cpu_frac_post", 0.0),
        )
    else:
        fix_run(run_id)

    return run_id
