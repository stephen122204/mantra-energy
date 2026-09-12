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
        Path(path + ".started").write_text(str(os.getpid()))
        time.sleep(delay)
        Path(path).write_text("finished")
        return True


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


def test_timed_out_process_stops_before_next_goal(tmp_path):
    path = str(tmp_path / "late")
    events = []
    executor = BoundedToolExecutor(
        {"t": SideEffectTool()}, timeout_seconds=2, event_sink=events.append
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
    import psutil

    assert not psutil.pid_exists(int(Path(path + ".started").read_text()))
    assert not Path(path).exists()
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
