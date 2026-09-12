"""Finite tool graphs with isolated, terminable worker processes.

Tools must be spawn-picklable. A fresh process owns each call; timeout cleanup
finishes before its end event or the next call. Process startup is included in
the call window. Mutable tool state is not shared across calls.
"""

from __future__ import annotations

import inspect
import math
import multiprocessing as mp
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import cloudpickle
import psutil


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
    workers_observed: int = 0  # zero means not observed, not zero work


@dataclass(frozen=True)
class ToolResultEnvelope:
    success: bool
    result: Any
    error: str | None = None
    workers_observed: int = 0


class GraphInputError(ValueError):
    """Invalid graph or control."""


class BoundedExecutionError(RuntimeError):
    """Owned work could not be terminated; do not finalize measurement."""


def _call_process(connection, tool, call, args, workers):
    try:
        if os.name == "posix":
            os.setsid()
        else:
            from .process_lifetime import create_windows_job

            job_handle = create_windows_job()
        connection.send(("start", time.monotonic_ns()))
        raw = _invoke(cloudpickle.loads(tool), args, workers)
        success = bool(getattr(raw, "success", True))
        outcome = ToolOutcome(
            call.call_id,
            call.tool,
            "completed" if success else "failed",
            getattr(raw, "result", raw),
            getattr(raw, "error", None) or None,
            workers,
            int(getattr(raw, "workers_observed", 0)),
        )
        connection.send(("outcome", outcome))
    except BaseException as exc:
        try:
            connection.send(
                (
                    "outcome",
                    ToolOutcome(
                        call.call_id,
                        call.tool,
                        "failed",
                        error=f"{type(exc).__name__}: {exc}",
                        workers_configured=workers,
                    ),
                )
            )
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()
        # Keep the tree rooted until the parent has enumerated and reaped it.
        # Exiting here could orphan subprocesses before cleanup inspects them.
        threading.Event().wait()


def _reap(process):
    """Kill this tool's process tree and join before allowing further work."""
    if process.pid is None:
        return
    descendants = []
    try:
        descendants = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        pass
    # The child establishes its own process group before executing any tool.
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            # macOS may deny killpg once the group leader has exited.
            # Reap the concrete process handles below and verify survivors.
            pass
    for child in reversed(descendants):
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    if process.is_alive():
        process.kill()
    process.join(timeout=3)
    _, alive = psutil.wait_procs(descendants, timeout=3)
    alive = [p for p in alive if p.is_running() and p.status() != psutil.STATUS_ZOMBIE]
    if process.is_alive() or alive:
        raise BoundedExecutionError("tool processes survived cleanup")
    process.close()


class BoundedToolExecutor:
    def __init__(
        self,
        tools: Mapping[str, Any],
        max_concurrent_calls: int = 1,
        workers_per_tool: int = 1,
        timeout_seconds: float = 10.0,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ):
        if type(max_concurrent_calls) is not int or max_concurrent_calls not in (1, 2):
            raise GraphInputError("max_concurrent_calls must be 1 or 2")
        if type(workers_per_tool) is not int or workers_per_tool not in (1, 4):
            raise GraphInputError("workers_per_tool must be 1 or 4")
        if (
            isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise GraphInputError("timeout_seconds must be finite and positive")
        self.tools = dict(tools)
        self.max_concurrent_calls = max_concurrent_calls
        self.workers_per_tool = workers_per_tool
        self.timeout_seconds = timeout_seconds
        self.event_sink = event_sink
        self.max_observed_concurrency = 0
        self._execute_lock = threading.Lock()

    def execute(self, calls: list[ToolCall]) -> dict[str, ToolOutcome]:
        self._validate_graph(calls)
        if not self._execute_lock.acquire(blocking=False):
            raise BoundedExecutionError("executor is already running a goal")
        ctx = mp.get_context("spawn")
        by_id = {call.call_id: call for call in calls}
        pending = set(by_id)
        completed = {}
        running = {}
        self.max_observed_concurrency = 0
        try:
            while pending or running:
                for call_id in sorted(tuple(pending)):
                    call = by_id[call_id]
                    if not all(dep in completed for dep in call.depends_on):
                        continue
                    if any(
                        completed[dep].status != "completed" for dep in call.depends_on
                    ):
                        pending.remove(call_id)
                        completed[call_id] = ToolOutcome(
                            call_id,
                            call.tool,
                            "skipped",
                            error="dependency did not complete",
                            workers_configured=self.workers_per_tool,
                        )
                        self._emit("end", call, completed[call_id])
                        continue
                    if len(running) >= self.max_concurrent_calls:
                        continue
                    pending.remove(call_id)
                    self._emit("ready", call)
                    parent, child = ctx.Pipe(duplex=False)
                    process = ctx.Process(
                        target=_call_process,
                        args=(
                            child,
                            cloudpickle.dumps(self.tools[call.tool]),
                            call,
                            _resolve_args(call.args, completed),
                            self.workers_per_tool,
                        ),
                    )
                    try:
                        process.start()
                    except Exception as exc:
                        parent.close()
                        child.close()
                        if process.pid is not None:
                            _reap(process)
                        completed[call_id] = ToolOutcome(
                            call_id,
                            call.tool,
                            "failed",
                            error=f"cannot start isolated tool: {exc}",
                            workers_configured=self.workers_per_tool,
                        )
                        self._emit("end", call, completed[call_id])
                        continue
                    child.close()
                    running[call_id] = [process, parent, time.monotonic(), False]
                for call_id, state in list(running.items()):
                    process, connection, admitted, started = state
                    outcome = None
                    try:
                        while connection.poll():
                            kind, value = connection.recv()
                            if kind == "start":
                                state[3] = True
                                self.max_observed_concurrency = max(
                                    self.max_observed_concurrency,
                                    sum(int(item[3]) for item in running.values()),
                                )
                                self._emit("start", by_id[call_id], timestamp=value)
                            else:
                                outcome = value
                                break
                    except (EOFError, OSError):
                        pass
                    if (
                        outcome is None
                        and time.monotonic() - admitted >= self.timeout_seconds
                    ):
                        outcome = ToolOutcome(
                            call_id,
                            by_id[call_id].tool,
                            "timed_out",
                            error=f"timeout after {self.timeout_seconds}s",
                            workers_configured=self.workers_per_tool,
                        )
                    if outcome is None and not process.is_alive():
                        outcome = ToolOutcome(
                            call_id,
                            by_id[call_id].tool,
                            "failed",
                            error=f"tool exited without result (exit {process.exitcode})",
                            workers_configured=self.workers_per_tool,
                        )
                    if outcome is not None:
                        _reap(process)
                        connection.close()
                        del running[call_id]
                        completed[call_id] = outcome
                        self._emit("end", by_id[call_id], outcome)
                if running:
                    time.sleep(0.002)
        finally:
            try:
                for process, connection, _, _ in running.values():
                    _reap(process)
                    connection.close()
            finally:
                self._execute_lock.release()
        return completed

    def _validate_graph(self, calls):
        if not calls:
            raise GraphInputError("goal graph must contain at least one call")
        ids = [c.call_id for c in calls]
        if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(
            set(ids)
        ):
            raise GraphInputError("call IDs must be non-empty and unique")
        by_id = {c.call_id: c for c in calls}
        for call in calls:
            if call.tool not in self.tools:
                raise GraphInputError(f"unknown tool: {call.tool}")
            if any(d not in by_id for d in call.depends_on):
                raise GraphInputError(f"missing dependency for {call.call_id}")
            if not _result_refs(call.args).issubset(set(call.depends_on)):
                raise GraphInputError("result references require explicit dependencies")
        visiting, visited = set(), set()

        def visit(key):
            if key in visiting:
                raise GraphInputError("dependency cycle")
            if key in visited:
                return
            visiting.add(key)
            for dep in by_id[key].depends_on:
                visit(dep)
            visiting.remove(key)
            visited.add(key)

        for key in ids:
            visit(key)

    def _emit(self, event, call, outcome=None, timestamp=None):
        if self.event_sink is None:
            return
        record = dict(
            event=event,
            call_id=call.call_id,
            tool=call.tool,
            monotonic_ns=time.monotonic_ns() if timestamp is None else timestamp,
            depends_on=list(call.depends_on),
            max_concurrent_calls=self.max_concurrent_calls,
            workers_per_tool=self.workers_per_tool,
        )
        if outcome is not None:
            record.update(
                status=outcome.status,
                error=outcome.error,
                workers_observed=outcome.workers_observed,
            )
        self.event_sink(record)


def _result_refs(value):
    if isinstance(value, str) and value.startswith("$result:"):
        return {value.removeprefix("$result:")}
    if isinstance(value, Mapping):
        return set().union(*(_result_refs(v) for v in value.values()), set())
    if isinstance(value, (list, tuple)):
        return set().union(*(_result_refs(v) for v in value), set())
    return set()


def _resolve_args(value, completed):
    if isinstance(value, str) and value.startswith("$result:"):
        key = value.removeprefix("$result:")
        if key not in completed or completed[key].status != "completed":
            raise BoundedExecutionError(f"result dependency unavailable: {key}")
        return completed[key].result
    if isinstance(value, Mapping):
        return {key: _resolve_args(v, completed) for key, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_resolve_args(v, completed) for v in value)
    return value


def _invoke(tool, args, workers):
    execute = getattr(tool, "execute", tool)
    if "workers" in inspect.signature(execute).parameters:
        return execute(**args, workers=workers)
    return execute(**args)


class WorkerAwareCalculatorTool:
    def __init__(self, calculator):
        self.calculator = calculator

    def execute(self, expression: str, repetitions: int = 1, workers: int = 1):
        if repetitions < 1:
            raise GraphInputError("repetitions must be positive")
        observed, lock = set(), threading.Lock()

        def work(_):
            with lock:
                observed.add(threading.get_ident())
            return self.calculator.execute(expression)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(work, range(repetitions)))
        failures = [r for r in results if not r.success]
        if failures:
            return ToolResultEnvelope(False, None, failures[0].error, len(observed))
        values = [r.result for r in results]
        return ToolResultEnvelope(
            True,
            values[0] if all(v == values[0] for v in values) else values,
            workers_observed=len(observed),
        )
