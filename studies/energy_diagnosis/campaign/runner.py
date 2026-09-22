"""Deterministic, one-goal-at-a-time campaign scheduling over :mod:`ledger`.

This module owns orchestration metadata, not model or measurement mechanics.
An injected executor performs one claimed goal and returns the contract-v0.1
record plus durable artifact references.  Unexpected executor exits deliberately
leave the claim running so recovery requires a proven termination endpoint.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

from studies.energy_diagnosis.contracts import ExecutionRecord

from .ledger import ArtifactRef, AttemptLease, LedgerValidationError, PlannedRun, RunLedger


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LedgerValidationError(message)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise LedgerValidationError(f"value is not strict JSON: {error}") from error


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ScheduleBlock:
    """Runs that may be shuffled together without crossing preparation blocks."""

    block_id: str
    session_slot: str
    preparation_sha256: str
    runs: tuple[PlannedRun, ...]

    def __post_init__(self) -> None:
        _require(isinstance(self.block_id, str) and bool(self.block_id.strip()), "block_id must be non-empty")
        _require(isinstance(self.session_slot, str) and bool(self.session_slot.strip()), "session_slot must be non-empty")
        _require(isinstance(self.preparation_sha256, str) and len(self.preparation_sha256) == 64, "preparation_sha256 must be a SHA-256 digest")
        _require(all(c in "0123456789abcdef" for c in self.preparation_sha256), "preparation_sha256 must be lowercase hexadecimal")
        _require(bool(self.runs), "schedule block must contain at least one run")


@dataclass(frozen=True)
class ScheduledRun:
    planned_run: PlannedRun
    block_id: str
    session_slot: str
    block_order: int
    declared_order: int
    preparation_sha256: str

    def __post_init__(self) -> None:
        _require(isinstance(self.block_id, str) and bool(self.block_id.strip()), "block_id must be non-empty")
        _require(isinstance(self.session_slot, str) and bool(self.session_slot.strip()), "session_slot must be non-empty")
        for name in ("block_order", "declared_order"):
            value = getattr(self, name)
            _require(isinstance(value, int) and not isinstance(value, bool) and value >= 1, f"{name} must be positive")
        _require(
            isinstance(self.preparation_sha256, str) and len(self.preparation_sha256) == 64
            and all(c in "0123456789abcdef" for c in self.preparation_sha256),
            "preparation_sha256 must be a lowercase SHA-256 digest",
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["planned_run"] = self.planned_run.to_dict()
        return value


@dataclass(frozen=True)
class CampaignSchedule:
    schedule_id: str
    seed: int
    entries: tuple[ScheduledRun, ...]

    def __post_init__(self) -> None:
        _require(isinstance(self.seed, int) and not isinstance(self.seed, bool), "seed must be an integer")
        _require(bool(self.entries), "schedule must contain at least one entry")
        identifiers = [entry.planned_run.planned_run_id for entry in self.entries]
        _require(len(identifiers) == len(set(identifiers)), "schedule planned_run_id values must be unique")
        _require(
            [entry.declared_order for entry in self.entries] == list(range(1, len(self.entries) + 1)),
            "schedule declared_order values must be contiguous",
        )
        _require(
            [entry.planned_run.ordinal for entry in self.entries] == list(range(1, len(self.entries) + 1)),
            "scheduled plan ordinals must match declared order",
        )
        payload = {"seed": self.seed, "entries": [entry.to_dict() for entry in self.entries]}
        _require(
            self.schedule_id == f"schedule-{_digest(_canonical_json(payload))}",
            "schedule_id does not match the immutable schedule payload",
        )

    @classmethod
    def build(cls, blocks: Iterable[ScheduleBlock], *, seed: int, balanced_pairs: bool = False) -> "CampaignSchedule":
        _require(isinstance(seed, int) and not isinstance(seed, bool), "seed must be an integer")
        block_list = tuple(blocks)
        _require(bool(block_list), "schedule must contain at least one block")
        _require(type(balanced_pairs) is bool, "balanced_pairs must be boolean")
        pair_keys = {}
        pair_counts = {}
        if balanced_pairs:
            for block in block_list:
                _require(len(block.runs) == 2, "balanced order requires two settings per block")
                left, right = block.runs
                _require(left.task_id == right.task_id and left.setting_id != right.setting_id,
                         "balanced pairs require the same task and distinct settings")
                identity = (left.task_id, tuple(sorted(r.setting_id for r in block.runs)),
                            block.session_slot, block.preparation_sha256,
                            left.task_asset_sha256, left.model_sha256,
                            left.verifier_version, left.verifier_sha256, left.source_commit, left.simulated)
                _require((left.task_asset_sha256, left.model_sha256, left.verifier_version, left.verifier_sha256, left.source_commit, left.simulated)
                         == (right.task_asset_sha256, right.model_sha256, right.verifier_version, right.verifier_sha256, right.source_commit, right.simulated),
                         "balanced pair inputs/model/verifier differ")
                pair_keys[block.block_id] = identity
                pair_counts[identity] = pair_counts.get(identity, 0) + 1
            _require(all(n % 2 == 0 for n in pair_counts.values()),
                     "balanced order requires an even number of pairs for each task/configuration")
        pair_seen = {}
        seen_blocks: set[str] = set()
        seen_runs: set[str] = set()
        entries: list[ScheduledRun] = []
        for block in block_list:
            _require(block.block_id not in seen_blocks, f"duplicate block_id: {block.block_id}")
            seen_blocks.add(block.block_id)
            runs = list(block.runs)
            block_seed = int.from_bytes(
                hashlib.sha256(f"{seed}\0{block.block_id}".encode("utf-8")).digest()[:8], "big"
            )
            if balanced_pairs:
                key = pair_keys[block.block_id]
                occurrence = pair_seen.get(key, 0)
                pair_seen[key] = occurrence + 1
                runs.sort(key=lambda run: run.setting_id)
                pair_seed = int.from_bytes(hashlib.sha256(
                    _canonical_json([seed, key, occurrence // 2]).encode("utf-8")
                ).digest()[:8], "big")
                random.Random(pair_seed).shuffle(runs)
                if occurrence % 2:
                    runs.reverse()
            else:
                random.Random(block_seed).shuffle(runs)
            for block_order, run in enumerate(runs, start=1):
                _require(run.planned_run_id not in seen_runs, f"duplicate planned_run_id: {run.planned_run_id}")
                seen_runs.add(run.planned_run_id)
                declared_order = len(entries) + 1
                entries.append(ScheduledRun(
                    planned_run=replace(run, ordinal=declared_order),
                    block_id=block.block_id,
                    session_slot=block.session_slot,
                    block_order=block_order,
                    declared_order=declared_order,
                    preparation_sha256=block.preparation_sha256,
                ))
        payload = {"seed": seed, "entries": [entry.to_dict() for entry in entries]}
        return cls(schedule_id=f"schedule-{_digest(_canonical_json(payload))}", seed=seed, entries=tuple(entries))

    def to_dict(self) -> dict[str, Any]:
        return {"schedule_id": self.schedule_id, "seed": self.seed, "entries": [entry.to_dict() for entry in self.entries]}


@dataclass(frozen=True)
class ExecutorRequest:
    lease: AttemptLease
    scheduled_run: ScheduledRun
    requested_resources: tuple[tuple[str, str], ...] = ()
    checkpoint: Callable[[Iterable[ArtifactRef], Mapping[str, Any] | None], None] | None = None


@dataclass(frozen=True)
class OutcomeMetadata:
    """Observed execution facts that are intentionally separate from the contract."""

    actual_setting_id: str
    actual_tool_concurrency: bool
    actual_tool_workers: int
    actual_preparation_sha256: str
    observed_resources: tuple[tuple[str, str], ...] = ()
    owned_work_terminated: bool = True
    fidelity_status: str = "eligible"
    sensor_gaps: tuple[str, ...] = ()
    overlapping_domains: tuple[tuple[str, str], ...] = ()
    cost_seconds: tuple[tuple[str, float], ...] = ()
    failure_reason: str = ""

    def __post_init__(self) -> None:
        _require(isinstance(self.actual_setting_id, str) and bool(self.actual_setting_id.strip()), "actual_setting_id must be non-empty")
        _require(isinstance(self.actual_tool_concurrency, bool), "actual_tool_concurrency must be boolean")
        _require(isinstance(self.actual_tool_workers, int) and not isinstance(self.actual_tool_workers, bool) and self.actual_tool_workers >= 1,
                 "actual_tool_workers must be positive")
        _require(isinstance(self.actual_preparation_sha256, str) and len(self.actual_preparation_sha256) == 64
                 and all(c in "0123456789abcdef" for c in self.actual_preparation_sha256),
                 "actual_preparation_sha256 must be a lowercase SHA-256 digest")
        _require(self.fidelity_status in {"eligible", "divergent", "ineligible", "unknown"}, "invalid fidelity_status")
        for label, pairs in (("observed_resources", self.observed_resources), ("cost_seconds", self.cost_seconds)):
            keys = [key for key, _ in pairs]
            _require(all(isinstance(key, str) and key.strip() for key in keys), f"{label} keys must be non-empty strings")
            _require(len(keys) == len(set(keys)), f"{label} keys must be unique")
        for key, value in self.cost_seconds:
            _require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0,
                     f"cost_seconds {key} must be finite and non-negative")
        _canonical_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "actual_setting_id": self.actual_setting_id,
            "actual_tool_concurrency": self.actual_tool_concurrency,
            "actual_tool_workers": self.actual_tool_workers,
            "actual_preparation_sha256": self.actual_preparation_sha256,
            "observed_resources": dict(self.observed_resources),
            "owned_work_terminated": self.owned_work_terminated,
            "fidelity_status": self.fidelity_status,
            "sensor_gaps": list(self.sensor_gaps),
            "overlapping_domains": [list(pair) for pair in self.overlapping_domains],
            "cost_seconds": dict(self.cost_seconds),
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True)
class ExecutionOutcome:
    record: ExecutionRecord
    artifacts: tuple[ArtifactRef, ...]
    metadata: OutcomeMetadata


Executor = Callable[[ExecutorRequest], ExecutionOutcome]


class BoundedCampaignRunner:
    """Persist a schedule and invoke at most one executor goal at a time."""

    def __init__(self, ledger: RunLedger, schedule: CampaignSchedule, state_dir: Path | str) -> None:
        self.ledger = ledger
        self.schedule = schedule
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._by_id = {entry.planned_run.planned_run_id: entry for entry in schedule.entries}
        self._register_schedule()

    def _register_schedule(self) -> None:
        content = _canonical_json(self.schedule.to_dict()) + "\n"
        path = self.state_dir / "schedule.json"
        if path.exists():
            if path.read_text(encoding="utf-8") != content:
                raise LedgerValidationError("persisted schedule conflicts with requested schedule")
        else:
            temporary = path.with_name(f".{path.name}.tmp")
            temporary.write_text(content, encoding="utf-8", newline="\n")
            os.replace(temporary, path)
        self.ledger.register_plan(entry.planned_run for entry in self.schedule.entries)

    def run_next(
        self,
        *,
        session_id: str,
        started_ns: int,
        clock_domain: str,
        executor: Executor,
        requested_resources: Mapping[str, str] | None = None,
    ) -> Optional[AttemptLease]:
        resources = tuple(sorted((requested_resources or {}).items()))
        claim_metadata = {
            "schedule_id": self.schedule.schedule_id,
            "requested_resources": dict(resources),
        }
        lease = self.ledger.claim_next(
            session_id=session_id,
            started_ns=started_ns,
            clock_domain=clock_domain,
            metadata=claim_metadata,
        )
        if lease is None:
            return None
        entry = self._by_id[lease.planned_run_id]

        def checkpoint(artifacts: Iterable[ArtifactRef], metadata: Mapping[str, Any] | None = None) -> None:
            self.ledger.checkpoint(lease, artifacts, metadata=metadata)

        outcome = executor(ExecutorRequest(
            lease=lease,
            scheduled_run=entry,
            requested_resources=resources,
            checkpoint=checkpoint,
        ))
        if not outcome.metadata.owned_work_terminated:
            raise LedgerValidationError("executor returned before all work owned by the goal terminated")
        outcome_metadata = outcome.metadata.to_dict()
        if not outcome_metadata["failure_reason"]:
            if outcome.record.execution_status != "completed":
                outcome_metadata["failure_reason"] = outcome.record.error
            elif outcome.record.verifier.outcome != "pass":
                outcome_metadata["failure_reason"] = outcome.record.verifier.reason
        self.ledger.finalize(lease, outcome.record, outcome.artifacts, metadata=outcome_metadata)
        return lease

    def recover_interrupted(self, *, session_id: str, clock_domain: str, ended_ns: int, reason: str) -> tuple[AttemptLease, ...]:
        return self.ledger.recover_interrupted(
            session_id=session_id, clock_domain=clock_domain, ended_ns=ended_ns, reason=reason
        )

    def record_unknown_interruption(self, *, session_id: str, reason: str) -> tuple[AttemptLease, ...]:
        return self.ledger.record_unknown_interruption(session_id=session_id, reason=reason)

    def export(self, output_dir: Path | str) -> dict[str, Path]:
        paths = self.ledger.export(output_dir)
        destination = Path(output_dir)
        schedule_path = destination / "schedule.json"
        validation_path = destination / "campaign-validation.json"
        self._atomic_text(schedule_path, json.dumps(self.schedule.to_dict(), sort_keys=True, indent=2, allow_nan=False) + "\n")
        attempts = [json.loads(line) for line in paths["attempts"].read_text(encoding="utf-8").splitlines()]
        plans = [json.loads(line) for line in paths["plans"].read_text(encoding="utf-8").splitlines()]
        ledger_report = json.loads(paths["validation"].read_text(encoding="utf-8"))
        report = self._validate_exports(attempts, plans, ledger_report)
        self._atomic_text(validation_path, json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")
        return {**paths, "schedule": schedule_path, "campaign_validation": validation_path}

    def _validate_exports(
        self,
        attempts: list[dict[str, Any]],
        plans: list[dict[str, Any]],
        ledger_report: dict[str, Any],
    ) -> dict[str, Any]:
        errors = list(ledger_report["errors"])
        observations: list[dict[str, Any]] = []
        expected_plan_ids = set(self._by_id)
        persisted_plan_ids = {item["plan"]["planned_run_id"] for item in plans}
        if persisted_plan_ids != expected_plan_ids:
            errors.append("ledger plan set differs from the persisted campaign schedule")
        dispositions = [
            {
                "planned_run_id": item["plan"]["planned_run_id"],
                "declared_order": item["plan"]["ordinal"],
                "disposition": item["disposition"],
            }
            for item in plans
        ]
        expected_orders = list(range(1, len(attempts) + 1))
        actual_orders = [item["attempt"]["actual_order"] for item in attempts]
        if actual_orders != expected_orders:
            errors.append("exported attempts are not in contiguous actual execution order")
        for envelope in attempts:
            attempt = envelope["attempt"]
            entry = self._by_id.get(envelope["plan"]["planned_run_id"])
            reasons: list[str] = []
            if entry is None:
                errors.append(f"{attempt['attempt_id']}: plan is absent from schedule")
                continue
            claim = attempt["claim_metadata"]
            outcome = attempt["outcome_metadata"]
            if any(error.startswith(f"{attempt['attempt_id']}:") for error in errors):
                reasons.append("ledger validation error")
            if claim.get("schedule_id") != self.schedule.schedule_id:
                errors.append(f"{attempt['attempt_id']}: claim schedule_id mismatch")
                reasons.append("claim schedule mismatch")
            if outcome is None:
                reasons.append("attempt is still running")
            else:
                plan = envelope["plan"]
                if "recovery" not in outcome:
                    comparisons = (
                        ("actual_setting_id", plan["setting_id"], "actual setting differs from plan"),
                        ("actual_tool_concurrency", plan["tool_concurrency"], "actual concurrency differs from plan"),
                        ("actual_tool_workers", plan["tool_workers"], "actual worker count differs from plan"),
                        ("actual_preparation_sha256", entry.preparation_sha256, "actual preparation differs from schedule"),
                    )
                    for field, expected, message in comparisons:
                        if outcome.get(field) != expected:
                            errors.append(f"{attempt['attempt_id']}: {message}")
                            reasons.append(message)
                if outcome.get("owned_work_terminated") is not True:
                    errors.append(f"{attempt['attempt_id']}: owned work survived finalization")
                    reasons.append("owned work survived finalization")
                if outcome.get("overlapping_domains"):
                    errors.append(f"{attempt['attempt_id']}: overlapping measurement domains reported")
                    reasons.append("overlapping measurement domains")
                if outcome.get("fidelity_status") != "eligible":
                    reasons.append(f"fidelity {outcome.get('fidelity_status', 'unknown')}")
                if outcome.get("sensor_gaps"):
                    reasons.append("sensor gaps reported")
            if attempt["execution_status"] != "completed":
                reasons.append(f"execution {attempt['execution_status']}")
            if attempt["verifier_outcome"] != "pass":
                reasons.append(f"verifier {attempt['verifier_outcome']}")
            if attempt["measurement_status"] != "valid":
                reasons.append(f"measurement {attempt['measurement_status']}")
            observations.append({
                "attempt_id": attempt["attempt_id"],
                "actual_order": attempt["actual_order"],
                "analysis_eligible": not reasons,
                "exclusion_reasons": reasons,
            })
        return {
            "valid": not errors,
            "errors": errors,
            "warnings": ledger_report["warnings"],
            "counts": ledger_report["counts"],
            "dispositions": dispositions,
            "observations": observations,
        }

    @staticmethod
    def _atomic_text(path: Path, content: str) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)


__all__ = [
    "BoundedCampaignRunner", "CampaignSchedule", "ExecutionOutcome", "Executor",
    "ExecutorRequest", "OutcomeMetadata", "ScheduleBlock", "ScheduledRun",
]
