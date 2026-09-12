"""Trace capture and execution-backed conditional replay for AL4."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


TRACE_VERSION = "trace-v1"


def _hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class TraceCall:
    call_id: str
    kind: str
    name: str
    inputs: Any
    depends_on: tuple[str, ...] = ()
    controls: Mapping[str, Any] = field(default_factory=dict)
    output: Any = None
    output_hash: str = ""


@dataclass(frozen=True)
class ExecutionTrace:
    trace_version: str
    mode: str
    calls: tuple[TraceCall, ...]
    events: tuple[dict[str, Any], ...]
    trace_hash: str


class TraceInputError(ValueError):
    """Raised when trace data is malformed or mode requirements are violated."""


class TraceRecorder:
    def __init__(self) -> None:
        self._calls: list[TraceCall] = []
        self._events: list[dict[str, Any]] = []

    def record(
        self,
        call_id: str,
        kind: str,
        name: str,
        inputs: Any,
        output: Any,
        depends_on: tuple[str, ...] = (),
        controls: Mapping[str, Any] | None = None,
    ) -> None:
        if kind not in {"model", "tool"}:
            raise TraceInputError("call kind must be model or tool")
        if any(call.call_id == call_id for call in self._calls):
            raise TraceInputError(f"duplicate call ID: {call_id}")
        call = TraceCall(
            call_id=call_id, kind=kind, name=name, inputs=inputs,
            depends_on=depends_on, controls=dict(controls or {}), output=output,
            output_hash=_hash(output),
        )
        self._calls.append(call)
        self._events.append({"event": "complete", "call_id": call_id, "kind": kind, "monotonic_ns": time.monotonic_ns()})

    def mark(self, event: str, call_id: str, kind: str) -> None:
        if event not in {"ready", "start"}:
            raise TraceInputError("unsupported trace event")
        self._events.append({"event": event, "call_id": call_id, "kind": kind, "monotonic_ns": time.monotonic_ns()})

    def build(self, mode: str) -> ExecutionTrace:
        if mode not in {"live", "conditional_replay"}:
            raise TraceInputError("mode must be live or conditional_replay")
        if not self._calls:
            raise TraceInputError("trace cannot be empty")
        trace_hash = _hash([call.__dict__ for call in self._calls])
        return ExecutionTrace(TRACE_VERSION, mode, tuple(self._calls), tuple(self._events), trace_hash)


class TraceExecutor:
    """Execute model and tool callables while recording actual outputs."""

    def __init__(self, model_runner: Callable[[Any], Any], tool_runners: Mapping[str, Callable[[Any], Any]]):
        self.model_runner = model_runner
        self.tool_runners = dict(tool_runners)

    def live(self, calls: list[TraceCall], controls: Mapping[str, Any] | None = None) -> ExecutionTrace:
        return self._run(calls, mode="live", controls=controls or {})

    def conditional_replay(self, reference: ExecutionTrace, controls: Mapping[str, Any] | None = None) -> ExecutionTrace:
        if reference.mode not in {"live", "conditional_replay"}:
            raise TraceInputError("reference trace has invalid mode")
        # Replay calls the model/tool runners again. Frozen reference inputs are
        # retained only as declared conditioning for downstream divergence checks.
        return self._run(list(reference.calls), mode="conditional_replay", controls=controls or {})

    def _run(self, calls: list[TraceCall], mode: str, controls: Mapping[str, Any]) -> ExecutionTrace:
        recorder = TraceRecorder()
        completed: dict[str, Any] = {}
        for call in calls:
            if any(dep not in completed for dep in call.depends_on):
                raise TraceInputError(f"dependency not complete: {call.call_id}")
            recorder.mark("ready", call.call_id, call.kind)
            recorder.mark("start", call.call_id, call.kind)
            inputs = _resolve_inputs(call.inputs, completed)
            if call.kind == "model":
                output = self.model_runner(inputs)
            elif call.name in self.tool_runners:
                output = self.tool_runners[call.name](inputs)
            else:
                raise TraceInputError(f"missing tool runner: {call.name}")
            completed[call.call_id] = output
            recorder.record(call.call_id, call.kind, call.name, inputs, output, call.depends_on, {**call.controls, **controls})
        return recorder.build(mode)


def _resolve_inputs(inputs: Any, completed: Mapping[str, Any]) -> Any:
    if isinstance(inputs, str) and inputs.startswith("$result:"):
        key = inputs.removeprefix("$result:")
        if key not in completed:
            raise TraceInputError(f"missing result: {key}")
        return completed[key]
    if isinstance(inputs, dict):
        return {key: _resolve_inputs(value, completed) for key, value in inputs.items()}
    return inputs
