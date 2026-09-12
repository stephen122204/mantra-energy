"""AX4 producer/consumer integration tests; all providers are simulated."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from studies.energy_diagnosis.campaign import PlannedRun, RunLedger
from studies.energy_diagnosis.contracts import MeasurementRecord, ModelResponse, SensorSample, TaskSpec
from studies.energy_diagnosis.integration import IntegrationError, MeasurementOutcome, run_integrated_goal
from studies.energy_diagnosis.workloads.data_analysis import load_default_task


SOURCE_COMMIT = "18d712d78801169ff74527dbc6a8d85fda31cfc5"
MODEL_HASH = "a" * 64
VERIFIER_HASH = hashlib.sha256(
    Path("studies/energy_diagnosis/workloads/data_analysis.py").read_bytes()
).hexdigest()


def task_spec():
    task = load_default_task()
    raw = json.loads(Path("studies/energy_diagnosis/workloads/task.json").read_text(encoding="utf-8"))
    return TaskSpec(
        task_id=task.task_id, family="data-analysis", split="development",
        asset_sha256=task.asset_sha256,
        expected_result_sha256=task.expected_result_sha256,
        verifier_version=task.verifier_version, prompt=raw["prompt"],
        deadline_s=30, retry_limit=0, eligible_settings=("C00",),
        lineage="merged ED-03 fixture",
    )


def plan(number=1):
    spec = task_spec()
    return PlannedRun(
        planned_run_id=f"fixture-ax4-{number}", ordinal=number,
        task_id=spec.task_id, setting_id="C00", tool_concurrency=False,
        tool_workers=1, source_commit=SOURCE_COMMIT,
        task_asset_sha256=spec.asset_sha256, model_sha256=MODEL_HASH,
        verifier_version=spec.verifier_version, verifier_sha256=VERIFIER_HASH,
        simulated=True,
    )


def correct_answer():
    task = load_default_task()
    expected = json.loads(task.expected_result_path.read_text(encoding="utf-8"))
    total = expected["grand_total"]
    return {
        "region_totals": expected["region_totals"],
        "product_totals": expected["product_totals"],
        "reconciliation": {"region_total": total, "product_total": total, "difference": 0},
        "evidence": [task.asset_sha256],
    }


@dataclass
class Runtime:
    status: str = "completed"
    answer: dict | None = None

    def generate(self, spec):
        return ModelResponse(
            request_id="fixture-request-001", status=self.status,
            model_hash=MODEL_HASH, started_ns=110, ended_ns=140,
            clock_domain="fixture-host:boot-1",
            text=json.dumps(self.answer or correct_answer(), sort_keys=True) if self.status == "completed" else None,
            prompt_tokens=23, completion_tokens=41 if self.status == "completed" else 7,
            token_provenance="provider",
            error="" if self.status == "completed" else "fixture runtime failed after partial output",
        )


class Measurement:
    session_id = "fixture-session-ax4"
    clock_domain = "fixture-host:boot-1"

    def __init__(self, unavailable=False):
        self.unavailable = unavailable

    def start_goal(self):
        return 100

    def finish_goal(self):
        status = "unavailable" if self.unavailable else "valid"
        samples, measurements = [], []
        for domain, energy in (("cpu-package-0", 0.25), ("gpu-board-0", 0.75)):
            samples.append(SensorSample(
                sample_id=f"fixture-{domain}", session_id=self.session_id,
                domain_id=domain, acquired_start_ns=145, acquired_end_ns=150,
                unit="microjoules", status="missing" if self.unavailable else "ok",
                value=None if self.unavailable else energy * 1_000_000,
                reason="fixture sensor unavailable" if self.unavailable else "",
            ))
            measurements.append(MeasurementRecord(
                session_id=self.session_id, domain_id=domain,
                start_ns=100, end_ns=160, status=status,
                method="fixture-counter-difference",
                energy_j=None if self.unavailable else energy,
                coverage=None if self.unavailable else 1.0,
                reason="fixture sensor unavailable" if self.unavailable else "",
            ))
        return MeasurementOutcome(160, tuple(samples), tuple(measurements))


class IntegratedGoalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def execute(self, *, number=1, runtime=None, measurement=None):
        with RunLedger(self.root / f"ledger-{number}.sqlite3", artifact_root=self.root) as ledger:
            record = run_integrated_goal(
                ledger=ledger, plan=plan(number), task_spec=task_spec(),
                verifier_task=load_default_task(), runtime=runtime or Runtime(),
                measurement=measurement or Measurement(), artifact_root=self.root,
            )
            report = ledger.validate()
            first = ledger.export(self.root / f"export-{number}")
            before = {key: path.read_bytes() for key, path in first.items()}
            second = ledger.export(self.root / f"export-{number}")
            after = {key: path.read_bytes() for key, path in second.items()}
        return record, report, before, after

    def test_success_traverses_all_merged_interfaces(self):
        record, report, first, second = self.execute()
        self.assertTrue(record.verified)
        self.assertEqual(record.model_response.request_id, "fixture-request-001")
        self.assertEqual(record.model_response.prompt_tokens, 23)
        self.assertEqual(record.model_response.token_provenance, "provider")
        self.assertEqual((record.started_ns, record.ended_ns), (100, 160))
        self.assertTrue(all(m.start_ns == 100 and m.end_ns == 160 for m in record.measurements))
        self.assertTrue(report["valid"], report)
        self.assertEqual(first, second)
        envelope = json.loads(first["attempts"].decode().splitlines()[0])
        roles = {item["role"] for item in envelope["attempt"]["artifacts"]}
        self.assertEqual(roles, {"model-output", "raw-sensor-samples"})
        self.assertEqual(
            envelope["attempt"]["execution_record"]["model_response"]["request_id"],
            "fixture-request-001",
        )

    def test_failed_runtime_retains_partial_metadata(self):
        record, report, _, _ = self.execute(number=2, runtime=Runtime(status="error"))
        self.assertEqual(record.execution_status, "crashed")
        self.assertEqual(record.verifier.outcome, "unavailable")
        self.assertEqual(record.model_response.completion_tokens, 7)
        self.assertIn("partial output", record.error)
        self.assertTrue(report["valid"], report)

    def test_wrong_output_is_completed_but_not_verified(self):
        wrong = correct_answer()
        wrong["region_totals"]["North"] += 1
        record, report, _, _ = self.execute(
            number=4, runtime=Runtime(answer=wrong)
        )
        self.assertEqual(record.execution_status, "completed")
        self.assertEqual(record.verifier.outcome, "fail")
        self.assertFalse(record.verified)
        self.assertTrue(report["valid"], report)

    def test_missing_cpu_and_gpu_energy_are_null_with_reasons(self):
        record, report, _, _ = self.execute(number=3, measurement=Measurement(True))
        self.assertTrue(record.verified)
        self.assertEqual({m.domain_id for m in record.measurements}, {"cpu-package-0", "gpu-board-0"})
        self.assertTrue(all(m.status == "unavailable" and m.energy_j is None and m.reason for m in record.measurements))
        self.assertTrue(report["valid"], report)

    def test_identity_mismatch_is_rejected_before_claim(self):
        bad = TaskSpec.from_dict({**task_spec().to_dict(), "task_id": "wrong-task"})
        with RunLedger(self.root / "mismatch.sqlite3", artifact_root=self.root) as ledger:
            with self.assertRaisesRegex(IntegrationError, "identity mismatch"):
                run_integrated_goal(
                    ledger=ledger, plan=plan(5), task_spec=bad,
                    verifier_task=load_default_task(), runtime=Runtime(),
                    measurement=Measurement(), artifact_root=self.root,
                )
            self.assertEqual(ledger.validate()["counts"]["attempts"], 0)

    def test_runtime_outside_goal_clock_is_rejected(self):
        class EarlyRuntime(Runtime):
            def generate(self, spec):
                return ModelResponse.from_dict({**super().generate(spec).to_dict(), "started_ns": 90})
        with RunLedger(self.root / "clock.sqlite3", artifact_root=self.root) as ledger:
            with self.assertRaisesRegex(IntegrationError, "outside the goal window"):
                run_integrated_goal(
                    ledger=ledger, plan=plan(6), task_spec=task_spec(),
                    verifier_task=load_default_task(), runtime=EarlyRuntime(),
                    measurement=Measurement(), artifact_root=self.root,
                )


if __name__ == "__main__":
    unittest.main()
