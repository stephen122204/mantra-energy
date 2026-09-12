"""Single-goal integration using only merged study interfaces."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from studies.energy_diagnosis.campaign import ArtifactRef, PlannedRun, RunLedger
from studies.energy_diagnosis.contracts import (
    ExecutionRecord, MeasurementRecord, ModelResponse, SensorSample, SpanEvent,
    TaskSpec, VerifierResult,
)
from studies.energy_diagnosis.workloads.data_analysis import DataAnalysisTask, verify_answer


class IntegrationError(RuntimeError):
    """A producer returned records that cannot be safely joined."""


class RuntimeProvider(Protocol):
    def generate(self, task: TaskSpec) -> ModelResponse: ...


@dataclass(frozen=True)
class MeasurementOutcome:
    goal_end_ns: int
    samples: tuple[SensorSample, ...]
    measurements: tuple[MeasurementRecord, ...]


class MeasurementProvider(Protocol):
    session_id: str
    clock_domain: str

    def start_goal(self) -> int: ...
    def finish_goal(self) -> MeasurementOutcome: ...


def run_integrated_goal(
    *, ledger: RunLedger, plan: PlannedRun, task_spec: TaskSpec,
    verifier_task: DataAnalysisTask, runtime: RuntimeProvider,
    measurement: MeasurementProvider, artifact_root: Path,
) -> ExecutionRecord:
    """Run and durably finalize one simulated or live-compatible goal."""
    _validate_static_links(plan, task_spec, verifier_task)
    ledger.register_plan((plan,))
    goal_start_ns = measurement.start_goal()
    lease = ledger.claim_next(
        session_id=measurement.session_id, started_ns=goal_start_ns,
        clock_domain=measurement.clock_domain,
    )
    if lease is None:
        measurement.finish_goal()
        raise IntegrationError("the planned run is not available to claim")

    try:
        response = runtime.generate(task_spec)
    except BaseException as exc:
        # Preserve cleanup and available observations, but do not invent a
        # complete model outcome or termination timestamp for recovery.
        measured = measurement.finish_goal()
        artifacts = _write_artifacts(artifact_root, plan, lease.attempt_number, None, measured.samples)
        ledger.checkpoint(lease, artifacts, metadata={"runtime_exception": type(exc).__name__,
            "owned_work_termination": "unverified"})
        raise
    answer = None
    if response.status == "completed":
        try:
            answer = json.loads(response.text or "")
            verifier = VerifierResult.from_data_analysis(verify_answer(verifier_task, answer))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            verifier = VerifierResult(
                verifier_version=plan.verifier_version, outcome="fail",
                reason=f"model output is not valid verifier input: {exc}",
            )
        execution_status, execution_error = "completed", ""
    else:
        verifier = VerifierResult(
            verifier_version=plan.verifier_version, outcome="unavailable",
            reason=f"verification unavailable after model {response.status}",
        )
        execution_status = _execution_status(response.status)
        execution_error = response.error

    measured = measurement.finish_goal()
    _validate_dynamic_links(
        lease.session_id, lease.clock_domain, goal_start_ns, measured, response
    )
    span = SpanEvent(
        span_id=f"model-{lease.attempt_id}", attempt_id=lease.attempt_id,
        kind="model", ready_ns=goal_start_ns, start_ns=response.started_ns,
        end_ns=response.ended_ns,
        status="completed" if response.status == "completed" else (
            "timed_out" if response.status == "timed_out" else "failed"
        ),
        error="" if response.status == "completed" else response.error,
    )
    record = ExecutionRecord(
        goal_execution_id=lease.execution_id, planned_run_id=lease.planned_run_id,
        session_id=lease.session_id, task_id=task_spec.task_id,
        setting_id=plan.setting_id, attempt_number=lease.attempt_number,
        execution_status=execution_status, started_ns=goal_start_ns,
        ended_ns=measured.goal_end_ns, clock_domain=lease.clock_domain,
        verifier=verifier, simulated=plan.simulated, model_response=response,
        spans=(span,), measurements=measured.measurements, error=execution_error,
        notes="Simulated fixture; not hardware evidence." if plan.simulated else "",
    )
    artifacts = _write_artifacts(
        artifact_root, plan, lease.attempt_number, answer, measured.samples
    )
    ledger.finalize(lease, record, artifacts)
    return record


def _validate_static_links(plan, task_spec, verifier_task):
    comparisons = {
        "task ID": (plan.task_id, task_spec.task_id),
        "task asset": (plan.task_asset_sha256, task_spec.asset_sha256),
        "verifier version": (plan.verifier_version, task_spec.verifier_version),
        "verifier task ID": (verifier_task.task_id, task_spec.task_id),
        "verifier asset": (verifier_task.asset_sha256, task_spec.asset_sha256),
    }
    mismatches = [name for name, values in comparisons.items() if values[0] != values[1]]
    if plan.setting_id not in task_spec.eligible_settings:
        mismatches.append("eligible setting")
    if mismatches:
        raise IntegrationError(f"producer/consumer identity mismatch: {', '.join(mismatches)}")


def _validate_dynamic_links(session_id, clock_domain, start_ns, outcome, response):
    if response.clock_domain != clock_domain:
        raise IntegrationError("runtime and measurement clock domains differ")
    if not (start_ns <= response.started_ns <= response.ended_ns <= outcome.goal_end_ns):
        raise IntegrationError("runtime response lies outside the goal window")
    sample_ids = set()
    for sample in outcome.samples:
        if sample.session_id != session_id:
            raise IntegrationError("sensor sample belongs to another session")
        if sample.sample_id in sample_ids:
            raise IntegrationError("sensor sample IDs are not unique")
        sample_ids.add(sample.sample_id)
        if not (start_ns <= sample.acquired_start_ns <= sample.acquired_end_ns <= outcome.goal_end_ns):
            raise IntegrationError("sensor sample lies outside the goal window")
    for item in outcome.measurements:
        if item.session_id != session_id:
            raise IntegrationError("measurement belongs to another session")
        if item.start_ns != start_ns or item.end_ns != outcome.goal_end_ns:
            raise IntegrationError("measurement does not match the complete goal window")


def _execution_status(model_status):
    if model_status == "timed_out":
        return "timed_out"
    if model_status == "interrupted":
        return "incomplete"
    return "crashed"


def _write_artifacts(root, plan, attempt_number, answer, samples):
    relative_dir = Path("integrated") / plan.planned_run_id / f"attempt-{attempt_number}"
    destination = root / relative_dir
    destination.mkdir(parents=True, exist_ok=True)
    payloads = {
        "model-output.json": answer,
        "sensor-samples.json": [sample.to_dict() for sample in samples],
    }
    references = []
    for name, payload in payloads.items():
        content = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        path = destination / name
        path.write_text(content, encoding="utf-8", newline="\n")
        references.append(ArtifactRef(
            path=(relative_dir / name).as_posix(),
            role="model-output" if name == "model-output.json" else "raw-sensor-samples",
            sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        ))
    return tuple(references)
