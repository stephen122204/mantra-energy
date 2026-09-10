"""Durable, restart-safe execution ledger for the energy-diagnosis study.

The planning utility in ``docs/agent-context/starter`` remains planning-only.
This module records realization of a plan while preserving every attempt.  It
uses only the Python standard library and deliberately supports a single
runner process; SQLite transactions and uniqueness constraints prevent two
callers from claiming the same planned run.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional

from studies.energy_diagnosis.contracts import (
    ExecutionRecord,
    VerifierResult,
)


class LedgerError(RuntimeError):
    """Base class for durable-ledger failures."""


class LedgerConflictError(LedgerError):
    """A persisted identity or immutable record conflicts with new input."""


class LedgerValidationError(LedgerError):
    """A plan, outcome, artifact, or ledger invariant is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LedgerValidationError(message)


def _non_empty(value: Any, name: str) -> None:
    _require(isinstance(value, str) and bool(value.strip()), f"{name} must be a non-empty string")


def _sha256(value: Any, name: str) -> None:
    _require(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value),
        f"{name} must be a lowercase SHA-256 hex digest",
    )


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise LedgerValidationError(f"value is not strict JSON: {error}") from error


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PlannedRun:
    """Immutable provenance for one slot in an execution plan."""

    planned_run_id: str
    ordinal: int
    task_id: str
    setting_id: str
    tool_concurrency: bool
    tool_workers: int
    source_commit: str
    task_asset_sha256: str
    model_sha256: str
    verifier_version: str
    verifier_sha256: str
    retry_limit: int = 0
    simulated: bool = True

    def __post_init__(self) -> None:
        for name in ("planned_run_id", "task_id", "setting_id", "source_commit", "verifier_version"):
            _non_empty(getattr(self, name), name)
        _require(isinstance(self.ordinal, int) and not isinstance(self.ordinal, bool) and self.ordinal >= 0, "ordinal must be a non-negative integer")
        _require(isinstance(self.tool_concurrency, bool), "tool_concurrency must be a boolean")
        _require(isinstance(self.tool_workers, int) and not isinstance(self.tool_workers, bool) and self.tool_workers >= 1, "tool_workers must be a positive integer")
        _require(isinstance(self.retry_limit, int) and not isinstance(self.retry_limit, bool) and self.retry_limit >= 0, "retry_limit must be a non-negative integer")
        _require(isinstance(self.simulated, bool), "simulated must be a boolean")
        _require(len(self.source_commit) == 40 and all(c in "0123456789abcdef" for c in self.source_commit), "source_commit must be a lowercase 40-character Git commit")
        for name in ("task_asset_sha256", "model_sha256", "verifier_sha256"):
            _sha256(getattr(self, name), name)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PlannedRun":
        try:
            return cls(**value)
        except TypeError as error:
            raise LedgerValidationError(f"invalid planned run: {error}") from error


@dataclass(frozen=True)
class ArtifactRef:
    """A portable, integrity-pinned artifact produced by an attempt."""

    path: str
    role: str
    sha256: str

    def __post_init__(self) -> None:
        _non_empty(self.path, "artifact.path")
        _non_empty(self.role, "artifact.role")
        _sha256(self.sha256, "artifact.sha256")
        _require("\\" not in self.path, "artifact.path must use portable forward slashes")
        path = PurePosixPath(self.path)
        _require(not path.is_absolute(), "artifact.path must be relative")
        _require(bool(path.parts), "artifact.path must name a file")
        _require(":" not in path.parts[0], "artifact.path must not contain a drive or URI scheme")
        _require(".." not in path.parts and "." not in path.parts, "artifact.path must not escape its root")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class AttemptLease:
    """Persisted identity for one claimed execution attempt."""

    planned_run_id: str
    execution_id: str
    attempt_id: str
    attempt_number: int
    session_id: str
    started_ns: int
    clock_domain: str
    simulated: bool


_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS plans (
    planned_run_id TEXT PRIMARY KEY,
    ordinal INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK (disposition IN ('pending', 'running', 'terminal')),
    active_attempt_id TEXT,
    last_attempt_id TEXT,
    CHECK ((disposition = 'running') = (active_attempt_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE,
    planned_run_id TEXT NOT NULL REFERENCES plans(planned_run_id),
    attempt_number INTEGER NOT NULL,
    session_id TEXT NOT NULL,
    started_ns INTEGER NOT NULL,
    ended_ns INTEGER,
    clock_domain TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'terminal')),
    execution_record_json TEXT,
    artifacts_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE (planned_run_id, attempt_number),
    CHECK ((status = 'running') = (execution_record_json IS NULL))
);
CREATE TABLE IF NOT EXISTS retry_requests (
    planned_run_id TEXT NOT NULL REFERENCES plans(planned_run_id),
    after_attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(attempt_id),
    reason TEXT NOT NULL,
    PRIMARY KEY (planned_run_id, after_attempt_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_running_attempt_per_plan
    ON attempts(planned_run_id) WHERE status = 'running';
"""


class RunLedger:
    """SQLite-backed execution ledger with explicit restart recovery."""

    def __init__(self, path: Path | str, *, artifact_root: Path | str | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_root = Path(artifact_root).resolve() if artifact_root is not None else None
        self._db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "RunLedger":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def register_plan(self, runs: Iterable[PlannedRun]) -> None:
        """Register immutable plan slots; identical registration is idempotent."""
        prepared: list[tuple[PlannedRun, str, str]] = []
        seen: set[str] = set()
        for run in runs:
            _require(run.planned_run_id not in seen, f"duplicate planned_run_id in input: {run.planned_run_id}")
            seen.add(run.planned_run_id)
            payload = _canonical_json(run.to_dict())
            prepared.append((run, payload, _digest_text(payload)))
        _require(bool(prepared), "plan must contain at least one run")

        self._begin()
        try:
            for run, payload, digest in prepared:
                existing = self._db.execute(
                    "SELECT payload_sha256 FROM plans WHERE planned_run_id = ?",
                    (run.planned_run_id,),
                ).fetchone()
                if existing is not None:
                    if existing["payload_sha256"] != digest:
                        raise LedgerConflictError(f"planned run {run.planned_run_id} conflicts with its persisted definition")
                    continue
                self._db.execute(
                    "INSERT INTO plans VALUES (?, ?, ?, ?, 'pending', NULL, NULL)",
                    (run.planned_run_id, run.ordinal, payload, digest),
                )
            self._commit()
        except Exception:
            self._rollback()
            raise

    def claim_next(self, *, session_id: str, started_ns: int, clock_domain: str) -> Optional[AttemptLease]:
        """Claim the next pending slot, or return None if busy or exhausted.

        One ledger admits at most one running goal, including across connections.
        A caller must finish/terminate owned work before finalizing its lease.
        """
        _non_empty(session_id, "session_id")
        _non_empty(clock_domain, "clock_domain")
        _require(isinstance(started_ns, int) and not isinstance(started_ns, bool) and started_ns >= 0, "started_ns must be a non-negative integer")

        self._begin()
        try:
            if self._db.execute("SELECT 1 FROM attempts WHERE status = 'running' LIMIT 1").fetchone():
                self._commit()
                return None
            row = self._db.execute(
                "SELECT * FROM plans WHERE disposition = 'pending' ORDER BY ordinal, planned_run_id LIMIT 1"
            ).fetchone()
            if row is None:
                self._commit()
                return None
            plan = PlannedRun.from_dict(json.loads(row["payload_json"]))
            if plan.simulated:
                _require("fixture" in session_id.lower(), "simulated runs require an explicitly fixture-labeled session_id")
                _require("fixture" in clock_domain.lower(), "simulated runs require an explicitly fixture-labeled clock_domain")
            previous = self._db.execute(
                "SELECT COALESCE(MAX(attempt_number), 0) AS number FROM attempts WHERE planned_run_id = ?",
                (plan.planned_run_id,),
            ).fetchone()["number"]
            attempt_number = previous + 1
            _require(attempt_number <= plan.retry_limit + 1, f"retry limit exhausted for {plan.planned_run_id}")
            execution_id = f"exec-{uuid.uuid4()}"
            attempt_id = f"attempt-{uuid.uuid4()}"
            self._db.execute(
                "INSERT INTO attempts(attempt_id, execution_id, planned_run_id, attempt_number, session_id, started_ns, clock_domain, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'running')",
                (attempt_id, execution_id, plan.planned_run_id, attempt_number, session_id, started_ns, clock_domain),
            )
            cursor = self._db.execute(
                "UPDATE plans SET disposition = 'running', active_attempt_id = ?, last_attempt_id = ? WHERE planned_run_id = ? AND disposition = 'pending'",
                (attempt_id, attempt_id, plan.planned_run_id),
            )
            _require(cursor.rowcount == 1, f"failed to claim {plan.planned_run_id}")
            self._commit()
            return AttemptLease(
                planned_run_id=plan.planned_run_id,
                execution_id=execution_id,
                attempt_id=attempt_id,
                attempt_number=attempt_number,
                session_id=session_id,
                started_ns=started_ns,
                clock_domain=clock_domain,
                simulated=plan.simulated,
            )
        except Exception:
            self._rollback()
            raise

    def finalize(
        self,
        lease: AttemptLease,
        record: ExecutionRecord,
        artifacts: Iterable[ArtifactRef] = (),
    ) -> None:
        """Validate and permanently finalize a running attempt."""
        artifact_list = tuple(artifacts)
        self._validate_artifacts(artifact_list)
        self._begin()
        try:
            self._finalize_tx(lease, record, artifact_list, requeue=False)
            self._commit()
        except Exception:
            self._rollback()
            raise

    def recover_interrupted(
        self, *, session_id: str, clock_domain: str, ended_ns: int, reason: str,
    ) -> tuple[AttemptLease, ...]:
        """Recover one session using a known termination endpoint in its clock.

        Call only after owned processes have terminated. ``ended_ns`` must come
        from the original host/boot clock (or retained endpoint evidence), never
        from the restart host's clock. Unknown termination times are not accepted
        by this v0.1 interface; retain the running attempt pending reconciliation.
        """
        _non_empty(session_id, "session_id")
        _non_empty(clock_domain, "clock_domain")
        _require(isinstance(ended_ns, int) and not isinstance(ended_ns, bool) and ended_ns >= 0, "ended_ns must be a non-negative integer")
        _non_empty(reason, "reason")
        recovered: list[AttemptLease] = []
        self._begin()
        try:
            rows = self._db.execute(
                "SELECT a.*, p.payload_json FROM attempts a JOIN plans p USING (planned_run_id) WHERE a.status = 'running' AND a.session_id = ? ORDER BY p.ordinal, a.attempt_number",
                (session_id,),
            ).fetchall()
            for row in rows:
                plan = PlannedRun.from_dict(json.loads(row["payload_json"]))
                lease = self._lease_from_row(row, plan.simulated)
                _require(clock_domain == lease.clock_domain, f"recovery clock_domain differs from original attempt {lease.attempt_id}")
                _require(ended_ns >= lease.started_ns, f"ended_ns precedes start for {lease.attempt_id}")
                record = ExecutionRecord(
                    goal_execution_id=lease.execution_id,
                    planned_run_id=lease.planned_run_id,
                    session_id=lease.session_id,
                    task_id=plan.task_id,
                    setting_id=plan.setting_id,
                    attempt_number=lease.attempt_number,
                    execution_status="incomplete",
                    started_ns=lease.started_ns,
                    ended_ns=ended_ns,
                    clock_domain=lease.clock_domain,
                    verifier=VerifierResult(
                        verifier_version=plan.verifier_version,
                        outcome="unavailable",
                        reason=f"verification unavailable: {reason}",
                    ),
                    simulated=plan.simulated,
                    error=reason,
                    notes="Recovered after interruption; the prior observation is retained.",
                )
                may_retry = lease.attempt_number <= plan.retry_limit
                self._finalize_tx(lease, record, (), requeue=may_retry)
                if may_retry:
                    self._db.execute(
                        "INSERT INTO retry_requests VALUES (?, ?, ?)",
                        (lease.planned_run_id, lease.attempt_id, f"automatic recovery: {reason}"),
                    )
                recovered.append(lease)
            self._commit()
        except Exception:
            self._rollback()
            raise
        return tuple(recovered)

    def schedule_retry(self, planned_run_id: str, *, reason: str) -> None:
        """Return a terminal plan to pending while retaining its prior attempt."""
        _non_empty(planned_run_id, "planned_run_id")
        _non_empty(reason, "reason")
        self._begin()
        try:
            row = self._db.execute("SELECT * FROM plans WHERE planned_run_id = ?", (planned_run_id,)).fetchone()
            if row is None:
                raise LedgerValidationError(f"unknown planned run: {planned_run_id}")
            if row["disposition"] != "terminal":
                raise LedgerConflictError(f"planned run {planned_run_id} is not terminal")
            plan = PlannedRun.from_dict(json.loads(row["payload_json"]))
            count = self._db.execute("SELECT COUNT(*) AS count FROM attempts WHERE planned_run_id = ?", (planned_run_id,)).fetchone()["count"]
            if count >= plan.retry_limit + 1:
                raise LedgerConflictError(f"retry limit exhausted for {planned_run_id}")
            after_attempt_id = row["last_attempt_id"]
            self._db.execute("INSERT INTO retry_requests VALUES (?, ?, ?)", (planned_run_id, after_attempt_id, reason))
            self._db.execute("UPDATE plans SET disposition = 'pending', active_attempt_id = NULL WHERE planned_run_id = ?", (planned_run_id,))
            self._commit()
        except Exception:
            self._rollback()
            raise

    def validate(self) -> dict[str, Any]:
        """Return a deterministic integrity report without discarding bad data."""
        errors: list[str] = []
        warnings: list[str] = []
        plans = self._db.execute("SELECT * FROM plans ORDER BY ordinal, planned_run_id").fetchall()
        attempts = self._db.execute("SELECT * FROM attempts ORDER BY planned_run_id, attempt_number").fetchall()
        by_plan: dict[str, list[sqlite3.Row]] = {}
        parsed_plans: dict[str, PlannedRun] = {}
        for attempt in attempts:
            by_plan.setdefault(attempt["planned_run_id"], []).append(attempt)

        for row in plans:
            try:
                plan = PlannedRun.from_dict(json.loads(row["payload_json"]))
                parsed_plans[plan.planned_run_id] = plan
                if _digest_text(row["payload_json"]) != row["payload_sha256"]:
                    errors.append(f"{plan.planned_run_id}: plan payload hash mismatch")
            except Exception as error:
                errors.append(f"{row['planned_run_id']}: invalid plan payload: {error}")
                continue
            linked = by_plan.get(plan.planned_run_id, [])
            numbers = [item["attempt_number"] for item in linked]
            if numbers != list(range(1, len(numbers) + 1)):
                errors.append(f"{plan.planned_run_id}: attempt numbers are not contiguous")
            running = [item for item in linked if item["status"] == "running"]
            if row["disposition"] == "running" and len(running) != 1:
                errors.append(f"{plan.planned_run_id}: running disposition does not identify one running attempt")
            if row["disposition"] != "running" and running:
                errors.append(f"{plan.planned_run_id}: non-running disposition has a running attempt")
            if row["disposition"] == "pending":
                warnings.append(f"{plan.planned_run_id}: pending")

        for row in attempts:
            if row["status"] == "running":
                warnings.append(f"{row['attempt_id']}: running")
                continue
            try:
                record = ExecutionRecord.from_json(row["execution_record_json"])
                plan = parsed_plans[row["planned_run_id"]]
                lease = self._lease_from_row(row, plan.simulated)
                self._validate_record_identity(plan, lease, record)
                self._validate_record_safety(record)
                artifacts = tuple(ArtifactRef(**item) for item in json.loads(row["artifacts_json"]))
                self._validate_artifacts(artifacts)
            except Exception as error:
                errors.append(f"{row['attempt_id']}: invalid terminal attempt: {error}")

        counts = {
            "plans": len(plans),
            "pending": sum(row["disposition"] == "pending" for row in plans),
            "running": sum(row["disposition"] == "running" for row in plans),
            "terminal": sum(row["disposition"] == "terminal" for row in plans),
            "attempts": len(attempts),
        }
        return {"valid": not errors, "errors": errors, "warnings": warnings, "counts": counts}

    def export(self, output_dir: Path | str) -> dict[str, Path]:
        """Write deterministic lossless, summary, and validation exports atomically."""
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        report = self.validate()
        attempts = self._db.execute(
            "SELECT a.*, p.ordinal, p.payload_json, p.disposition FROM attempts a JOIN plans p USING (planned_run_id) ORDER BY p.ordinal, p.planned_run_id, a.attempt_number"
        ).fetchall()
        plans = self._db.execute("SELECT * FROM plans ORDER BY ordinal, planned_run_id").fetchall()
        retry_reasons = {
            row["after_attempt_id"]: row["reason"]
            for row in self._db.execute("SELECT after_attempt_id, reason FROM retry_requests").fetchall()
        }
        previous_attempt: dict[str, str] = {}

        jsonl_lines = []
        for row in attempts:
            retried_after = previous_attempt.get(row["planned_run_id"])
            execution_record = json.loads(row["execution_record_json"]) if row["execution_record_json"] else None
            measurement = self._measurement_summary(execution_record)
            envelope = {
                "artifact_type": "simulated_execution_attempt" if json.loads(row["payload_json"])["simulated"] else "execution_attempt",
                "plan": json.loads(row["payload_json"]),
                "attempt": {
                    "attempt_id": row["attempt_id"],
                    "execution_id": row["execution_id"],
                    "attempt_number": row["attempt_number"],
                    "session_id": row["session_id"],
                    "started_ns": row["started_ns"],
                    "ended_ns": row["ended_ns"],
                    "clock_domain": row["clock_domain"],
                    "status": row["status"],
                    "retried_after_attempt_id": retried_after,
                    "retry_reason": retry_reasons.get(retried_after, "") if retried_after else "",
                    "execution_status": execution_record["execution_status"] if execution_record else "running",
                    "verifier_outcome": execution_record["verifier"]["outcome"] if execution_record else "unavailable",
                    "measurement_status": measurement["status"],
                    "measurement_reason": measurement["reason"],
                    "execution_record": execution_record,
                    "artifacts": json.loads(row["artifacts_json"]),
                },
            }
            jsonl_lines.append(_canonical_json(envelope))
            previous_attempt[row["planned_run_id"]] = row["attempt_id"]

        plan_lines: list[str] = []
        summary_rows: list[dict[str, Any]] = []
        for plan_row in plans:
            plan = PlannedRun.from_dict(json.loads(plan_row["payload_json"]))
            plan_lines.append(_canonical_json({
                "plan": plan.to_dict(),
                "payload_sha256": plan_row["payload_sha256"],
                "disposition": plan_row["disposition"],
                "active_attempt_id": plan_row["active_attempt_id"],
                "last_attempt_id": plan_row["last_attempt_id"],
                "retry_requests": [dict(row) for row in self._db.execute(
                    "SELECT r.after_attempt_id, r.reason FROM retry_requests r JOIN attempts a ON a.attempt_id = r.after_attempt_id WHERE r.planned_run_id = ? ORDER BY a.attempt_number",
                    (plan.planned_run_id,),
                ).fetchall()],
            }))
            latest = self._db.execute(
                "SELECT * FROM attempts WHERE planned_run_id = ? ORDER BY attempt_number DESC LIMIT 1",
                (plan.planned_run_id,),
            ).fetchone()
            record = ExecutionRecord.from_json(latest["execution_record_json"]) if latest and latest["execution_record_json"] else None
            measurement = self._measurement_summary(record.to_dict() if record else None)
            summary_rows.append({
                "planned_run_id": plan.planned_run_id,
                "ordinal": plan.ordinal,
                "task_id": plan.task_id,
                "setting_id": plan.setting_id,
                "disposition": plan_row["disposition"],
                "attempt_count": self._db.execute("SELECT COUNT(*) FROM attempts WHERE planned_run_id = ?", (plan.planned_run_id,)).fetchone()[0],
                "latest_execution_id": latest["execution_id"] if latest else "",
                "execution_status": record.execution_status if record else "",
                "verifier_outcome": record.verifier.outcome if record else "",
                "measurement_status": measurement["status"],
                "measurement_reason": measurement["reason"],
                "simulated": str(plan.simulated).lower(),
            })

        jsonl_path = destination / "attempts.jsonl"
        plans_path = destination / "plans.jsonl"
        csv_path = destination / "dispositions.csv"
        report_path = destination / "validation-report.json"
        self._atomic_text(jsonl_path, "\n".join(jsonl_lines) + ("\n" if jsonl_lines else ""))
        self._atomic_text(plans_path, "\n".join(plan_lines) + ("\n" if plan_lines else ""))
        self._atomic_csv(csv_path, summary_rows)
        self._atomic_text(report_path, json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")
        return {"attempts": jsonl_path, "plans": plans_path, "dispositions": csv_path, "validation": report_path}

    def _finalize_tx(
        self,
        lease: AttemptLease,
        record: ExecutionRecord,
        artifacts: tuple[ArtifactRef, ...],
        *,
        requeue: bool,
    ) -> None:
        row = self._db.execute(
            "SELECT a.*, p.payload_json, p.active_attempt_id FROM attempts a JOIN plans p USING (planned_run_id) WHERE a.attempt_id = ?",
            (lease.attempt_id,),
        ).fetchone()
        if row is None:
            raise LedgerValidationError(f"unknown attempt: {lease.attempt_id}")
        if row["status"] != "running" or row["active_attempt_id"] != lease.attempt_id:
            raise LedgerConflictError(f"attempt {lease.attempt_id} is already terminal or is not active")
        persisted = self._lease_from_row(row, PlannedRun.from_dict(json.loads(row["payload_json"])).simulated)
        if persisted != lease:
            raise LedgerConflictError(f"attempt lease does not match persisted identity: {lease.attempt_id}")
        plan = PlannedRun.from_dict(json.loads(row["payload_json"]))
        self._validate_record_identity(plan, lease, record)
        self._validate_record_safety(record)
        record_json = _canonical_json(record.to_dict())
        artifacts_json = _canonical_json([artifact.to_dict() for artifact in artifacts])
        self._db.execute(
            "UPDATE attempts SET ended_ns = ?, status = 'terminal', execution_record_json = ?, artifacts_json = ? WHERE attempt_id = ? AND status = 'running'",
            (record.ended_ns, record_json, artifacts_json, lease.attempt_id),
        )
        disposition = "pending" if requeue else "terminal"
        self._db.execute(
            "UPDATE plans SET disposition = ?, active_attempt_id = NULL, last_attempt_id = ? WHERE planned_run_id = ? AND active_attempt_id = ?",
            (disposition, lease.attempt_id, lease.planned_run_id, lease.attempt_id),
        )

    @staticmethod
    def _validate_record_identity(plan: PlannedRun, lease: AttemptLease, record: ExecutionRecord) -> None:
        expected = {
            "goal_execution_id": lease.execution_id,
            "planned_run_id": lease.planned_run_id,
            "session_id": lease.session_id,
            "task_id": plan.task_id,
            "setting_id": plan.setting_id,
            "attempt_number": lease.attempt_number,
            "started_ns": lease.started_ns,
            "clock_domain": lease.clock_domain,
            "simulated": plan.simulated,
        }
        for field, value in expected.items():
            if getattr(record, field) != value:
                raise LedgerValidationError(f"execution record {field} does not match the claimed plan/attempt")
        if record.model_response is not None and record.model_response.model_hash != plan.model_sha256:
            raise LedgerValidationError("execution record model_hash does not match plan provenance")
        if record.verifier.verifier_version != plan.verifier_version:
            raise LedgerValidationError("execution record verifier_version does not match plan provenance")
        for span in record.spans:
            if span.attempt_id != lease.attempt_id:
                raise LedgerValidationError(f"span {span.span_id} does not link to the claimed attempt_id")

    @staticmethod
    def _validate_record_safety(record: ExecutionRecord) -> None:
        domains: set[str] = set()
        for measurement in record.measurements:
            if measurement.domain_id in domains:
                raise LedgerValidationError(f"duplicate measurement domain: {measurement.domain_id}")
            domains.add(measurement.domain_id)
            if measurement.start_ns < record.started_ns or measurement.end_ns > record.ended_ns:
                raise LedgerValidationError(f"measurement {measurement.domain_id} is not fully bounded by the execution window")
            if measurement.status == "valid" and (
                measurement.start_ns != record.started_ns or measurement.end_ns != record.ended_ns
            ):
                raise LedgerValidationError(f"valid measurement {measurement.domain_id} must cover the full goal window")
            for name in ("energy_j", "coverage"):
                value = getattr(measurement, name)
                if value is not None and (isinstance(value, bool) or not math.isfinite(value)):
                    raise LedgerValidationError(f"measurement {measurement.domain_id} has invalid {name}")
        response = record.model_response
        if response is not None:
            _require(response.clock_domain == record.clock_domain, "model response clock_domain differs from execution")
            _require(record.started_ns <= response.started_ns <= response.ended_ns <= record.ended_ns,
                     "model response is not bounded by the execution window")
            for name in ("prompt_tokens", "completion_tokens"):
                value = getattr(response, name)
                if isinstance(value, bool):
                    raise LedgerValidationError(f"model response {name} must not be boolean")
        _canonical_json(record.to_dict())

    def _validate_artifacts(self, artifacts: tuple[ArtifactRef, ...]) -> None:
        paths: set[str] = set()
        for artifact in artifacts:
            if artifact.path in paths:
                raise LedgerValidationError(f"duplicate artifact path: {artifact.path}")
            paths.add(artifact.path)
            if self.artifact_root is None:
                raise LedgerValidationError("artifact_root is required when artifact references are supplied")
            candidate = (self.artifact_root / Path(*PurePosixPath(artifact.path).parts)).resolve()
            try:
                candidate.relative_to(self.artifact_root)
            except ValueError as error:
                raise LedgerValidationError(f"artifact escapes root: {artifact.path}") from error
            if not candidate.is_file():
                raise LedgerValidationError(f"artifact does not exist: {artifact.path}")
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
            if digest != artifact.sha256:
                raise LedgerValidationError(f"artifact hash mismatch: {artifact.path}")

    @staticmethod
    def _lease_from_row(row: sqlite3.Row, simulated: bool) -> AttemptLease:
        return AttemptLease(
            planned_run_id=row["planned_run_id"],
            execution_id=row["execution_id"],
            attempt_id=row["attempt_id"],
            attempt_number=row["attempt_number"],
            session_id=row["session_id"],
            started_ns=row["started_ns"],
            clock_domain=row["clock_domain"],
            simulated=simulated,
        )

    def _begin(self) -> None:
        self._db.execute("BEGIN IMMEDIATE")

    def _commit(self) -> None:
        self._db.execute("COMMIT")

    def _rollback(self) -> None:
        self._db.execute("ROLLBACK")

    @staticmethod
    def _atomic_text(path: Path, content: str) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)

    @staticmethod
    def _atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
        fieldnames = [
            "planned_run_id", "ordinal", "task_id", "setting_id", "disposition",
            "attempt_count", "latest_execution_id", "execution_status",
            "verifier_outcome", "measurement_status", "measurement_reason", "simulated",
        ]
        temporary = path.with_name(f".{path.name}.tmp")
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)

    @staticmethod
    def _measurement_summary(record: Optional[dict[str, Any]]) -> dict[str, str]:
        if record is None:
            return {"status": "unavailable", "reason": "attempt has not produced a terminal execution record"}
        measurements = record.get("measurements", [])
        if not measurements:
            reason = record.get("error") or "no measurement records were produced"
            return {"status": "unavailable", "reason": reason}
        statuses = ";".join(sorted({str(item["status"]) for item in measurements}))
        reasons = "; ".join(sorted({str(item.get("reason", "")) for item in measurements if item.get("reason")}))
        return {"status": statuses, "reason": reasons}


__all__ = [
    "ArtifactRef",
    "AttemptLease",
    "LedgerConflictError",
    "LedgerError",
    "LedgerValidationError",
    "PlannedRun",
    "RunLedger",
]
