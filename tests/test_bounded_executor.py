"""Fixture tests for AL2 bounded tool execution."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.execution.tools.real_tools import CodeExecutorTool
from studies.energy_diagnosis.workloads.bounded_executor import (
    BoundedToolExecutor,
    GraphInputError,
    ToolCall,
)


class TimedTool:
    def __init__(self, delay=0.04):
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def execute(self, value, workers=1):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delay)
            return {"value": value, "workers": workers}
        finally:
            with self.lock:
                self.active -= 1


class WorkerProbe:
    def __init__(self):
        self.thread_names = set()
        self.lock = threading.Lock()

    def execute(self, repetitions, workers=1):
        def work(_):
            with self.lock:
                self.thread_names.add(threading.current_thread().name)
            time.sleep(0.01)
            return 1

        with ThreadPoolExecutor(max_workers=workers) as pool:
            values = list(pool.map(work, range(repetitions)))
        return {"total": sum(values), "workers_observed": len(self.thread_names)}


def test_ready_calls_are_bounded_and_dependency_starts_after_parent():
    tool = TimedTool()
    events = []
    executor = BoundedToolExecutor(
        {"timed": tool}, max_concurrent_calls=2, workers_per_tool=1, event_sink=events.append
    )

    result = executor.execute(
        [
            ToolCall("north", "timed", {"value": "north"}),
            ToolCall("south", "timed", {"value": "south"}),
            ToolCall("join", "timed", {"value": "$result:north"}, ("north", "south")),
        ]
    )

    assert result["north"].result == {"value": "north", "workers": 1}
    assert result["south"].result == {"value": "south", "workers": 1}
    assert result["join"].status == "completed"
    assert executor.max_observed_concurrency <= 2
    assert tool.max_active <= 2
    starts = {event["call_id"]: event["monotonic_ns"] for event in events if event["event"] == "start"}
    assert starts["join"] >= max(starts["north"], starts["south"])


def test_worker_setting_changes_real_worker_execution():
    one_probe = WorkerProbe()
    four_probe = WorkerProbe()
    one = BoundedToolExecutor({"probe": one_probe}, workers_per_tool=1).execute(
        [ToolCall("one", "probe", {"repetitions": 4})]
    )
    four = BoundedToolExecutor({"probe": four_probe}, workers_per_tool=4).execute(
        [ToolCall("four", "probe", {"repetitions": 4})]
    )

    assert one["one"].result["total"] == 4
    assert four["four"].result["total"] == 4
    assert one["one"].result["workers_observed"] == 1
    assert four["four"].result["workers_observed"] >= 2


def test_existing_code_tool_performs_real_computation():
    result = BoundedToolExecutor({"code": CodeExecutorTool()}, workers_per_tool=1).execute(
        [ToolCall("sum", "code", {"code": "print(sum([2, 3]))"})]
    )

    assert result["sum"].status == "completed"
    assert result["sum"].result["output"].strip() == "5"


@pytest.mark.parametrize("kwargs", [{"max_concurrent_calls": 3}, {"workers_per_tool": 2}])
def test_only_eligible_controls_are_accepted(kwargs):
    with pytest.raises(GraphInputError):
        BoundedToolExecutor({"timed": TimedTool()}, **kwargs)


def test_missing_dependency_and_cycles_are_rejected():
    executor = BoundedToolExecutor({"timed": TimedTool()})

    with pytest.raises(GraphInputError, match="missing dependency"):
        executor.execute([ToolCall("child", "timed", {}, ("absent",))])
    with pytest.raises(GraphInputError, match="dependency cycle"):
        executor.execute([ToolCall("a", "timed", {}, ("b",)), ToolCall("b", "timed", {}, ("a",))])


def test_timeout_is_recorded_and_pending_dependents_are_skipped():
    executor = BoundedToolExecutor(
        {"timed": TimedTool(delay=0.2)}, timeout_seconds=0.01
    )
    result = executor.execute([
        ToolCall("slow", "timed", {"value": "slow"}),
        ToolCall("after", "timed", {"value": "after"}, ("slow",)),
    ])

    assert result["slow"].status == "timed_out"
    assert result["after"].status == "skipped"
