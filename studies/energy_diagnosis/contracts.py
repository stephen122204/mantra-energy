"""ED-01 shared record contracts for the energy-diagnosis study (v0.1).

One small, dependency-free module that every component produces or consumes:

    Aldric  (workloads) produces TaskSpec, ExecutionSetting, VerifierResult, SpanEvent
    Alex    (runtime)   produces ModelResponse, SensorSample, MeasurementRecord
    Nitheesh (campaign) consumes all of them and produces ExecutionRecord
    Stephen (analysis)  consumes ExecutionRecord

Design rules (from studies/energy_diagnosis/planning/data-contract.md):

* Records are frozen dataclasses with a stable JSON form (``to_dict`` / ``from_dict``).
* Timestamps are monotonic nanoseconds inside a named ``clock_domain``; wall-clock anchors
  are separate and never subtracted from monotonic values.
* Unknown energy is never zero: a MeasurementRecord with ``status != "valid"`` carries
  ``energy_j = None`` and a non-empty ``reason``.
* Execution status, verifier outcome and measurement status are stored separately.
  Completion is not correctness; a verifier failure is not a measurement failure.
* Every ExecutionRecord is emitted even when the model, collector or verifier failed.
* ``simulated=True`` marks fixture runs; they are never hardware energy evidence.

Field additions are allowed in later minor versions; renames and semantic changes bump
``CONTRACT_VERSION`` and require a migration note in the study README.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

CONTRACT_VERSION = "0.1"

EXECUTION_STATUSES = ("completed", "crashed", "timed_out", "cancelled", "incomplete")
VERIFIER_OUTCOMES = ("pass", "fail", "unavailable")
MEASUREMENT_STATUSES = ("valid", "partial", "invalid", "unavailable")
MODEL_STATUSES = ("completed", "timed_out", "interrupted", "error")
SPAN_KINDS = ("model", "tool", "verify", "wait", "cleanup")
SPAN_STATUSES = ("completed", "failed", "timed_out", "cancelled", "skipped")
SAMPLE_STATUSES = ("ok", "invalid", "wrapped", "reset", "missing")
TOKEN_PROVENANCES = ("provider", "tokenizer", "estimated", "unknown")


class ContractError(ValueError):
    """A record violates the shared contract."""


# --------------------------------------------------------------------------- helpers

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _non_empty(value: Any, name: str) -> None:
    _require(isinstance(value, str) and value.strip() != "", f"{name} must be a non-empty string")


def _one_of(value: Any, allowed: Sequence[str], name: str) -> None:
    _require(value in allowed, f"{name} must be one of {list(allowed)}, got {value!r}")


def _ns(value: Any, name: str, optional: bool = False) -> None:
    if value is None and optional:
        return
    _require(isinstance(value, int) and not isinstance(value, bool) and value >= 0, f"{name} must be a non-negative integer nanosecond value")


def _window(start: Any, end: Any, name: str) -> None:
    _ns(start, f"{name}.start"); _ns(end, f"{name}.end")
    _require(end >= start, f"{name}: end must not precede start")


class _Record:
    """Mixin: dict/JSON conversion with validation on construction from a mapping."""

    def to_dict(self) -> dict[str, Any]:
        return _to_jsonable(dataclasses.asdict(self))

    def to_json(self, **kwargs: Any) -> str:
        kwargs.setdefault("sort_keys", True)
        kwargs.setdefault("indent", 2)
        return json.dumps(self.to_dict(), **kwargs) + "\n"

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]):
        _require(isinstance(raw, Mapping), f"{cls.__name__} must be built from an object")
        names = {f.name for f in fields(cls)}
        unknown = sorted(set(raw) - names)
        _require(not unknown, f"{cls.__name__}: unknown fields {unknown}")
        missing = sorted(n for n in names if n not in raw and _is_required(cls, n))
        _require(not missing, f"{cls.__name__}: missing fields {missing}")
        kwargs = {}
        for f in fields(cls):
            if f.name not in raw:
                continue
            kwargs[f.name] = _coerce(f, raw[f.name])
        return cls(**kwargs)

    @classmethod
    def from_json(cls, text: str):
        return cls.from_dict(json.loads(text))


def _is_required(cls, name: str) -> bool:
    f = next(f for f in fields(cls) if f.name == name)
    return f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING  # type: ignore[attr-defined]


_NESTED = {}


def _coerce(f: dataclasses.Field, value: Any) -> Any:
    nested = _NESTED.get((f.name))
    if nested is None or value is None:
        return tuple(value) if isinstance(value, list) else value
    single, cls = nested
    if single:
        return cls.from_dict(value)
    _require(isinstance(value, list), f"{f.name} must be a list")
    return tuple(cls.from_dict(v) for v in value)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return value


# --------------------------------------------------------------------------- records

@dataclass(frozen=True)
class ExecutionSetting(_Record):
    """One execution configuration under test (Aldric's four controls are four of these)."""

    setting_id: str
    tool_concurrency: bool
    tool_workers: int
    description: str = ""

    def __post_init__(self) -> None:
        _non_empty(self.setting_id, "setting_id")
        _require(isinstance(self.tool_concurrency, bool), "tool_concurrency must be a boolean")
        _require(isinstance(self.tool_workers, int) and self.tool_workers >= 1, "tool_workers must be >= 1")


@dataclass(frozen=True)
class TaskSpec(_Record):
    """Immutable goal contract (workloads -> runner)."""

    task_id: str
    family: str                      # e.g. "data-analysis", "repository-analysis"
    split: str                       # "development" | "held_out"
    asset_sha256: str
    expected_result_sha256: str
    verifier_version: str
    prompt: str
    deadline_s: float
    retry_limit: int
    eligible_settings: tuple[str, ...]   # setting_ids this task may run under
    lineage: str = ""                # where the assets came from (license/provenance note)

    def __post_init__(self) -> None:
        for name in ("task_id", "family", "asset_sha256", "expected_result_sha256", "verifier_version", "prompt"):
            _non_empty(getattr(self, name), name)
        _one_of(self.split, ("development", "held_out"), "split")
        _require(len(self.asset_sha256) == 64 and len(self.expected_result_sha256) == 64, "sha256 fields must be 64 hex characters")
        _require(isinstance(self.deadline_s, (int, float)) and self.deadline_s > 0, "deadline_s must be positive")
        _require(isinstance(self.retry_limit, int) and self.retry_limit >= 0, "retry_limit must be >= 0")
        _require(len(self.eligible_settings) >= 1, "eligible_settings must name at least one setting")


@dataclass(frozen=True)
class ModelResponse(_Record):
    """Normalized model outcome (runtime -> executor). Always emitted, even on failure."""

    request_id: str
    status: str                      # MODEL_STATUSES
    model_hash: str
    started_ns: int
    ended_ns: int
    clock_domain: str
    text: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    token_provenance: str = "unknown"
    error: str = ""

    def __post_init__(self) -> None:
        _non_empty(self.request_id, "request_id"); _non_empty(self.model_hash, "model_hash"); _non_empty(self.clock_domain, "clock_domain")
        _one_of(self.status, MODEL_STATUSES, "status")
        _one_of(self.token_provenance, TOKEN_PROVENANCES, "token_provenance")
        _window(self.started_ns, self.ended_ns, "model_response")
        if self.status == "completed":
            _require(self.text is not None, "a completed response must carry text")
        else:
            _non_empty(self.error, "error (required when status is not completed)")
        for name in ("prompt_tokens", "completion_tokens"):
            v = getattr(self, name)
            _require(v is None or (isinstance(v, int) and v >= 0), f"{name} must be a non-negative integer or null")


@dataclass(frozen=True)
class SpanEvent(_Record):
    """One model/tool/verify/wait/cleanup span with ready/start/end and dependencies (executor -> runner)."""

    span_id: str
    attempt_id: str
    kind: str                        # SPAN_KINDS
    ready_ns: int
    start_ns: int
    end_ns: int
    status: str                      # SPAN_STATUSES
    depends_on: tuple[str, ...] = ()
    workers_configured: Optional[int] = None
    workers_observed: Optional[int] = None
    input_sha256: str = ""
    output_sha256: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        _non_empty(self.span_id, "span_id"); _non_empty(self.attempt_id, "attempt_id")
        _one_of(self.kind, SPAN_KINDS, "kind"); _one_of(self.status, SPAN_STATUSES, "status")
        _ns(self.ready_ns, "ready_ns"); _window(self.start_ns, self.end_ns, f"span {self.span_id}")
        _require(self.start_ns >= self.ready_ns, f"span {self.span_id}: start precedes ready")
        _require(self.span_id not in self.depends_on, f"span {self.span_id} depends on itself")
        for name in ("workers_configured", "workers_observed"):
            v = getattr(self, name)
            _require(v is None or (isinstance(v, int) and v >= 1), f"{name} must be >= 1 or null")


@dataclass(frozen=True)
class SensorSample(_Record):
    """One raw counter read (collector -> runner). Invalid reads are null with a reason."""

    sample_id: str
    session_id: str
    domain_id: str
    acquired_start_ns: int
    acquired_end_ns: int
    unit: str
    status: str = "ok"               # SAMPLE_STATUSES
    value: Optional[float] = None
    reason: str = ""
    counter_generation: int = 0

    def __post_init__(self) -> None:
        for name in ("sample_id", "session_id", "domain_id", "unit"):
            _non_empty(getattr(self, name), name)
        _one_of(self.status, SAMPLE_STATUSES, "status")
        _window(self.acquired_start_ns, self.acquired_end_ns, f"sample {self.sample_id}")
        if self.status == "ok":
            _require(isinstance(self.value, (int, float)), "an ok sample must carry a numeric value")
        else:
            _require(self.value is None, f"a {self.status} sample must carry value=null")
            _non_empty(self.reason, "reason (required when status is not ok)")


@dataclass(frozen=True)
class MeasurementRecord(_Record):
    """Derived energy over one window for one domain (collector -> runner -> analysis).

    Unknown energy is never zero: any status other than ``valid`` requires ``energy_j=None``
    and a reason. ``coverage`` is the fraction of the window backed by valid samples.
    """

    session_id: str
    domain_id: str
    start_ns: int
    end_ns: int
    status: str                      # MEASUREMENT_STATUSES
    method: str                      # e.g. "counter-difference", "trapezoid-power"
    energy_j: Optional[float] = None
    coverage: Optional[float] = None
    reason: str = ""

    def __post_init__(self) -> None:
        for name in ("session_id", "domain_id", "method"):
            _non_empty(getattr(self, name), name)
        _one_of(self.status, MEASUREMENT_STATUSES, "status")
        _window(self.start_ns, self.end_ns, "measurement")
        if self.status == "valid":
            _require(isinstance(self.energy_j, (int, float)) and self.energy_j >= 0, "a valid measurement must carry non-negative energy_j")
            _require(self.coverage is None or self.coverage == 1.0, "a valid measurement has coverage 1.0")
        elif self.status == "partial":
            _require(isinstance(self.energy_j, (int, float)) and self.energy_j >= 0, "a partial measurement must carry the covered energy_j")
            _require(isinstance(self.coverage, (int, float)) and 0 < self.coverage < 1, "a partial measurement needs coverage strictly between 0 and 1")
            _non_empty(self.reason, "reason (required for partial)")
        else:
            _require(self.energy_j is None, f"a {self.status} measurement must carry energy_j=null, never 0")
            _non_empty(self.reason, f"reason (required for {self.status})")


@dataclass(frozen=True)
class VerifierResult(_Record):
    """Independent correctness decision (verifier -> runner). Never copied from the agent's self-report."""

    verifier_version: str
    outcome: str                     # VERIFIER_OUTCOMES
    reason: str
    expected_result_sha256: str = ""
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _non_empty(self.verifier_version, "verifier_version"); _non_empty(self.reason, "reason")
        _one_of(self.outcome, VERIFIER_OUTCOMES, "outcome")

    @classmethod
    def from_data_analysis(cls, result: Mapping[str, Any]) -> "VerifierResult":
        """Adapter for the existing ED-03 verifier output (``verify_answer``)."""
        _require("passed" in result and "verifier_version" in result, "not a data-analysis verifier result")
        return cls(
            verifier_version=str(result["verifier_version"]),
            outcome="pass" if result["passed"] else "fail",
            reason=str(result.get("reason", "ok" if result["passed"] else "failed")),
            expected_result_sha256=str(result.get("expected_result_sha256", "")),
            evidence=tuple(str(v) for v in result.get("evidence", ())),
        )


@dataclass(frozen=True)
class ExecutionRecord(_Record):
    """Immutable ledger row for one attempt of one goal under one setting (runner -> analysis)."""

    goal_execution_id: str
    planned_run_id: str
    session_id: str
    task_id: str
    setting_id: str
    attempt_number: int
    execution_status: str            # EXECUTION_STATUSES
    started_ns: int
    ended_ns: int
    clock_domain: str
    verifier: VerifierResult
    simulated: bool
    model_response: Optional[ModelResponse] = None
    spans: tuple[SpanEvent, ...] = ()
    measurements: tuple[MeasurementRecord, ...] = ()
    contract_version: str = CONTRACT_VERSION
    error: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        for name in ("goal_execution_id", "planned_run_id", "session_id", "task_id", "setting_id", "clock_domain"):
            _non_empty(getattr(self, name), name)
        _require(self.contract_version == CONTRACT_VERSION, f"contract_version must be {CONTRACT_VERSION}")
        _require(isinstance(self.attempt_number, int) and self.attempt_number >= 1, "attempt_number starts at 1")
        _one_of(self.execution_status, EXECUTION_STATUSES, "execution_status")
        _require(isinstance(self.simulated, bool), "simulated must be a boolean")
        _window(self.started_ns, self.ended_ns, "execution")
        if self.execution_status != "completed":
            _non_empty(self.error, "error (required when execution_status is not completed)")
        # spans: unique ids, dependencies resolvable, acyclic, no dependent starts before its parent ends
        ids = [s.span_id for s in self.spans]
        _require(len(ids) == len(set(ids)), "span ids must be unique")
        by_id = {s.span_id: s for s in self.spans}
        for s in self.spans:
            _require(s.start_ns >= self.started_ns and s.end_ns <= self.ended_ns, f"span {s.span_id} lies outside the execution window")
            for dep in s.depends_on:
                _require(dep in by_id, f"span {s.span_id} depends on unknown span {dep}")
                _require(s.start_ns >= by_id[dep].end_ns, f"span {s.span_id} started before its dependency {dep} ended")
        _require(not _has_cycle(by_id), "span dependencies contain a cycle")
        for m in self.measurements:
            _require(m.session_id == self.session_id, f"measurement on {m.domain_id} belongs to another session")
            _require(m.start_ns <= self.ended_ns and m.end_ns >= self.started_ns, f"measurement on {m.domain_id} does not overlap the execution window")
        # completion is not correctness: a completed run may still fail verification; a failed run cannot pass
        if self.execution_status != "completed":
            _require(self.verifier.outcome != "pass", "a run that did not complete cannot have a passing verifier outcome")

    @property
    def energy_by_domain(self) -> dict[str, Optional[float]]:
        """Energy per domain; None where the measurement is not valid. Never substitutes 0."""
        return {m.domain_id: (m.energy_j if m.status == "valid" else None) for m in self.measurements}

    @property
    def verified(self) -> bool:
        return self.execution_status == "completed" and self.verifier.outcome == "pass"


def _has_cycle(by_id: Mapping[str, SpanEvent]) -> bool:
    state: dict[str, int] = {}

    def visit(node: str) -> bool:
        if state.get(node) == 1:
            return True
        if state.get(node) == 2:
            return False
        state[node] = 1
        for dep in by_id[node].depends_on:
            if dep in by_id and visit(dep):
                return True
        state[node] = 2
        return False

    return any(visit(n) for n in by_id)


_NESTED.update({
    "verifier": (True, VerifierResult),
    "model_response": (True, ModelResponse),
    "spans": (False, SpanEvent),
    "measurements": (False, MeasurementRecord),
})

RECORD_TYPES = {
    "ExecutionSetting": ExecutionSetting, "TaskSpec": TaskSpec, "ModelResponse": ModelResponse,
    "SpanEvent": SpanEvent, "SensorSample": SensorSample, "MeasurementRecord": MeasurementRecord,
    "VerifierResult": VerifierResult, "ExecutionRecord": ExecutionRecord,
}

EXAMPLES_DIR = Path(__file__).resolve().parent / "fixtures" / "contract_examples"


def load_example(name: str):
    """Load ``fixtures/contract_examples/<name>.json`` as the record type named in its ``_type`` key."""
    raw = json.loads((EXAMPLES_DIR / f"{name}.json").read_text(encoding="utf-8"))
    kind = raw.pop("_type")
    return RECORD_TYPES[kind].from_dict(raw)


__all__ = ["CONTRACT_VERSION", "ContractError", "ExecutionSetting", "TaskSpec", "ModelResponse", "SpanEvent",
           "SensorSample", "MeasurementRecord", "VerifierResult", "ExecutionRecord", "RECORD_TYPES", "load_example"]
