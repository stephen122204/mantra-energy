"""Execution-backed traces with explicit conditioning and divergence."""

from __future__ import annotations

import hashlib
import inspect
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping

from .bounded_executor import BoundedToolExecutor, ToolCall, _resolve_args

TRACE_VERSION = "trace-v2"


def _hash(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False
        ).encode()
    ).hexdigest()


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
    status: str = "completed"
    error: str = ""


@dataclass(frozen=True)
class ExecutionTrace:
    trace_version: str
    mode: str
    calls: tuple[TraceCall, ...]
    events: tuple[dict[str, Any], ...]
    trace_hash: str
    reference_trace_hash: str = ""
    frozen_downstream_inputs: bool = False
    divergent_call_ids: tuple[str, ...] = ()
    fidelity_status: str = "live"


class TraceInputError(ValueError):
    pass


class TraceRecorder:
    def __init__(self):
        self._calls = []
        self._events = []

    def record(
        self,
        call_id,
        kind,
        name,
        inputs,
        output,
        depends_on=(),
        controls=None,
        status="completed",
        error="",
    ):
        if kind not in {"model", "tool"}:
            raise TraceInputError("call kind must be model or tool")
        if any(c.call_id == call_id for c in self._calls):
            raise TraceInputError(f"duplicate call ID: {call_id}")
        self._calls.append(
            TraceCall(
                call_id,
                kind,
                name,
                inputs,
                depends_on,
                dict(controls or {}),
                output,
                _hash(output),
                status,
                error,
            )
        )
        self._events.append(
            dict(
                event="complete",
                call_id=call_id,
                kind=kind,
                status=status,
                error=error,
                monotonic_ns=time.monotonic_ns(),
            )
        )

    def mark(self, event, call_id, kind):
        if event not in {"ready", "start"}:
            raise TraceInputError("unsupported trace event")
        self._events.append(
            dict(
                event=event,
                call_id=call_id,
                kind=kind,
                monotonic_ns=time.monotonic_ns(),
            )
        )

    def build(self, mode, reference=None):
        if mode not in {"live", "conditional_replay"} or not self._calls:
            raise TraceInputError("trace needs calls and a supported mode")
        divergent = ()
        if reference:
            expected = {c.call_id: c for c in reference.calls}
            divergent = tuple(
                c.call_id
                for c in self._calls
                if c.output_hash != expected[c.call_id].output_hash
                or c.status != expected[c.call_id].status
            )
        failed = any(c.status != "completed" for c in self._calls)
        fidelity = (
            "failed"
            if failed
            else ("divergent" if divergent else ("valid" if reference else "live"))
        )
        payload = dict(
            trace_version=TRACE_VERSION,
            mode=mode,
            calls=[asdict(c) for c in self._calls],
            reference_trace_hash=reference.trace_hash if reference else "",
            frozen_downstream_inputs=bool(reference),
            divergent_call_ids=divergent,
            fidelity_status=fidelity,
        )
        return ExecutionTrace(
            TRACE_VERSION,
            mode,
            tuple(self._calls),
            tuple(self._events),
            _hash(payload),
            payload["reference_trace_hash"],
            bool(reference),
            divergent,
            fidelity,
        )


@dataclass
class _TraceTool:
    runner: Any

    def execute(self, inputs, workers=1):
        execute = getattr(self.runner, "execute", self.runner)
        if "workers" in inspect.signature(execute).parameters:
            return execute(inputs, workers=workers)
        return execute(inputs)


class TraceExecutor:
    """Batch consecutive tool nodes through the bounded executor.

    Model callbacks must enforce their own runtime request deadline. Replay
    physically invokes them again while explicitly freezing recorded inputs.
    Tool worker settings are accepted only by runners that implement workers.
    """

    def __init__(self, model_runner: Callable, tool_runners: Mapping[str, Callable]):
        self.model_runner = model_runner
        self.tool_runners = dict(tool_runners)

    def live(self, calls, controls=None):
        return self._run(calls, "live", controls or {})

    def conditional_replay(self, reference, controls=None):
        if reference.trace_version != TRACE_VERSION or reference.mode not in {
            "live",
            "conditional_replay",
        }:
            raise TraceInputError("unsupported reference trace")
        recorder = TraceRecorder()
        recorder._calls = list(reference.calls)
        # Verify immutable call contents against the same hash input. A replay
        # reference is accepted as a source too, retaining its existing metadata.
        payload = dict(
            trace_version=reference.trace_version,
            mode=reference.mode,
            calls=[asdict(c) for c in reference.calls],
            reference_trace_hash=reference.reference_trace_hash,
            frozen_downstream_inputs=reference.frozen_downstream_inputs,
            divergent_call_ids=reference.divergent_call_ids,
            fidelity_status=reference.fidelity_status,
        )
        if _hash(payload) != reference.trace_hash:
            raise TraceInputError("reference trace hash mismatch")
        return self._run(
            list(reference.calls), "conditional_replay", controls or {}, reference
        )

    def _run(self, calls, mode, controls, reference=None):
        allowed = {"workers", "max_concurrent_calls", "timeout_seconds"}
        if set(controls) - allowed or any(
            set(c.controls) - allowed - {"workers_observed"} for c in calls
        ):
            raise TraceInputError("unsupported execution control")
        ids = [c.call_id for c in calls]
        if len(ids) != len(set(ids)):
            raise TraceInputError("duplicate call ID")
        known = set()
        for c in calls:
            if any(d not in known for d in c.depends_on):
                raise TraceInputError(
                    f"dependency not complete in declared graph: {c.call_id}"
                )
            if c.kind not in {"model", "tool"}:
                raise TraceInputError("invalid call kind")
            if c.kind == "tool" and c.name not in self.tool_runners:
                raise TraceInputError(f"missing tool runner: {c.name}")
            known.add(c.call_id)
        recorder, completed = TraceRecorder(), {}
        index = 0
        while index < len(calls):
            call = calls[index]
            if call.kind == "model":
                recorder.mark("ready", call.call_id, call.kind)
                recorder.mark("start", call.call_id, call.kind)
                inputs = (
                    call.inputs
                    if reference
                    else _resolve_inputs(call.inputs, completed)
                )
                try:
                    output = self.model_runner(inputs)
                    status, error = "completed", ""
                except Exception as exc:
                    output, status, error = (
                        None,
                        "failed",
                        f"{type(exc).__name__}: {exc}",
                    )
                recorder.record(
                    call.call_id,
                    call.kind,
                    call.name,
                    inputs,
                    output,
                    call.depends_on,
                    {**call.controls, **controls},
                    status,
                    error,
                )
                completed[call.call_id] = output
                index += 1
                if status != "completed":
                    break
                continue
            group = []
            while index < len(calls) and calls[index].kind == "tool":
                group.append(calls[index])
                index += 1
            settings = [
                {**{k: v for k, v in c.controls.items() if k in allowed}, **controls}
                for c in group
            ]
            if any(s != settings[0] for s in settings):
                raise TraceInputError(
                    "a tool batch must have one explicit control setting"
                )
            setting = settings[0]
            workers = setting.get("workers", 1)
            for c in group:
                runner = getattr(
                    self.tool_runners[c.name], "execute", self.tool_runners[c.name]
                )
                if (
                    workers != 1
                    and "workers" not in inspect.signature(runner).parameters
                ):
                    raise TraceInputError(f"tool {c.name} does not support workers")
            group_ids = {c.call_id for c in group}
            inputs = {
                c.call_id: (
                    c.inputs
                    if reference
                    else _resolve_inputs(c.inputs, completed, group_ids)
                )
                for c in group
            }
            outcomes = BoundedToolExecutor(
                {
                    name: _TraceTool(runner)
                    for name, runner in self.tool_runners.items()
                },
                max_concurrent_calls=setting.get("max_concurrent_calls", 1),
                workers_per_tool=workers,
                timeout_seconds=setting.get("timeout_seconds", 10),
                event_sink=recorder._events.append,
            ).execute(
                [
                    ToolCall(
                        c.call_id,
                        c.name,
                        {"inputs": inputs[c.call_id]},
                        tuple(d for d in c.depends_on if d in group_ids),
                    )
                    for c in group
                ]
            )
            for c in group:
                outcome = outcomes[c.call_id]
                resolved = (
                    inputs[c.call_id]
                    if reference or outcome.status != "completed"
                    else _resolve_args(inputs[c.call_id], outcomes)
                )
                recorder.record(
                    c.call_id,
                    c.kind,
                    c.name,
                    resolved,
                    outcome.result,
                    c.depends_on,
                    {**setting, "workers_observed": outcome.workers_observed},
                    outcome.status,
                    outcome.error or "",
                )
                completed[c.call_id] = outcome.result
            if any(o.status != "completed" for o in outcomes.values()):
                break
        return recorder.build(mode, reference)


def _resolve_inputs(inputs, completed, future_ids=()):
    if isinstance(inputs, str) and inputs.startswith("$result:"):
        key = inputs.removeprefix("$result:")
        if key in future_ids:
            return inputs
        if key not in completed:
            raise TraceInputError(f"missing result: {key}")
        return completed[key]
    if isinstance(inputs, dict):
        return {
            key: _resolve_inputs(value, completed, future_ids)
            for key, value in inputs.items()
        }
    if isinstance(inputs, list):
        return [_resolve_inputs(value, completed, future_ids) for value in inputs]
    return inputs
