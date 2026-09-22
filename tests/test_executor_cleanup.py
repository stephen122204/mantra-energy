"""Timeout, normalization and real-control regressions from integration review."""

import os
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from studies.energy_diagnosis.workloads.bounded_executor import (
    BoundedToolExecutor,
    ToolCall,
    WorkerAwareCalculatorTool,
    GraphInputError,
)
from studies.energy_diagnosis.workloads.trace_replay import (
    TraceExecutor,
    TraceCall,
    TraceInputError,
)


class SideEffectTool:
    def execute(self, path, delay):
        # Observers use existence as readiness: publish complete PID bytes in
        # one rename, never expose an empty file between open and write.
        pending = Path(path + ".started.tmp")
        pending.write_text(str(os.getpid()))
        pending.replace(path + ".started")
        time.sleep(delay)
        Path(path).write_text("finished")
        return True


def read_ready_pid(path):
    # Windows can expose the renamed entry before another process may open it.
    # Wait only for marker readability; termination assertions still use zero grace.
    until = time.monotonic() + 3
    while True:
        try:
            return int(Path(path).read_text())
        except (FileNotFoundError, PermissionError):
            if time.monotonic() >= until:
                raise
            time.sleep(0.002)


def observe_worker_exit(pid, request):
    """Capture identity while live; test exit without waiting for PID removal."""
    if os.name == "nt":
        import _winapi

        handle = _winapi.OpenProcess(_winapi.SYNCHRONIZE, False, pid)
        request.addfinalizer(lambda: _winapi.CloseHandle(handle))
        return lambda: _winapi.WaitForSingleObject(handle, 0) == _winapi.WAIT_OBJECT_0
    import psutil

    process = psutil.Process(pid)

    def exited():
        try:
            process.wait(timeout=0)
        except psutil.TimeoutExpired:
            return False
        return True

    return exited


@pytest.mark.parametrize("success", [True, False])
def test_calculator_envelope_is_normalized(success):
    class Calculator:
        def execute(self, expression):
            return SimpleNamespace(
                success=success,
                result=5 if success else None,
                error="" if success else "bad expression",
            )

    result = BoundedToolExecutor(
        {"c": WorkerAwareCalculatorTool(Calculator())}
    ).execute([ToolCall("c", "c", {"expression": "2+3"})])["c"]
    assert result.status == ("completed" if success else "failed")
    assert result.result == (5 if success else None)
    assert result.workers_observed == 1
    assert bool(result.error) is not success


def test_timed_out_process_stops_before_next_goal(tmp_path, request):
    path = str(tmp_path / "late")
    events = []
    observed_worker = []

    def observe(event):
        events.append(event)
        if event["event"] == "body_start":
            pid = read_ready_pid(path + ".started")
            observed_worker.append(observe_worker_exit(pid, request))
            assert not observed_worker[-1](), "probe must be alive before timeout"

    executor = BoundedToolExecutor(
        {"t": SideEffectTool()}, timeout_seconds=2, event_sink=observe
    )
    result = executor.execute(
        [
            ToolCall("slow", "t", {"path": path, "delay": 20}),
            ToolCall("child", "t", {"path": path + "child", "delay": 0}, ("slow",)),
        ]
    )
    assert Path(path + ".started").exists(), "probe must actually enter the tool"
    assert result["slow"].status == "timed_out"
    assert result["child"].status == "skipped"
    assert any(e["event"] == "body_start" for e in events)
    assert not any(e["event"] == "body_end" for e in events)
    # Windows may retain a terminated PID while process handles remain open.
    # Require the observed worker to have exited already, with no extra grace.
    assert len(observed_worker) == 1
    assert observed_worker[0](), "timed-out worker still executing after cleanup"
    assert not Path(path).exists()
    executor.event_sink = events.append
    followup = executor.execute(
        [ToolCall("fast", "t", {"path": path + "next", "delay": 0})]
    )
    assert followup["fast"].status == "completed"
    assert not Path(path).exists()


@pytest.mark.parametrize("value", [float("inf"), float("nan"), True, 0, -1])
def test_invalid_deadlines_rejected(value):
    with pytest.raises(GraphInputError):
        BoundedToolExecutor({}, timeout_seconds=value)


def test_trace_applies_worker_setting_and_freezes_declared_inputs():
    def tool(inputs, workers=1):
        return {"workers": workers, "input": inputs}

    counter = iter([1, 2])
    runner = TraceExecutor(lambda _: next(counter), {"tool": tool})
    ref = runner.live(
        [
            TraceCall("m", "model", "m", {}),
            TraceCall("t", "tool", "tool", "$result:m", ("m",)),
        ],
        {"workers": 4},
    )
    assert ref.calls[1].output == {"workers": 4, "input": 1}
    replay = runner.conditional_replay(ref, {"workers": 1})
    assert replay.calls[0].output == 2
    assert replay.calls[1].output == {"workers": 1, "input": 1}
    assert replay.frozen_downstream_inputs
    assert set(replay.divergent_call_ids) == {"m", "t"}


def test_trace_rejects_unsupported_workers_and_retains_failure():
    runner = TraceExecutor(lambda _: 1, {"t": lambda value: value})
    with pytest.raises(TraceInputError, match="does not support workers"):
        runner.live([TraceCall("t", "tool", "t", {})], {"workers": 4})

    def fails(_):
        raise ValueError("deliberate")

    trace = TraceExecutor(fails, {}).live([TraceCall("m", "model", "m", {})])
    assert trace.calls[0].status == "failed"
    assert trace.fidelity_status == "failed"
    assert "deliberate" in trace.calls[0].error


class BackgroundChildTool:
    def execute(self):
        import subprocess, sys

        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        return child.pid


def test_tool_descendants_are_reaped_after_success():
    import psutil

    result = BoundedToolExecutor({"spawn": BackgroundChildTool()}).execute(
        [ToolCall("spawn", "spawn", {})]
    )["spawn"]
    assert result.status == "completed", result.error
    try:
        process = psutil.Process(result.result)
        assert process.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        pass


@pytest.mark.parametrize("error_type", [ValueError, OSError])
def test_body_observer_failure_reaps_tool_and_allows_next_goal(tmp_path, error_type, request):
    marker = str(tmp_path / "observer-failure")
    observed_worker = []

    def broken_observer(event):
        if event["event"] == "body_start":
            pid = read_ready_pid(marker + ".started")
            observed_worker.append(observe_worker_exit(pid, request))
            assert not observed_worker[-1](), "probe must be alive before observer failure"
            raise error_type("observer failure")

    executor = BoundedToolExecutor({"t": SideEffectTool()}, event_sink=broken_observer)
    with pytest.raises(error_type, match="observer failure"):
        executor.execute([ToolCall("t", "t", {"path": marker, "delay": 20})])
    # Check termination of the process observed before failure. A bare PID
    # presence check is not a portable wait/exit-status check (nor PID identity).
    # Zero timeout requires it to have exited already when execute returned.
    assert observed_worker[0](), "observer-failure worker still executing after cleanup"
    assert not Path(marker).exists()
    executor.event_sink = None
    assert executor.execute([
        ToolCall("next", "t", {"path": marker + "next", "delay": 0})
    ])["next"].status == "completed"


def test_ready_pid_waits_for_read_access(monkeypatch):
    reads = iter([PermissionError("temporarily shared"), "123"])
    def read(self):
        value = next(reads)
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(Path, "read_text", read)
    assert read_ready_pid("fixture.started") == 123
