"""Fixture tests for AL2 bounded tool execution."""

import threading
import time
from pathlib import Path
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

    def __getstate__(self):
        return {"delay": self.delay}

    def __setstate__(self, state):
        self.__init__(state["delay"])

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

    def __getstate__(self):
        return {}

    def __setstate__(self, state):
        self.__init__()

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
    assert executor.max_observed_concurrency == 2
    starts = {event["call_id"]: event["monotonic_ns"] for event in events if event["event"] == "start"}
    ends = {event["call_id"]: event["monotonic_ns"] for event in events if event["event"] == "end"}
    assert starts["join"] >= max(ends["north"], ends["south"])


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


class BodyProbe:
    def __getstate__(self):
        return {}

    def __setstate__(self, state):
        self.deserialized_ns = time.monotonic_ns()

    def execute(self, marker, workers=1):
        entered = time.monotonic_ns()
        Path(marker).write_text("finished")
        return dict(deserialized_ns=self.deserialized_ns, entered_ns=entered,
                    returned_ns=time.monotonic_ns())


def test_tool_body_brackets_exclude_deserialization_and_do_not_wait_for_observer(tmp_path):
    marker = tmp_path / "finished"
    events = []

    def observe(event):
        events.append(event)
        if event["event"] == "body_start":
            # If the child waits for the observer, this cannot complete. This
            # exercises callback overlap without padding tool execution time.
            until = time.monotonic() + 3
            while not marker.exists() and time.monotonic() < until:
                time.sleep(0.002)
            assert marker.exists(), "tool must progress independently of observer"

    outcome = BoundedToolExecutor({"probe": BodyProbe()}, event_sink=observe).execute(
        [ToolCall("probe", "probe", {"marker": str(marker)})]
    )["probe"]
    assert outcome.status == "completed"
    stamps = {e["event"]: e["monotonic_ns"] for e in events}
    assert list(stamps) == ["ready", "start", "body_start", "body_end", "end"]
    assert stamps["start"] <= outcome.result["deserialized_ns"] <= stamps["body_start"]
    assert stamps["body_start"] <= outcome.result["entered_ns"]
    assert outcome.result["returned_ns"] <= stamps["body_end"] <= stamps["end"]
    assert all(e["observed_ns"] >= e["monotonic_ns"] for e in events)


def test_tool_body_failure_keeps_brackets_and_error():
    def broken():
        raise ValueError("body failed")

    events = []
    outcome = BoundedToolExecutor({"broken": broken}, event_sink=events.append).execute(
        [ToolCall("broken", "broken", {})]
    )["broken"]
    assert outcome.status == "failed"
    assert "body failed" in outcome.error
    assert [e["event"] for e in events] == ["ready", "start", "body_start", "body_end", "end"]
