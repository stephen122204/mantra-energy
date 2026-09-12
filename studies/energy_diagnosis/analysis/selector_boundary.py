"""Budgeted selector capability and held-out reference boundary.

The scientific selector is injected.  This module only controls what it can
observe, accounts for profiling attempts, seals its decision, and exposes
reference/live evaluation through separate post-seal methods.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional


class SelectorBoundaryError(RuntimeError):
    """Base error for selector access, budget, and immutability violations."""


class BudgetExhaustedError(SelectorBoundaryError):
    """Raised when another profiling query is not allowed."""


class ReferenceAccessError(SelectorBoundaryError):
    """Raised when reference or live-evaluation access violates the seal."""


class SelectorConflictError(SelectorBoundaryError):
    """Raised when immutable session or decision state conflicts."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SelectorBoundaryError(message)


def _non_empty(value: Any, name: str) -> None:
    _require(isinstance(value, str) and bool(value.strip()), f"{name} must be a non-empty string")


def _finite_nonnegative(value: Any, name: str) -> None:
    _require(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value) and value >= 0,
        f"{name} must be finite and non-negative",
    )


def _nonnegative_int(value: Any, name: str) -> None:
    _require(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0,
        f"{name} must be a non-negative integer",
    )


def _sha256(value: Any, name: str) -> None:
    _require(
        isinstance(value, str) and len(value) == 64
        and all(character in "0123456789abcdef" for character in value),
        f"{name} must be a lowercase SHA-256 digest",
    )


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise SelectorBoundaryError(f"value is not strict JSON: {error}") from error


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProfilingBudget:
    max_queries: int
    max_duration_s: float
    max_energy_j: Optional[float] = None

    def __post_init__(self) -> None:
        _require(
            isinstance(self.max_queries, int) and not isinstance(self.max_queries, bool)
            and self.max_queries >= 0,
            "max_queries must be a non-negative integer",
        )
        _finite_nonnegative(self.max_duration_s, "max_duration_s")
        if self.max_energy_j is not None:
            _finite_nonnegative(self.max_energy_j, "max_energy_j")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProfileResult:
    """One profiler result, including failed work and unavailable energy."""

    status: str
    duration_s: float
    energy_j: Optional[float]
    energy_reason: str
    features: Mapping[str, Any]
    failure_reason: str = ""

    def __post_init__(self) -> None:
        _require(self.status in {"success", "failure"}, "profile status must be success or failure")
        _finite_nonnegative(self.duration_s, "duration_s")
        if self.energy_j is None:
            _non_empty(self.energy_reason, "energy_reason when energy is unavailable")
        else:
            _finite_nonnegative(self.energy_j, "energy_j")
            _require(not self.energy_reason, "energy_reason must be empty when energy is available")
        if self.status == "failure":
            _non_empty(self.failure_reason, "failure_reason")
        else:
            _require(not self.failure_reason, "successful profiles cannot carry failure_reason")
        _require(isinstance(self.features, Mapping), "features must be a mapping")
        _canonical_json(dict(self.features))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "duration_s": self.duration_s,
            "energy_j": self.energy_j,
            "energy_reason": self.energy_reason,
            "features": dict(self.features),
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True)
class SealedDecision:
    decision_id: str
    session_id: str
    selector_revision: str
    development_data_sha256: str
    outcome: str
    recommendation: Optional[str]
    abstention_reason: str
    rationale: str
    query_ids: tuple[str, ...]
    profiling_query_count: int
    profiling_duration_s: float
    profiling_energy_j: Optional[float]
    unavailable_energy_queries: int
    sealed_at_ns: int
    seal_sha256: str

    def __post_init__(self) -> None:
        for name in ("decision_id", "session_id", "selector_revision"):
            _non_empty(getattr(self, name), name)
        _sha256(self.development_data_sha256, "development_data_sha256")
        _sha256(self.seal_sha256, "seal_sha256")
        _require(self.outcome in {"recommendation", "abstention"}, "invalid decision outcome")
        if self.outcome == "recommendation":
            _non_empty(self.recommendation, "recommendation")
            _non_empty(self.rationale, "rationale")
            _require(not self.abstention_reason, "recommendation cannot carry abstention_reason")
        else:
            _require(self.recommendation is None, "abstention cannot carry recommendation")
            _non_empty(self.abstention_reason, "abstention_reason")
            _require(not self.rationale, "abstention cannot carry rationale")
        _require(
            isinstance(self.profiling_query_count, int) and not isinstance(self.profiling_query_count, bool)
            and self.profiling_query_count >= 0,
            "profiling_query_count must be non-negative",
        )
        _require(len(self.query_ids) == self.profiling_query_count, "query_ids count mismatch")
        _require(len(self.query_ids) == len(set(self.query_ids)), "query_ids must be unique")
        _finite_nonnegative(self.profiling_duration_s, "profiling_duration_s")
        if self.profiling_energy_j is not None:
            _finite_nonnegative(self.profiling_energy_j, "profiling_energy_j")
        _require(
            isinstance(self.unavailable_energy_queries, int)
            and not isinstance(self.unavailable_energy_queries, bool)
            and 0 <= self.unavailable_energy_queries <= self.profiling_query_count,
            "unavailable_energy_queries is invalid",
        )
        _require(
            isinstance(self.sealed_at_ns, int) and not isinstance(self.sealed_at_ns, bool)
            and self.sealed_at_ns >= 0,
            "sealed_at_ns must be non-negative",
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SealedDecision":
        data = dict(value)
        data["query_ids"] = tuple(data["query_ids"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["query_ids"] = list(self.query_ids)
        return value


_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS selector_sessions (
    session_id TEXT PRIMARY KEY,
    definition_json TEXT NOT NULL,
    definition_sha256 TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('open', 'sealed')),
    decision_json TEXT,
    decision_sha256 TEXT,
    CHECK ((state = 'sealed') = (decision_json IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS profile_queries (
    query_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES selector_sessions(session_id),
    query_index INTEGER NOT NULL,
    candidate_id TEXT NOT NULL,
    result_json TEXT NOT NULL,
    UNIQUE(session_id, query_index)
);
CREATE TABLE IF NOT EXISTS reference_results (
    session_id TEXT PRIMARY KEY REFERENCES selector_sessions(session_id),
    outcomes_json TEXT NOT NULL,
    outcomes_sha256 TEXT NOT NULL,
    opened_at_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS live_evaluations (
    session_id TEXT PRIMARY KEY REFERENCES selector_sessions(session_id),
    setting_id TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);
"""


Profiler = Callable[[str], ProfileResult]
Selector = Callable[["RestrictedSelectorAPI"], None]


class RestrictedSelectorAPI:
    """Only the capabilities supplied to a selector before its decision seal."""

    __slots__ = ("__profile", "__remaining", "__recommend", "__abstain", "candidates")

    def __init__(
        self,
        *,
        candidates: tuple[str, ...],
        profile: Callable[[str], ProfileResult],
        remaining: Callable[[], dict[str, Any]],
        recommend: Callable[[str, str], SealedDecision],
        abstain: Callable[[str], SealedDecision],
    ) -> None:
        self.candidates = candidates
        self.__profile = profile
        self.__remaining = remaining
        self.__recommend = recommend
        self.__abstain = abstain

    def profile(self, candidate_id: str) -> ProfileResult:
        return self.__profile(candidate_id)

    def remaining_budget(self) -> dict[str, Any]:
        return self.__remaining()

    def seal_recommendation(self, candidate_id: str, rationale: str) -> SealedDecision:
        return self.__recommend(candidate_id, rationale)

    def seal_abstention(self, reason: str) -> SealedDecision:
        return self.__abstain(reason)


class SelectorBoundary:
    """SQLite-backed profiling budget and pre/post-seal information boundary."""

    def __init__(
        self,
        path: Path | str,
        *,
        session_id: str,
        selector_revision: str,
        development_data_sha256: str,
        candidates: tuple[str, ...],
        allowed_features: tuple[str, ...],
        budget: ProfilingBudget,
        profiler: Profiler,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        _non_empty(session_id, "session_id")
        _non_empty(selector_revision, "selector_revision")
        _sha256(development_data_sha256, "development_data_sha256")
        _require(bool(candidates), "candidates must not be empty")
        _require(len(candidates) == len(set(candidates)), "candidates must be unique")
        for candidate in candidates:
            _non_empty(candidate, "candidate_id")
        _require(len(allowed_features) == len(set(allowed_features)), "allowed_features must be unique")
        for feature in allowed_features:
            _non_empty(feature, "allowed feature")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self.selector_revision = selector_revision
        self.development_data_sha256 = development_data_sha256
        self.candidates = candidates
        self.allowed_features = allowed_features
        self.budget = budget
        self.profiler = profiler
        self.clock_ns = clock_ns
        self._db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        try:
            self._db.executescript(_SCHEMA)
            self._register_session()
        except Exception:
            self._db.close()
            raise

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "SelectorBoundary":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _register_session(self) -> None:
        definition = {
            "session_id": self.session_id,
            "selector_revision": self.selector_revision,
            "development_data_sha256": self.development_data_sha256,
            "candidates": list(self.candidates),
            "allowed_features": list(self.allowed_features),
            "budget": self.budget.to_dict(),
        }
        definition_json = _canonical_json(definition)
        digest = _digest(definition_json)
        row = self._db.execute(
            "SELECT definition_sha256 FROM selector_sessions WHERE session_id = ?", (self.session_id,)
        ).fetchone()
        if row is not None:
            if row["definition_sha256"] != digest:
                raise SelectorConflictError("selector session definition conflicts with persisted state")
            return
        self._db.execute(
            "INSERT INTO selector_sessions VALUES (?, ?, ?, 'open', NULL, NULL)",
            (self.session_id, definition_json, digest),
        )

    def run_selector(self, selector: Selector) -> SealedDecision:
        _require(callable(selector), "selector must be callable")
        if self.decision() is not None:
            raise SelectorConflictError("selector decision is already sealed")
        api = RestrictedSelectorAPI(
            candidates=self.candidates,
            profile=self.profile,
            remaining=self.remaining_budget,
            recommend=self.seal_recommendation,
            abstain=self.seal_abstention,
        )
        try:
            selector(api)
        except Exception as error:
            if self.decision() is None:
                self.seal_abstention(f"selector failed: {type(error).__name__}: {error}")
            raise
        decision = self.decision()
        if decision is None:
            decision = self.seal_abstention("selector returned without sealing a decision")
        return decision

    def profile(self, candidate_id: str) -> ProfileResult:
        self._require_open()
        _require(candidate_id in self.candidates, f"candidate is not eligible: {candidate_id}")
        remaining = self.remaining_budget()
        if remaining["exhausted"]:
            raise BudgetExhaustedError("profiling budget exhausted: " + "; ".join(remaining["reasons"]))
        query_index = remaining["used_queries"] + 1
        query_id = f"{self.session_id}-query-{query_index:04d}"
        started_ns = self.clock_ns()
        _nonnegative_int(started_ns, "profile started_ns")
        try:
            result = self.profiler(candidate_id)
            _require(isinstance(result, ProfileResult), "profiler must return ProfileResult")
        except Exception as error:
            ended_ns = self.clock_ns()
            _nonnegative_int(ended_ns, "profile ended_ns")
            _require(ended_ns >= started_ns, "profile clock moved backwards")
            duration_s = (ended_ns - started_ns) / 1_000_000_000
            result = ProfileResult(
                status="failure",
                duration_s=duration_s,
                energy_j=None,
                energy_reason="energy unavailable because profiler raised",
                features={},
                failure_reason=f"{type(error).__name__}: {error}",
            )
        undeclared = sorted(set(result.features) - set(self.allowed_features))
        if undeclared:
            result = ProfileResult(
                status="failure",
                duration_s=result.duration_s,
                energy_j=result.energy_j,
                energy_reason=result.energy_reason,
                features={},
                failure_reason="profiler returned undeclared features: " + ", ".join(undeclared),
            )
        self._db.execute(
            "INSERT INTO profile_queries VALUES (?, ?, ?, ?, ?)",
            (query_id, self.session_id, query_index, candidate_id, _canonical_json(result.to_dict())),
        )
        return result

    def remaining_budget(self) -> dict[str, Any]:
        rows = self._query_rows()
        results = [json.loads(row["result_json"]) for row in rows]
        used_duration = sum(result["duration_s"] for result in results)
        known_energy = sum(result["energy_j"] for result in results if result["energy_j"] is not None)
        unavailable = sum(result["energy_j"] is None for result in results)
        reasons: list[str] = []
        if len(rows) >= self.budget.max_queries:
            reasons.append("query count limit reached")
        if used_duration >= self.budget.max_duration_s:
            reasons.append("duration limit reached")
        if self.budget.max_energy_j is not None:
            if unavailable:
                reasons.append("energy cost unavailable under an energy budget")
            elif known_energy >= self.budget.max_energy_j:
                reasons.append("energy limit reached")
        return {
            "used_queries": len(rows),
            "remaining_queries": max(0, self.budget.max_queries - len(rows)),
            "used_duration_s": used_duration,
            "remaining_duration_s": max(0.0, self.budget.max_duration_s - used_duration),
            "known_energy_j": known_energy,
            "unavailable_energy_queries": unavailable,
            "remaining_energy_j": None if self.budget.max_energy_j is None else max(0.0, self.budget.max_energy_j - known_energy),
            "exhausted": bool(reasons),
            "reasons": reasons,
        }

    def seal_recommendation(self, candidate_id: str, rationale: str) -> SealedDecision:
        _require(candidate_id in self.candidates, f"recommended candidate is not eligible: {candidate_id}")
        _non_empty(rationale, "rationale")
        return self._seal(outcome="recommendation", recommendation=candidate_id, abstention_reason="", rationale=rationale)

    def seal_abstention(self, reason: str) -> SealedDecision:
        _non_empty(reason, "abstention reason")
        return self._seal(outcome="abstention", recommendation=None, abstention_reason=reason, rationale="")

    def _seal(self, *, outcome: str, recommendation: Optional[str], abstention_reason: str, rationale: str) -> SealedDecision:
        self._require_open()
        rows = self._query_rows()
        remaining = self.remaining_budget()
        query_ids = tuple(row["query_id"] for row in rows)
        total_energy = None if remaining["unavailable_energy_queries"] else remaining["known_energy_j"]
        sealed_at_ns = self.clock_ns()
        _nonnegative_int(sealed_at_ns, "sealed_at_ns")
        payload = {
            "decision_id": f"decision-{self.session_id}",
            "session_id": self.session_id,
            "selector_revision": self.selector_revision,
            "development_data_sha256": self.development_data_sha256,
            "outcome": outcome,
            "recommendation": recommendation,
            "abstention_reason": abstention_reason,
            "rationale": rationale,
            "query_ids": list(query_ids),
            "profiling_query_count": len(rows),
            "profiling_duration_s": remaining["used_duration_s"],
            "profiling_energy_j": total_energy,
            "unavailable_energy_queries": remaining["unavailable_energy_queries"],
            "sealed_at_ns": sealed_at_ns,
        }
        seal_sha256 = _digest(_canonical_json(payload))
        decision_data = dict(payload)
        decision_data["seal_sha256"] = seal_sha256
        decision_json = _canonical_json(decision_data)
        cursor = self._db.execute(
            "UPDATE selector_sessions SET state = 'sealed', decision_json = ?, decision_sha256 = ? WHERE session_id = ? AND state = 'open'",
            (decision_json, seal_sha256, self.session_id),
        )
        if cursor.rowcount != 1:
            raise SelectorConflictError("selector decision was sealed concurrently")
        return SealedDecision.from_dict(decision_data)

    def decision(self) -> Optional[SealedDecision]:
        row = self._db.execute(
            "SELECT decision_json FROM selector_sessions WHERE session_id = ?", (self.session_id,)
        ).fetchone()
        return SealedDecision.from_dict(json.loads(row["decision_json"])) if row["decision_json"] else None

    def open_reference(self, outcomes: Mapping[str, Any]) -> Mapping[str, Any]:
        decision = self.decision()
        if decision is None:
            raise ReferenceAccessError("reference outcomes are unavailable until the selector decision is sealed")
        _require(set(outcomes) == set(self.candidates), "reference outcomes must cover exactly the eligible candidates")
        outcomes_json = _canonical_json(dict(outcomes))
        digest = _digest(outcomes_json)
        row = self._db.execute(
            "SELECT outcomes_sha256 FROM reference_results WHERE session_id = ?", (self.session_id,)
        ).fetchone()
        if row is not None:
            if row["outcomes_sha256"] != digest:
                raise SelectorConflictError("reference outcomes are already opened with different content")
        else:
            opened_at_ns = self.clock_ns()
            _nonnegative_int(opened_at_ns, "opened_at_ns")
            _require(opened_at_ns >= decision.sealed_at_ns, "reference open timestamp precedes decision seal")
            self._db.execute(
                "INSERT INTO reference_results VALUES (?, ?, ?, ?)",
                (self.session_id, outcomes_json, digest, opened_at_ns),
            )
        return json.loads(outcomes_json)

    def record_live_evaluation(
        self, *, setting_id: str, evidence_sha256: str, metadata: Mapping[str, Any] | None = None
    ) -> None:
        decision = self.decision()
        if decision is None:
            raise ReferenceAccessError("live evaluation is unavailable until the selector decision is sealed")
        if decision.outcome != "recommendation":
            raise ReferenceAccessError("an abstention has no selected live setting")
        if setting_id != decision.recommendation:
            raise ReferenceAccessError("live setting must equal the sealed recommendation")
        _sha256(evidence_sha256, "evidence_sha256")
        metadata_json = _canonical_json(dict(metadata or {}))
        row = self._db.execute(
            "SELECT setting_id, evidence_sha256, metadata_json FROM live_evaluations WHERE session_id = ?",
            (self.session_id,),
        ).fetchone()
        expected = (setting_id, evidence_sha256, metadata_json)
        if row is not None:
            if tuple(row) != expected:
                raise SelectorConflictError("live evaluation is already recorded with different content")
            return
        self._db.execute(
            "INSERT INTO live_evaluations VALUES (?, ?, ?, ?)",
            (self.session_id, setting_id, evidence_sha256, metadata_json),
        )

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        session = self._db.execute(
            "SELECT * FROM selector_sessions WHERE session_id = ?", (self.session_id,)
        ).fetchone()
        if _digest(session["definition_json"]) != session["definition_sha256"]:
            errors.append("session definition hash mismatch")
        try:
            definition = json.loads(session["definition_json"])
            if _canonical_json(definition) != session["definition_json"]:
                errors.append("session definition is not canonical JSON")
        except Exception as error:
            errors.append(f"invalid session definition: {error}")
        rows = self._query_rows()
        if [row["query_index"] for row in rows] != list(range(1, len(rows) + 1)):
            errors.append("query indexes are not contiguous")
        for row in rows:
            if row["candidate_id"] not in self.candidates:
                errors.append(f"{row['query_id']}: candidate is not eligible")
            try:
                result = ProfileResult(**json.loads(row["result_json"]))
                if _canonical_json(result.to_dict()) != row["result_json"]:
                    errors.append(f"{row['query_id']}: result is not canonical")
            except Exception as error:
                errors.append(f"{row['query_id']}: invalid profile result: {error}")
        try:
            decision = self.decision()
        except Exception as error:
            decision = None
            errors.append(f"invalid sealed decision: {error}")
        if session["state"] == "sealed" and decision is None:
            errors.append("sealed session has no decision")
        if decision is not None and decision.seal_sha256 != session["decision_sha256"]:
            errors.append("decision seal hash mismatch")
        if decision is not None:
            decision_payload = decision.to_dict()
            decision_payload.pop("seal_sha256")
            if _digest(_canonical_json(decision_payload)) != decision.seal_sha256:
                errors.append("sealed decision content hash mismatch")
            if (
                decision.session_id != self.session_id
                or decision.selector_revision != self.selector_revision
                or decision.development_data_sha256 != self.development_data_sha256
            ):
                errors.append("sealed decision identity/provenance mismatch")
            remaining = self.remaining_budget()
            expected_energy = None if remaining["unavailable_energy_queries"] else remaining["known_energy_j"]
            if decision.query_ids != tuple(row["query_id"] for row in rows):
                errors.append("sealed decision query links mismatch")
            if (
                decision.profiling_query_count != len(rows)
                or decision.profiling_duration_s != remaining["used_duration_s"]
                or decision.profiling_energy_j != expected_energy
                or decision.unavailable_energy_queries != remaining["unavailable_energy_queries"]
            ):
                errors.append("sealed decision profiling costs mismatch")
        reference = self._db.execute(
            "SELECT * FROM reference_results WHERE session_id = ?", (self.session_id,)
        ).fetchone()
        if reference is not None:
            if decision is None:
                errors.append("reference outcomes were opened before a decision seal")
            if not isinstance(reference["opened_at_ns"], int) or isinstance(reference["opened_at_ns"], bool):
                errors.append("reference outcomes timestamp must be an integer")
            elif decision is not None and reference["opened_at_ns"] < decision.sealed_at_ns:
                errors.append("reference outcomes timestamp precedes the decision seal")
            if _digest(reference["outcomes_json"]) != reference["outcomes_sha256"]:
                errors.append("reference outcomes hash mismatch")
            try:
                outcomes = json.loads(reference["outcomes_json"])
                if set(outcomes) != set(self.candidates):
                    errors.append("reference outcomes do not cover exactly the eligible candidates")
            except Exception as error:
                errors.append(f"invalid reference outcomes: {error}")
        live = self._db.execute(
            "SELECT * FROM live_evaluations WHERE session_id = ?", (self.session_id,)
        ).fetchone()
        if live is not None and (decision is None or live["setting_id"] != decision.recommendation):
            errors.append("live setting differs from sealed recommendation")
        if live is not None:
            try:
                _sha256(live["evidence_sha256"], "live evidence_sha256")
                metadata = json.loads(live["metadata_json"])
                if not isinstance(metadata, dict) or _canonical_json(metadata) != live["metadata_json"]:
                    errors.append("live evaluation metadata is not a canonical JSON object")
            except Exception as error:
                errors.append(f"invalid live evaluation: {error}")
        return {
            "valid": not errors,
            "errors": errors,
            "state": session["state"],
            "query_count": len(rows),
            "budget": self.remaining_budget(),
            "reference_opened": reference is not None,
            "live_evaluation_recorded": live is not None,
        }

    def export_selection(self, output_dir: Path | str) -> dict[str, Path]:
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        query_path = destination / "profiling-queries.jsonl"
        decision_path = destination / "sealed-decision.json"
        validation_path = destination / "selection-validation.json"
        query_lines = [
            _canonical_json({
                "query_id": row["query_id"], "query_index": row["query_index"],
                "candidate_id": row["candidate_id"], "result": json.loads(row["result_json"]),
            })
            for row in self._query_rows()
        ]
        decision = self.decision()
        self._atomic_text(query_path, "\n".join(query_lines) + ("\n" if query_lines else ""))
        self._atomic_text(
            decision_path,
            json.dumps(decision.to_dict() if decision else None, sort_keys=True, indent=2, allow_nan=False) + "\n",
        )
        self._atomic_text(
            validation_path, json.dumps(self.validate(), sort_keys=True, indent=2, allow_nan=False) + "\n"
        )
        return {"queries": query_path, "decision": decision_path, "validation": validation_path}

    def export_reference(self, output_dir: Path | str) -> dict[str, Path]:
        if self.decision() is None:
            raise ReferenceAccessError("reference export is unavailable until the selector decision is sealed")
        reference = self._db.execute(
            "SELECT * FROM reference_results WHERE session_id = ?", (self.session_id,)
        ).fetchone()
        if reference is None:
            raise ReferenceAccessError("reference outcomes have not been opened")
        live = self._db.execute(
            "SELECT * FROM live_evaluations WHERE session_id = ?", (self.session_id,)
        ).fetchone()
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        reference_path = destination / "reference-results.json"
        live_path = destination / "live-evaluation.json"
        self._atomic_text(reference_path, json.dumps({
            "outcomes": json.loads(reference["outcomes_json"]),
            "outcomes_sha256": reference["outcomes_sha256"],
            "opened_at_ns": reference["opened_at_ns"],
        }, sort_keys=True, indent=2, allow_nan=False) + "\n")
        live_value = None if live is None else {
            "setting_id": live["setting_id"], "evidence_sha256": live["evidence_sha256"],
            "metadata": json.loads(live["metadata_json"]),
        }
        self._atomic_text(live_path, json.dumps(live_value, sort_keys=True, indent=2, allow_nan=False) + "\n")
        return {"reference": reference_path, "live_evaluation": live_path}

    def _require_open(self) -> None:
        state = self._db.execute(
            "SELECT state FROM selector_sessions WHERE session_id = ?", (self.session_id,)
        ).fetchone()["state"]
        if state != "open":
            raise SelectorConflictError("selector decision is already sealed")

    def _query_rows(self) -> list[sqlite3.Row]:
        return self._db.execute(
            "SELECT * FROM profile_queries WHERE session_id = ? ORDER BY query_index", (self.session_id,)
        ).fetchall()

    @staticmethod
    def _atomic_text(path: Path, content: str) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)


__all__ = [
    "BudgetExhaustedError", "ProfileResult", "ProfilingBudget", "ReferenceAccessError",
    "RestrictedSelectorAPI", "SealedDecision", "Selector", "SelectorBoundary",
    "SelectorBoundaryError", "SelectorConflictError",
]
