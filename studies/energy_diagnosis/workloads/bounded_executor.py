"""Bounded single-goal execution for independent ready tool calls."""

from __future__ import annotations

import inspect
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    tool: str
    args: Mapping[str, Any]
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolOutcome:
    call_id: str
    tool: str
    status: str
    result: Any = None
    error: str | None = None
    workers_configured: int = 1
    workers_observed: int = 0


class GraphInputError(ValueError):
    """Raised when a goal graph or control is invalid."""


class BoundedExecutionError(RuntimeError):
    """Raised when a graph cannot be completed safely."""


class BoundedToolExecutor:
    """Execute one finite graph with explicit concurrency and worker controls."""

    def __init__(
        self,
        tools: Mapping[str, Any],
        max_concurrent_calls: int = 1,
        workers_per_tool: int = 1,
        timeout_seconds: float = 10.0,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if max_concurrent_calls not in (1, 2):
            raise GraphInputError("max_concurrent_calls must be 1 or 2")
        if workers_per_tool not in (1, 4):
            raise GraphInputError("workers_per_tool must be 1 or 4")
        if timeout_seconds <= 0:
            raise GraphInputError("timeout_seconds must be positive")
        self.tools = dict(tools)
        self.max_concurrent_calls = max_concurrent_calls
        self.workers_per_tool = workers_per_tool
        self.timeout_seconds = timeout_seconds
        self.event_sink = event_sink
        self.max_observed_concurrency = 0
        self._active_calls = 0
        self._active_lock = threading.Lock()

    def execute(self, calls: list[ToolCall]) -> dict[str, ToolOutcome]:
        self._validate_graph(calls)
        by_id = {call.call_id: call for call in calls}
        completed: dict[str, ToolOutcome] = {}
        pending = set(by_id)
        running: dict[str, tuple[Future[ToolOutcome], float]] = {}
        pool = ThreadPoolExecutor(max_workers=self.max_concurrent_calls)
        try:
            while pending or running:
                ready = [
                    by_id[call_id]
                    for call_id in sorted(pending)
                    if all(dep in completed for dep in by_id[call_id].depends_on)
                ]
                while ready and len(running) < self.max_concurrent_calls:
                    call = ready.pop(0)
                    pending.remove(call.call_id)
                    self._emit("ready", call)
                    running[call.call_id] = (
                        pool.submit(self._run_call, call, completed),
                        time.monotonic(),
                    )
                if not running:
                    raise BoundedExecutionError("graph has unresolved dependencies")

                call_id, (future, submitted_at) = next(iter(running.items()))
                call = by_id[call_id]
                remaining = self.timeout_seconds - (time.monotonic() - submitted_at)
                try:
                    outcome = future.result(timeout=max(0.0, remaining))
                except TimeoutError:
                    future.cancel()
                    outcome = ToolOutcome(
                        call_id=call_id,
                        tool=call.tool,
                        status="timed_out",
                        error=f"timeout after {self.timeout_seconds}s",
                        workers_configured=self.workers_per_tool,
                    )
                except Exception as exc:
                    outcome = ToolOutcome(
                        call_id=call_id,
                        tool=call.tool,
                        status="failed",
                        error=str(exc),
                        workers_configured=self.workers_per_tool,
                    )
                running.pop(call_id)
                completed[call_id] = outcome
                self._emit("end", call, outcome)
                if outcome.status != "completed":
                    self._skip_descendants(call_id, by_id, pending, completed)
                    for other_future, _ in running.values():
                        other_future.cancel()
                    pending.difference_update(completed)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return completed

    def _run_call(self, call: ToolCall, completed: Mapping[str, ToolOutcome]) -> ToolOutcome:
        self._emit("start", call)
        with self._active_lock:
            self._active_calls += 1
            self.max_observed_concurrency = max(self.max_observed_concurrency, self._active_calls)
        try:
            args = _resolve_args(call.args, completed)
            raw = _invoke(self.tools[call.tool], args, self.workers_per_tool)
            success = bool(getattr(raw, "success", True))
            result = getattr(raw, "result", raw)
            error = getattr(raw, "error", "") or None
            observed = int(getattr(raw, "workers_observed", 0))
            return ToolOutcome(
                call_id=call.call_id,
                tool=call.tool,
                status="completed" if success else "failed",
                result=result,
                error=error,
                workers_configured=self.workers_per_tool,
                workers_observed=observed,
            )
        finally:
            with self._active_lock:
                self._active_calls -= 1

    @staticmethod
    def _skip_descendants(
        failed_id: str,
        by_id: Mapping[str, ToolCall],
        pending: set[str],
        completed: dict[str, ToolOutcome],
    ) -> None:
        changed = True
        while changed:
            changed = False
            for call_id in sorted(pending):
                dependencies = by_id[call_id].depends_on
                if failed_id in dependencies or any(dep in completed and completed[dep].status != "completed" for dep in dependencies):
                    completed[call_id] = ToolOutcome(
                        call_id=call_id,
                        tool=by_id[call_id].tool,
                        status="skipped",
                        error="dependency did not complete",
                        workers_configured=1,
                    )
                    pending.remove(call_id)
                    changed = True

    def _validate_graph(self, calls: list[ToolCall]) -> None:
        if not calls:
            raise GraphInputError("goal graph must contain at least one call")
        ids = [call.call_id for call in calls]
        if len(ids) != len(set(ids)):
            raise GraphInputError("call IDs must be unique")
        by_id = {call.call_id: call for call in calls}
        for call in calls:
            if call.tool not in self.tools:
                raise GraphInputError(f"unknown tool: {call.tool}")
            if any(dep not in by_id for dep in call.depends_on):
                raise GraphInputError(f"missing dependency for {call.call_id}")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(call_id: str) -> None:
            if call_id in visiting:
                raise GraphInputError("dependency cycle")
            if call_id in visited:
                return
            visiting.add(call_id)
            for dep in by_id[call_id].depends_on:
                visit(dep)
            visiting.remove(call_id)
            visited.add(call_id)

        for call_id in ids:
            visit(call_id)

    def _emit(self, event: str, call: ToolCall, outcome: ToolOutcome | None = None) -> None:
        if self.event_sink is None:
            return
        record: dict[str, Any] = {
            "event": event,
            "call_id": call.call_id,
            "tool": call.tool,
            "monotonic_ns": time.monotonic_ns(),
            "depends_on": list(call.depends_on),
            "max_concurrent_calls": self.max_concurrent_calls,
            "workers_per_tool": self.workers_per_tool,
        }
        if outcome is not None:
            record.update({"status": outcome.status, "error": outcome.error})
        self.event_sink(record)


def _resolve_args(args: Mapping[str, Any], completed: Mapping[str, ToolOutcome]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str) and value.startswith("$result:"):
            dependency_id = value.removeprefix("$result:")
            if dependency_id not in completed or completed[dependency_id].status != "completed":
                raise BoundedExecutionError(f"result dependency unavailable: {dependency_id}")
            resolved[key] = completed[dependency_id].result
        else:
            resolved[key] = value
    return resolved


def _invoke(tool: Any, args: Mapping[str, Any], workers: int) -> Any:
    execute = getattr(tool, "execute", tool)
    if "workers" in inspect.signature(execute).parameters:
        return execute(**args, workers=workers)
    return execute(**args)


class WorkerAwareCalculatorTool:
    """Adapter that performs real CalculatorTool calls across configured workers."""

    def __init__(self, calculator: Any) -> None:
        self.calculator = calculator

    def execute(self, expression: str, repetitions: int = 1, workers: int = 1) -> dict[str, Any]:
        if repetitions < 1:
            raise GraphInputError("repetitions must be positive")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda _: self.calculator.execute(expression), range(repetitions)))
        failures = [result for result in results if not result.success]
        if failures:
            return {"success": False, "result": None, "error": failures[0].error, "workers_observed": min(workers, repetitions)}
        values = [result.result for result in results]
        return {"success": True, "result": values[0] if len(set(values)) == 1 else values, "workers_observed": min(workers, repetitions)}
