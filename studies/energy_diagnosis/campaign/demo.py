"""Generate a tiny simulated ED-04 ledger and portable export.

This module never invokes a model, tool, collector, or hardware interface.  Its
outputs are fixture evidence only.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from studies.energy_diagnosis.campaign.ledger import ArtifactRef, PlannedRun, RunLedger
from studies.energy_diagnosis.contracts import ExecutionRecord, MeasurementRecord, ModelResponse, VerifierResult


MODEL_SHA256 = "b" * 64
VERIFIER_SHA256 = "c" * 64
VERIFIER_VERSION = "fixture-verifier-v1"


def make_demo_plan(source_commit: str) -> tuple[PlannedRun, ...]:
    """Return five fixture slots covering ED-04's required dispositions."""
    labels = ("success", "model-failure", "verifier-failure", "interruption", "missing-telemetry")
    return tuple(
        PlannedRun(
            planned_run_id=f"fixture-{label}",
            ordinal=index,
            task_id=f"fixture-task-{label}",
            setting_id="C00",
            tool_concurrency=False,
            tool_workers=1,
            source_commit=source_commit,
            task_asset_sha256=f"{index + 1:x}" * 64,
            model_sha256=MODEL_SHA256,
            verifier_version=VERIFIER_VERSION,
            verifier_sha256=VERIFIER_SHA256,
            retry_limit=1 if label == "interruption" else 0,
            simulated=True,
        )
        for index, label in enumerate(labels)
    )


def _record(
    lease,
    plan: PlannedRun,
    *,
    execution_status: str = "completed",
    verifier_outcome: str = "pass",
    measurement_status: str = "valid",
) -> ExecutionRecord:
    model_status = "error" if execution_status == "crashed" else "completed"
    energy_j = None if measurement_status == "unavailable" else 12.5
    return ExecutionRecord(
        goal_execution_id=lease.execution_id,
        planned_run_id=lease.planned_run_id,
        session_id=lease.session_id,
        task_id=plan.task_id,
        setting_id=plan.setting_id,
        attempt_number=lease.attempt_number,
        execution_status=execution_status,
        started_ns=lease.started_ns,
        ended_ns=lease.started_ns + 100,
        clock_domain=lease.clock_domain,
        verifier=VerifierResult(
            verifier_version=VERIFIER_VERSION,
            outcome=verifier_outcome,
            reason="simulated verifier result" if verifier_outcome != "unavailable" else "no output to verify",
        ),
        simulated=True,
        model_response=ModelResponse(
            request_id=f"fixture-request-{lease.execution_id}",
            status=model_status,
            model_hash=MODEL_SHA256,
            started_ns=lease.started_ns,
            ended_ns=lease.started_ns + 20,
            clock_domain=lease.clock_domain,
            text="simulated output" if model_status == "completed" else None,
            prompt_tokens=10,
            completion_tokens=5 if model_status == "completed" else None,
            token_provenance="provider",
            error="" if model_status == "completed" else "simulated model failure",
        ),
        measurements=(
            MeasurementRecord(
                session_id=lease.session_id,
                domain_id="fixture-cpu-package-0",
                start_ns=lease.started_ns,
                end_ns=lease.started_ns + 100,
                status=measurement_status,
                method="fixture-counter-difference",
                energy_j=energy_j,
                coverage=1.0 if measurement_status == "valid" else None,
                reason="" if measurement_status == "valid" else "simulated telemetry unavailable",
            ),
        ),
        error="" if execution_status == "completed" else "simulated model failure",
        notes="Simulated fixture; not model, Grace, or hardware evidence.",
    )


def create_demo(output_dir: Path, source_commit: str) -> dict[str, Path]:
    """Create the fixture ledger and return its export paths."""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    database = output_dir / "fixture-ledger.sqlite3"
    if database.exists():
        raise FileExistsError(f"refusing to overwrite existing demo ledger: {database}")
    artifact_root = output_dir / "artifacts"
    artifact_root.mkdir()
    result_artifact = artifact_root / "verified-result.json"
    result_artifact.write_text('{"fixture":true,"verified":true}\n', encoding="utf-8", newline="\n")
    artifact = ArtifactRef(
        path="verified-result.json",
        role="verified-output",
        sha256=hashlib.sha256(result_artifact.read_bytes()).hexdigest(),
    )
    plans = make_demo_plan(source_commit)
    by_id = {plan.planned_run_id: plan for plan in plans}

    with RunLedger(database, artifact_root=artifact_root) as ledger:
        ledger.register_plan(plans)
        success = ledger.claim_next(session_id="fixture-session-demo", started_ns=100, clock_domain="fixture-host:boot-demo")
        assert success is not None
        ledger.finalize(success, _record(success, by_id[success.planned_run_id]), [artifact])

        model_failure = ledger.claim_next(session_id="fixture-session-demo", started_ns=300, clock_domain="fixture-host:boot-demo")
        assert model_failure is not None
        ledger.finalize(
            model_failure,
            _record(model_failure, by_id[model_failure.planned_run_id], execution_status="crashed", verifier_outcome="unavailable"),
        )

        verifier_failure = ledger.claim_next(session_id="fixture-session-demo", started_ns=500, clock_domain="fixture-host:boot-demo")
        assert verifier_failure is not None
        ledger.finalize(
            verifier_failure,
            _record(verifier_failure, by_id[verifier_failure.planned_run_id], verifier_outcome="fail"),
        )

        interrupted = ledger.claim_next(session_id="fixture-session-demo", started_ns=700, clock_domain="fixture-host:boot-demo")
        assert interrupted is not None

    with RunLedger(database, artifact_root=artifact_root) as ledger:
        ledger.recover_interrupted(session_id="fixture-session-demo", clock_domain="fixture-host:boot-demo", ended_ns=750, reason="simulated process interruption")
        retry = ledger.claim_next(session_id="fixture-session-demo", started_ns=800, clock_domain="fixture-host:boot-demo")
        assert retry is not None and retry.planned_run_id == interrupted.planned_run_id
        ledger.finalize(retry, _record(retry, by_id[retry.planned_run_id]))

        missing = ledger.claim_next(session_id="fixture-session-demo", started_ns=1000, clock_domain="fixture-host:boot-demo")
        assert missing is not None
        ledger.finalize(
            missing,
            _record(missing, by_id[missing.planned_run_id], measurement_status="unavailable"),
        )
        return ledger.export(output_dir / "export")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-commit", required=True, help="Exact 40-character lowercase Git commit")
    arguments = parser.parse_args()
    paths = create_demo(arguments.out, arguments.source_commit)
    for name, path in paths.items():
        print(f"{name}: {path}")
    print("Evidence level: simulated fixture only; no model, Grace, or hardware measurement ran.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
