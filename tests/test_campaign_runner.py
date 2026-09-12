"""NI2 fixture tests for deterministic, bounded campaign execution."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from studies.energy_diagnosis.campaign import (
    ArtifactRef,
    BoundedCampaignRunner,
    CampaignSchedule,
    ExecutionOutcome,
    LedgerValidationError,
    OutcomeMetadata,
    PlannedRun,
    RunLedger,
    ScheduleBlock,
)
from studies.energy_diagnosis.contracts import ExecutionRecord, MeasurementRecord, VerifierResult


SOURCE_COMMIT = "d4f8616443651bb81f15da46f7720a4027d6987d"
SHA = "a" * 64


def plan(number: int, *, retry_limit: int = 0) -> PlannedRun:
    return PlannedRun(
        planned_run_id=f"fixture-plan-{number}", ordinal=number, task_id=f"task-{number}",
        setting_id=f"C{number % 2:02d}", tool_concurrency=bool(number % 2), tool_workers=number % 2 + 1,
        source_commit=SOURCE_COMMIT, task_asset_sha256=SHA, model_sha256="b" * 64,
        verifier_version="fixture-verifier-v1", verifier_sha256="c" * 64,
        retry_limit=retry_limit, simulated=True,
    )


def schedule(*blocks: tuple[str, tuple[PlannedRun, ...]], seed: int = 7) -> CampaignSchedule:
    return CampaignSchedule.build(
        [ScheduleBlock(block_id=name, session_slot=f"slot-{name}", preparation_sha256=SHA, runs=runs)
         for name, runs in blocks],
        seed=seed,
    )


def result(request, *, status: str = "completed", verifier: str = "pass", measurement: str = "valid",
           actual_setting: str | None = None, preparation: str = SHA, owned: bool = True,
           overlap: tuple[tuple[str, str], ...] = (), sensor_gaps: tuple[str, ...] = (),
           artifact: ArtifactRef | None = None) -> ExecutionOutcome:
    lease = request.lease
    planned = request.scheduled_run.planned_run
    energy = 2.5 if measurement in {"valid", "partial"} else None
    coverage = 1.0 if measurement == "valid" else (0.5 if measurement == "partial" else None)
    record = ExecutionRecord(
        goal_execution_id=lease.execution_id, planned_run_id=lease.planned_run_id,
        session_id=lease.session_id, task_id=planned.task_id, setting_id=planned.setting_id,
        attempt_number=lease.attempt_number, execution_status=status,
        started_ns=lease.started_ns, ended_ns=lease.started_ns + 100, clock_domain=lease.clock_domain,
        verifier=VerifierResult(
            verifier_version=planned.verifier_version, outcome=verifier,
            reason="fixture verifier result",
        ),
        simulated=True,
        measurements=(MeasurementRecord(
            session_id=lease.session_id, domain_id="fixture-cpu", start_ns=lease.started_ns,
            end_ns=lease.started_ns + 100, status=measurement, method="fixture-counter",
            energy_j=energy, coverage=coverage,
            reason="" if measurement == "valid" else "fixture sensor gap",
        ),),
        error="" if status == "completed" else "expected fixture model failure",
        notes="Fixture evidence only; no model, Grace, or hardware execution.",
    )
    metadata = OutcomeMetadata(
        actual_setting_id=actual_setting or planned.setting_id,
        actual_tool_concurrency=planned.tool_concurrency,
        actual_tool_workers=planned.tool_workers,
        actual_preparation_sha256=preparation,
        observed_resources=(("host", "fixture-host"),),
        owned_work_terminated=owned,
        fidelity_status="eligible",
        sensor_gaps=sensor_gaps,
        overlapping_domains=overlap,
        cost_seconds=(("wall", 0.1),),
    )
    return ExecutionOutcome(record=record, artifacts=(artifact,) if artifact else (), metadata=metadata)


class CampaignRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_runner(self, campaign: CampaignSchedule, *, artifact_root: Path | None = None):
        ledger = RunLedger(self.root / "ledger.sqlite3", artifact_root=artifact_root)
        return ledger, BoundedCampaignRunner(ledger, campaign, self.root / "state")

    def test_seeded_order_is_deterministic_and_never_crosses_blocks(self) -> None:
        blocks = (("a", tuple(plan(i) for i in range(5))), ("b", tuple(plan(i) for i in range(5, 10))))
        first = schedule(*blocks, seed=41)
        same = schedule(*blocks, seed=41)
        different = schedule(*blocks, seed=42)
        first_ids = [entry.planned_run.planned_run_id for entry in first.entries]
        self.assertEqual(first_ids, [entry.planned_run.planned_run_id for entry in same.entries])
        self.assertNotEqual(first_ids, [entry.planned_run.planned_run_id for entry in different.entries])
        self.assertTrue(all(entry.block_id == "a" for entry in first.entries[:5]))
        self.assertTrue(all(entry.block_id == "b" for entry in first.entries[5:]))
        self.assertEqual(list(range(1, 11)), [entry.declared_order for entry in first.entries])

    def test_actual_order_metadata_failures_and_complete_dispositions_are_exported(self) -> None:
        campaign = schedule(("a", (plan(0), plan(1), plan(2))))
        ledger, runner = self.make_runner(campaign)
        try:
            invocations = 0

            def executor(request):
                nonlocal invocations
                invocations += 1
                if invocations == 2:
                    return result(request, status="crashed", verifier="unavailable", measurement="unavailable")
                return result(request)

            first = runner.run_next(session_id="fixture-session", started_ns=100, clock_domain="fixture-clock", executor=executor,
                                    requested_resources={"allocation": "fixture"})
            second = runner.run_next(session_id="fixture-session", started_ns=300, clock_domain="fixture-clock", executor=executor)
            third = runner.run_next(session_id="fixture-session", started_ns=500, clock_domain="fixture-clock", executor=executor)
            self.assertEqual([1, 2, 3], [first.actual_order, second.actual_order, third.actual_order])
            self.assertIsNone(runner.run_next(session_id="fixture-session", started_ns=700, clock_domain="fixture-clock", executor=executor))
            paths = runner.export(self.root / "export")
            first_bytes = {name: path.read_bytes() for name, path in paths.items()}
            self.assertEqual(first_bytes, {name: path.read_bytes() for name, path in runner.export(self.root / "export").items()})
            report = json.loads(paths["campaign_validation"].read_text(encoding="utf-8"))
            self.assertTrue(report["valid"], report)
            self.assertEqual(3, report["counts"]["terminal"])
            self.assertEqual(3, len(report["dispositions"]))
            self.assertEqual([True, False, True], [item["analysis_eligible"] for item in report["observations"]])
            first_export = json.loads(paths["attempts"].read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual("fixture", first_export["attempt"]["claim_metadata"]["requested_resources"]["allocation"])
            second_export = json.loads(paths["attempts"].read_text(encoding="utf-8").splitlines()[1])
            self.assertEqual("expected fixture model failure", second_export["attempt"]["outcome_metadata"]["failure_reason"])
        finally:
            ledger.close()

    def test_crash_blocks_new_work_until_scoped_recovery_then_retry(self) -> None:
        campaign = schedule(("a", (plan(0, retry_limit=1), plan(1, retry_limit=1))))
        artifact_root = self.root / "artifacts"
        artifact_root.mkdir()
        partial = artifact_root / "partial.json"
        partial.write_text("partial fixture observation", encoding="utf-8")
        partial_ref = ArtifactRef(
            path="partial.json", role="partial-executor-output",
            sha256=hashlib.sha256(partial.read_bytes()).hexdigest(),
        )
        ledger, runner = self.make_runner(campaign, artifact_root=artifact_root)
        try:
            def crash(request):
                request.checkpoint((partial_ref,), {"phase": "model-response-received"})
                raise RuntimeError("fixture executor disappeared")

            with self.assertRaises(RuntimeError):
                runner.run_next(session_id="fixture-session", started_ns=100, clock_domain="fixture-boot-a", executor=crash)
            self.assertIsNone(runner.run_next(session_id="fixture-session", started_ns=200, clock_domain="fixture-boot-b", executor=result))
            with self.assertRaises(LedgerValidationError):
                runner.recover_interrupted(session_id="fixture-session", clock_domain="fixture-boot-b", ended_ns=250, reason="reboot")
            unresolved = runner.record_unknown_interruption(
                session_id="fixture-session", reason="restart cannot provide the original clock endpoint"
            )
            self.assertEqual(1, len(unresolved))
            self.assertEqual(1, ledger.validate()["counts"]["running"])
            recovered = runner.recover_interrupted(
                session_id="fixture-session", clock_domain="fixture-boot-a", ended_ns=180,
                reason="owned fixture process termination confirmed",
            )
            retry = runner.run_next(session_id="fixture-session", started_ns=300, clock_domain="fixture-boot-b", executor=result)
            self.assertEqual(recovered[0].planned_run_id, retry.planned_run_id)
            self.assertEqual(2, retry.attempt_number)
            self.assertEqual(2, retry.actual_order)
            attempts = [json.loads(line) for line in runner.export(self.root / "export")["attempts"].read_text(encoding="utf-8").splitlines()]
            self.assertEqual("incomplete", attempts[0]["attempt"]["execution_status"])
            self.assertTrue(attempts[0]["attempt"]["outcome_metadata"]["recovery"]["termination_endpoint_known"])
            self.assertEqual("partial.json", attempts[0]["attempt"]["artifacts"][0]["path"])
            self.assertEqual("model-response-received", attempts[0]["attempt"]["checkpoints"][0]["metadata"]["phase"])
            unknown = attempts[0]["attempt"]["checkpoints"][1]["metadata"]["interruption"]
            self.assertFalse(unknown["termination_endpoint_known"])
        finally:
            ledger.close()

    def test_observed_mismatches_overlap_and_partial_data_are_preserved_and_flagged(self) -> None:
        campaign = schedule(("a", (plan(0),)))
        ledger, runner = self.make_runner(campaign)
        try:
            runner.run_next(
                session_id="fixture-session", started_ns=100, clock_domain="fixture-clock",
                executor=lambda request: result(
                    request, measurement="partial", actual_setting="C99", preparation="d" * 64,
                    overlap=(("fixture-cpu", "fixture-gpu"),), sensor_gaps=("sample-2 missing",),
                ),
            )
            paths = runner.export(self.root / "export")
            report = json.loads(paths["campaign_validation"].read_text(encoding="utf-8"))
            self.assertFalse(report["valid"])
            self.assertTrue(any("actual setting differs" in error for error in report["errors"]))
            self.assertTrue(any("actual preparation differs" in error for error in report["errors"]))
            self.assertTrue(any("overlapping measurement domains" in error for error in report["errors"]))
            self.assertIn("measurement partial", report["observations"][0]["exclusion_reasons"])
            envelope = json.loads(paths["attempts"].read_text(encoding="utf-8"))
            measurement = envelope["attempt"]["execution_record"]["measurements"][0]
            self.assertEqual(2.5, measurement["energy_j"])
            self.assertEqual(0.5, measurement["coverage"])
        finally:
            ledger.close()

    def test_runner_refuses_finalization_while_owned_work_survives(self) -> None:
        campaign = schedule(("a", (plan(0), plan(1))))
        ledger, runner = self.make_runner(campaign)
        try:
            with self.assertRaises(LedgerValidationError):
                runner.run_next(
                    session_id="fixture-session", started_ns=100, clock_domain="fixture-clock",
                    executor=lambda request: result(request, owned=False),
                )
            self.assertEqual(1, ledger.validate()["counts"]["running"])
            self.assertIsNone(runner.run_next(
                session_id="fixture-session", started_ns=300, clock_domain="fixture-clock", executor=result
            ))
        finally:
            ledger.close()

    def test_same_clock_timestamps_cannot_report_overlapping_goals(self) -> None:
        campaign = schedule(("a", (plan(0), plan(1))))
        ledger, runner = self.make_runner(campaign)
        try:
            runner.run_next(
                session_id="fixture-session", started_ns=100, clock_domain="fixture-clock", executor=result
            )
            with self.assertRaisesRegex(LedgerValidationError, "overlaps"):
                runner.run_next(
                    session_id="fixture-session", started_ns=150, clock_domain="fixture-clock", executor=result
                )
            self.assertEqual(0, ledger.validate()["counts"]["running"])
        finally:
            ledger.close()

    def test_schedule_conflict_and_post_finalize_artifact_corruption_are_diagnosed(self) -> None:
        artifact_root = self.root / "artifacts"
        artifact_root.mkdir()
        artifact = artifact_root / "raw.json"
        artifact.write_text("fixture", encoding="utf-8")
        reference = ArtifactRef(path="raw.json", role="raw-executor-output", sha256=hashlib.sha256(artifact.read_bytes()).hexdigest())
        campaign = schedule(("a", (plan(0),)))
        ledger, runner = self.make_runner(campaign, artifact_root=artifact_root)
        try:
            runner.run_next(session_id="fixture-session", started_ns=100, clock_domain="fixture-clock",
                            executor=lambda request: result(request, artifact=reference))
            artifact.write_text("corrupt", encoding="utf-8")
            report = json.loads(runner.export(self.root / "export")["campaign_validation"].read_text(encoding="utf-8"))
            self.assertFalse(report["valid"])
            self.assertTrue(any("artifact hash mismatch" in error for error in report["errors"]))
            artifact.unlink()
            missing = json.loads(runner.export(self.root / "missing-export")["campaign_validation"].read_text(encoding="utf-8"))
            self.assertTrue(any("artifact does not exist" in error for error in missing["errors"]))
        finally:
            ledger.close()
        with RunLedger(self.root / "ledger.sqlite3", artifact_root=artifact_root) as reopened:
            with self.assertRaises(LedgerValidationError):
                BoundedCampaignRunner(reopened, schedule(("a", (plan(0),)), seed=8), self.root / "state")


if __name__ == "__main__":
    unittest.main()
