"""AL4 trace and execution-backed replay tests."""

import pytest

from studies.energy_diagnosis.workloads.trace_replay import (
    TraceCall,
    TraceExecutor,
    TraceInputError,
)


def runners(calls):
    def model(value):
        calls.append(("model", value))
        return {"plan": value["prompt"] + "!"}

    def summarize(value):
        calls.append(("tool", value))
        return {"length": len(value["plan"])}

    return TraceExecutor(model, {"summarize": summarize})


def test_live_trace_records_hashes_dependencies_events_and_controls():
    calls = []
    trace = runners(calls).live([
        TraceCall("model-1", "model", "planner", {"prompt": "go"}),
        TraceCall("tool-1", "tool", "summarize", {"plan": "$result:model-1"}, ("model-1",)),
    ], {"workers": 1})

    assert trace.mode == "live"
    assert trace.trace_version == "trace-v1"
    assert len(trace.trace_hash) == 64
    assert all(call.output_hash for call in trace.calls)
    assert any(event["event"] == "ready" for event in trace.events)
    assert trace.calls[1].inputs == {"plan": {"plan": "go!"}}
    assert calls == [("model", {"prompt": "go"}), ("tool", {"plan": {"plan": "go!"}})]


def test_conditional_replay_executes_runners_again_and_is_labeled():
    calls = []
    executor = runners(calls)
    reference = executor.live([TraceCall("model-1", "model", "planner", {"prompt": "go"})])
    calls.clear()

    replay = executor.conditional_replay(reference, {"workers": 4})

    assert replay.mode == "conditional_replay"
    assert calls == [("model", {"prompt": "go"})]
    assert replay.calls[0].output == reference.calls[0].output
    assert replay.calls[0].controls["workers"] == 4


def test_replay_records_divergent_fresh_outputs():
    count = {"value": 0}

    def model(_):
        count["value"] += 1
        return count["value"]

    executor = TraceExecutor(model, {})
    reference = executor.live([TraceCall("model-1", "model", "planner", {})])
    replay = executor.conditional_replay(reference)

    assert replay.calls[0].output != reference.calls[0].output
    assert replay.calls[0].output_hash != reference.calls[0].output_hash


def test_dependencies_and_missing_runners_are_rejected():
    executor = runners([])
    with pytest.raises(TraceInputError, match="dependency not complete"):
        executor.live([TraceCall("tool", "tool", "summarize", {"x": "$result:missing"}, ("missing",))])
    with pytest.raises(TraceInputError, match="missing tool runner"):
        executor.live([TraceCall("tool", "tool", "unknown", {})])
