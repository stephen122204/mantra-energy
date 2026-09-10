"""ED-04 fixture tests for the durable campaign execution ledger."""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from studies.energy_diagnosis.campaign import (
    ArtifactRef,
    LedgerConflictError,
    LedgerValidationError,
    PlannedRun,
    RunLedger,
)
from studies.energy_diagnosis.campaign.demo import create_demo
from studies.energy_diagnosis.contracts import (
    ExecutionRecord,
    MeasurementRecord,
    ModelResponse,
    SpanEvent,
    VerifierResult,
)


SOURCE_COMMIT = "03d078227feb7808df1950ced913ebc2a9cce188"
MODEL_SHA = "b" * 64
VERIFIER_VERSION = "fixture-verifier-v1"


def planned(number: int, *, retry_limit: int = 0) -> PlannedRun:
    return PlannedRun(
        planned_run_id=f"fixture-plan-{number:02d}",
        ordinal=number,
        task_id=f"fixture-task-{number:02d}",
        setting_id="C00",
        tool_concurrency=False,
        tool_workers=1,
        source_commit=SOURCE_COMMIT,
        task_asset_sha256=f"{number:x}" * 64,
        model_sha256=MODEL_SHA,
        verifier_version=VERIFIER_VERSION,
        verifier_sha256="c" * 64,
        retry_limit=retry_limit,
        simulated=True,
    )


def outcome(
    lease,
    plan: PlannedRun,
    *,
    execution_status: str = "completed",
    verifier_outcome: str = "pass",
    measurement_status: str = "valid",
    energy_j: float | None = 12.5,
    coverage: float | None = 1.0,
) -> ExecutionRecord:
    ended_ns = lease.started_ns + 100
    model_status = "completed" if execution_status == "completed" else "error"
    model = ModelResponse(
        request_id=f"request-{lease.attempt_number}",
        status=model_status,
        model_hash=MODEL_SHA,
        started_ns=lease.started_ns,
        ended_ns=lease.started_ns + 20,
        clock_domain=lease.clock_domain,
        text="fixture output" if model_status == "completed" else None,
        prompt_tokens=10,
        completion_tokens=5 if model_status == "completed" else None,
        token_provenance="provider",
        error="" if model_status == "completed" else "simulated model failure",
    )
    span = SpanEvent(
        span_id=f"span-{lease.execution_id}",
        attempt_id=lease.attempt_id,
        kind="model",
        ready_ns=lease.started_ns,
        start_ns=lease.started_ns,
        end_ns=lease.started_ns + 20,
        status="completed" if model_status == "completed" else "failed",
        error="" if model_status == "completed" else "simulated model failure",
    )
    measurement = MeasurementRecord(
        session_id=lease.session_id,
        domain_id="fixture-cpu-package-0",
        start_ns=lease.started_ns,
        end_ns=ended_ns,
        status=measurement_status,
        method="fixture-counter-difference",
        energy_j=energy_j,
        coverage=coverage,
        reason="" if measurement_status == "valid" else "simulated telemetry gap",
    )
    return ExecutionRecord(
        goal_execution_id=lease.execution_id,
        planned_run_id=lease.planned_run_id,
        session_id=lease.session_id,
        task_id=plan.task_id,
        setting_id=plan.setting_id,
        attempt_number=lease.attempt_number,
        execution_status=execution_status,
        started_ns=lease.started_ns,
        ended_ns=ended_ns,
        clock_domain=lease.clock_domain,
        verifier=VerifierResult(
            verifier_version=VERIFIER_VERSION,
            outcome=verifier_outcome,
            reason="fixture verifier result" if verifier_outcome != "unavailable" else "no output to verify",
        ),
        simulated=True,
        model_response=model,
        spans=(span,),
        measurements=(measurement,),
        error="" if execution_status == "completed" else "simulated model failure",
        notes="Simulated fixture; not hardware evidence.",
    )


class RunLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "ledger.sqlite3"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def claim(self, ledger: RunLedger, timestamp: int = 100):
        lease = ledger.claim_next(
            session_id="fixture-session-01",
            started_ns=timestamp,
            clock_domain="fixture-host:boot-01",
        )
        self.assertIsNotNone(lease)
        return lease

    def test_simulated_campaign_survives_restart_and_exports_every_disposition(self) -> None:
        plans = [planned(0), planned(1), planned(2), planned(3, retry_limit=1), planned(4)]
        by_id = {item.planned_run_id: item for item in plans}
        with RunLedger(self.database) as ledger:
            ledger.register_plan(plans)

            success = self.claim(ledger, 100)
            ledger.finalize(success, outcome(success, by_id[success.planned_run_id]))

            model_failure = self.claim(ledger, 300)
            ledger.finalize(
                model_failure,
                outcome(
                    model_failure,
                    by_id[model_failure.planned_run_id],
                    execution_status="crashed",
                    verifier_outcome="unavailable",
                ),
            )

            verifier_failure = self.claim(ledger, 500)
            ledger.finalize(
                verifier_failure,
                outcome(verifier_failure, by_id[verifier_failure.planned_run_id], verifier_outcome="fail"),
            )

            interrupted = self.claim(ledger, 700)

        with RunLedger(self.database) as resumed:
            recovered = resumed.recover_interrupted(session_id="fixture-session-01", clock_domain="fixture-host:boot-01", ended_ns=750, reason="simulated process interruption")
            self.assertEqual((interrupted,), recovered)

            retry = self.claim(resumed, 800)
            self.assertEqual(interrupted.planned_run_id, retry.planned_run_id)
            self.assertEqual(2, retry.attempt_number)
            self.assertNotEqual(interrupted.execution_id, retry.execution_id)
            self.assertNotEqual(interrupted.attempt_id, retry.attempt_id)
            resumed.finalize(retry, outcome(retry, by_id[retry.planned_run_id]))

            missing = self.claim(resumed, 1000)
            resumed.finalize(
                missing,
                outcome(
                    missing,
                    by_id[missing.planned_run_id],
                    measurement_status="unavailable",
                    energy_j=None,
                    coverage=None,
                ),
            )
            self.assertIsNone(resumed.claim_next(session_id="fixture-session-01", started_ns=1200, clock_domain="fixture-host:boot-01"))

            report = resumed.validate()
            self.assertTrue(report["valid"], report)
            self.assertEqual({"plans": 5, "pending": 0, "running": 0, "terminal": 5, "attempts": 6}, report["counts"])

            first = resumed.export(self.root / "export")
            bytes_before = {name: path.read_bytes() for name, path in first.items()}
            second = resumed.export(self.root / "export")
            self.assertEqual(bytes_before, {name: path.read_bytes() for name, path in second.items()})

        with (self.root / "export" / "dispositions.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(5, len(rows))
        self.assertTrue(all(row["disposition"] == "terminal" for row in rows))
        self.assertEqual("2", rows[3]["attempt_count"])
        self.assertEqual("unavailable", rows[4]["measurement_status"])
        envelopes = [json.loads(line) for line in (self.root / "export" / "attempts.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(6, len(envelopes))
        self.assertTrue(all(item["artifact_type"] == "simulated_execution_attempt" for item in envelopes))
        self.assertTrue(any(item["attempt"]["execution_record"]["execution_status"] == "incomplete" for item in envelopes))
        retry_export = next(item for item in envelopes if item["attempt"]["attempt_number"] == 2)
        self.assertEqual(interrupted.attempt_id, retry_export["attempt"]["retried_after_attempt_id"])
        self.assertIn("automatic recovery", retry_export["attempt"]["retry_reason"])
        interrupted_export = next(
            item for item in envelopes if item["attempt"]["attempt_id"] == interrupted.attempt_id
        )
        self.assertEqual("incomplete", interrupted_export["attempt"]["execution_status"])
        self.assertEqual("unavailable", interrupted_export["attempt"]["measurement_status"])
        self.assertEqual("simulated process interruption", interrupted_export["attempt"]["measurement_reason"])

    def test_plan_registration_is_idempotent_and_conflicts_are_atomic(self) -> None:
        plan = planned(1)
        with RunLedger(self.database) as ledger:
            ledger.register_plan([plan])
            ledger.register_plan([plan])
            with self.assertRaises(LedgerConflictError):
                ledger.register_plan([planned(2), replace(plan, task_id="changed-task")])
            self.assertEqual(1, ledger.validate()["counts"]["plans"])

    def test_duplicate_claim_is_prevented_across_connections(self) -> None:
        with RunLedger(self.database) as first:
            first.register_plan([planned(1)])
            lease = self.claim(first)
            with RunLedger(self.database) as second:
                self.assertIsNone(second.claim_next(session_id="fixture-session-02", started_ns=200, clock_domain="fixture-host:boot-01"))
            first.finalize(lease, outcome(lease, planned(1)))

    def test_terminal_attempt_is_immutable_and_retry_is_explicit(self) -> None:
        plan = planned(1, retry_limit=1)
        with RunLedger(self.database) as ledger:
            ledger.register_plan([plan])
            first = self.claim(ledger)
            failed = outcome(first, plan, execution_status="crashed", verifier_outcome="unavailable")
            ledger.finalize(first, failed)
            with self.assertRaises(LedgerConflictError):
                ledger.finalize(first, failed)
            ledger.schedule_retry(plan.planned_run_id, reason="fixture retry policy")
            second = self.claim(ledger, 300)
            self.assertEqual(2, second.attempt_number)
            self.assertNotEqual(first.execution_id, second.execution_id)
            ledger.finalize(second, outcome(second, plan))
            with self.assertRaises(LedgerConflictError):
                ledger.schedule_retry(plan.planned_run_id, reason="too many retries")

    def test_identity_and_model_provenance_must_match(self) -> None:
        plan = planned(1)
        with RunLedger(self.database) as ledger:
            ledger.register_plan([plan])
            lease = self.claim(ledger)
            record = outcome(lease, plan)
            with self.assertRaises(LedgerValidationError):
                ledger.finalize(lease, replace(record, task_id="wrong-task"))
            wrong_model = replace(record.model_response, model_hash="d" * 64)
            with self.assertRaises(LedgerValidationError):
                ledger.finalize(lease, replace(record, model_response=wrong_model))
            ledger.finalize(lease, record)

    def test_artifacts_are_portable_present_and_integrity_pinned(self) -> None:
        artifact_root = self.root / "artifacts"
        artifact_root.mkdir()
        result = artifact_root / "result.json"
        result.write_text('{"fixture": true}\n', encoding="utf-8")
        reference = ArtifactRef(
            path="result.json",
            role="model-output",
            sha256=hashlib.sha256(result.read_bytes()).hexdigest(),
        )
        plan = planned(1)
        with RunLedger(self.database, artifact_root=artifact_root) as ledger:
            ledger.register_plan([plan])
            lease = self.claim(ledger)
            with self.assertRaises(LedgerValidationError):
                ledger.finalize(lease, outcome(lease, plan), [replace(reference, sha256="f" * 64)])
            with self.assertRaises(LedgerValidationError):
                ledger.finalize(
                    lease,
                    outcome(lease, plan),
                    [ArtifactRef(path="missing.json", role="missing", sha256="a" * 64)],
                )
            ledger.finalize(lease, outcome(lease, plan), [reference])
            self.assertTrue(ledger.validate()["valid"])
        with self.assertRaises(LedgerValidationError):
            ArtifactRef(path="../secret.txt", role="bad", sha256="a" * 64)
        with self.assertRaises(LedgerValidationError):
            ArtifactRef(path="/secret.txt", role="bad", sha256="a" * 64)
        with self.assertRaises(LedgerValidationError):
            ArtifactRef(path="C:\\secret.txt", role="bad", sha256="a" * 64)
        with self.assertRaises(LedgerValidationError):
            ArtifactRef(path="C:/secret.txt", role="bad", sha256="a" * 64)

    def test_partial_energy_is_retained_with_coverage_and_reason(self) -> None:
        plan = planned(1)
        with RunLedger(self.database) as ledger:
            ledger.register_plan([plan])
            lease = self.claim(ledger)
            record = outcome(
                lease,
                plan,
                measurement_status="partial",
                energy_j=7.25,
                coverage=0.5,
            )
            ledger.finalize(lease, record)
            paths = ledger.export(self.root / "partial-export")
        envelope = json.loads(paths["attempts"].read_text(encoding="utf-8"))
        measurement = envelope["attempt"]["execution_record"]["measurements"][0]
        self.assertEqual("partial", measurement["status"])
        self.assertEqual(7.25, measurement["energy_j"])
        self.assertEqual(0.5, measurement["coverage"])
        self.assertEqual("simulated telemetry gap", measurement["reason"])

    def test_unsafe_measurements_are_rejected_at_ledger_boundary(self) -> None:
        cases = []
        plan = planned(1)
        with RunLedger(self.database) as ledger:
            ledger.register_plan([plan])
            lease = self.claim(ledger)
            base = outcome(lease, plan)
            measurement = base.measurements[0]
            cases.append(replace(base, measurements=(replace(measurement, energy_j=float("inf")),)))
            cases.append(replace(base, measurements=(measurement, replace(measurement, energy_j=1.0))))
            cases.append(replace(base, measurements=(replace(measurement, start_ns=lease.started_ns - 1),)))
            for unsafe in cases:
                with self.subTest(record=unsafe):
                    with self.assertRaises(LedgerValidationError):
                        ledger.finalize(lease, unsafe)
            ledger.finalize(lease, base)

    def test_simulated_plan_requires_fixture_labeled_runtime_identity(self) -> None:
        with RunLedger(self.database) as ledger:
            ledger.register_plan([planned(1)])
            with self.assertRaises(LedgerValidationError):
                ledger.claim_next(session_id="grace-a100-01", started_ns=100, clock_domain="boot-real")

    def test_packaged_demo_generates_an_inspectable_fixture_export(self) -> None:
        paths = create_demo(self.root / "demo", SOURCE_COMMIT)
        report = json.loads(paths["validation"].read_text(encoding="utf-8"))
        self.assertTrue(report["valid"], report)
        self.assertEqual(5, report["counts"]["terminal"])
        self.assertEqual(6, report["counts"]["attempts"])
        summary = paths["dispositions"].read_text(encoding="utf-8")
        self.assertIn("fixture-model-failure", summary)
        self.assertIn("fixture-missing-telemetry", summary)

    def test_next_goal_cannot_start_while_another_attempt_is_running(self) -> None:
        with RunLedger(self.database) as first:
            first.register_plan([planned(1), planned(2)])
            lease = self.claim(first)
            with RunLedger(self.database) as second:
                self.assertIsNone(second.claim_next(
                    session_id="fixture-session-02", started_ns=110,
                    clock_domain="fixture-host:boot-01",
                ))
            first.finalize(lease, outcome(lease, planned(1)))
            self.assertEqual(planned(2).planned_run_id, self.claim(first, 300).planned_run_id)

    def test_short_sensor_window_cannot_be_exported_as_full_goal_energy(self) -> None:
        with RunLedger(self.database) as ledger:
            ledger.register_plan([planned(1)])
            lease = self.claim(ledger)
            record = outcome(lease, planned(1))
            short = replace(record.measurements[0], start_ns=150, end_ns=175)
            with self.assertRaisesRegex(LedgerValidationError, "goal window"):
                ledger.finalize(lease, replace(record, measurements=(short,)))
            ledger.finalize(lease, record)

    def test_model_clock_and_window_must_match_the_goal(self) -> None:
        with RunLedger(self.database) as ledger:
            ledger.register_plan([planned(1)])
            lease = self.claim(ledger)
            record = outcome(lease, planned(1))
            for response in (
                replace(record.model_response, clock_domain="fixture-other-host:boot-02"),
                replace(record.model_response, ended_ns=record.ended_ns + 1),
            ):
                with self.subTest(response=response):
                    with self.assertRaises(LedgerValidationError):
                        ledger.finalize(lease, replace(record, model_response=response))
            ledger.finalize(lease, record)

    def test_export_preserves_full_unattempted_plan_and_pending_retry(self) -> None:
        plan = planned(1, retry_limit=1)
        with RunLedger(self.database) as ledger:
            ledger.register_plan([plan, planned(2)])
            lease = self.claim(ledger)
            ledger.finalize(lease, outcome(lease, plan, execution_status="crashed", verifier_outcome="unavailable"))
            ledger.schedule_retry(plan.planned_run_id, reason="retry after transient failure")
            paths = ledger.export(self.root / "pending-export")
        self.assertIn("plans", paths)
        plans = [json.loads(line) for line in paths["plans"].read_text(encoding="utf-8").splitlines()]
        self.assertEqual(planned(2).to_dict(), plans[1]["plan"])
        self.assertEqual("pending", plans[1]["disposition"])
        self.assertEqual(lease.attempt_id, plans[0]["retry_requests"][0]["after_attempt_id"])
        self.assertEqual("retry after transient failure", plans[0]["retry_requests"][0]["reason"])

    def test_recovery_is_scoped_and_rejects_a_different_boot_clock(self) -> None:
        with RunLedger(self.database) as ledger:
            ledger.register_plan([planned(1, retry_limit=1)])
            lease = self.claim(ledger)
        with RunLedger(self.database) as ledger:
            self.assertEqual((), ledger.recover_interrupted(
                session_id="fixture-unrelated-session", clock_domain=lease.clock_domain,
                ended_ns=150, reason="unrelated recovery",
            ))
            with self.assertRaisesRegex(LedgerValidationError, "clock_domain"):
                ledger.recover_interrupted(
                    session_id=lease.session_id, clock_domain="fixture-host:boot-02",
                    ended_ns=1000, reason="reboot with a different monotonic clock",
                )
            self.assertEqual(1, ledger.validate()["counts"]["running"])
            self.assertEqual((lease,), ledger.recover_interrupted(
                session_id=lease.session_id, clock_domain=lease.clock_domain,
                ended_ns=150, reason="retained original-clock termination endpoint",
            ))
            paths = ledger.export(self.root / "recovered")
            row = json.loads(paths["attempts"].read_text(encoding="utf-8"))
            self.assertEqual(150, row["attempt"]["ended_ns"])
            self.assertEqual("incomplete", row["attempt"]["execution_status"])
            self.assertEqual("unavailable", row["attempt"]["measurement_status"])


if __name__ == "__main__":
    unittest.main()
