"""chat-tools-v1 protocol: parsing, model-visible history, outcomes and deadlines."""
import json
import time
from pathlib import Path

import pytest

from studies.energy_diagnosis.agent_protocol import (
    SUBMIT, Conversation, function_tools, parse_response, outcome_class, strict_loads, turn_seed, visible,
)
from studies.energy_diagnosis.moe import run as campaign
from studies.energy_diagnosis.workloads.bounded_executor import BoundedToolExecutor, ToolCall


def call(name, arguments):
    return f"<tool_call>\n{json.dumps(dict(name=name, arguments=arguments))}\n</tool_call>"


def test_parse_tool_calls_answer_and_visible_text():
    d = parse_response("Checking schema.\n" + call("sql", {"action": "schema"}) + call("sql", {"action": "query", "sql": "SELECT 1"}))
    assert d.kind == "tool_calls" and d.calls == (("sql", {"action": "schema"}), ("sql", {"action": "query", "sql": "SELECT 1"}))
    assert d.content == "Checking schema."
    d = parse_response(call(SUBMIT, {"answer": {"count": 3}}))
    assert d.kind == "answer" and d.answer == {"count": 3}
    assert parse_response("The answer is 3.").kind == "no_action"


@pytest.mark.parametrize("text,reason", [
    ('<tool_call>\n{"name": "sql", "name": "etl", "arguments": {}}\n</tool_call>', "duplicate"),
    (call(SUBMIT, {"answer": {}}) + call("sql", {"action": "schema"}), "mixed"),
    (call(SUBMIT, {"answer": {}, "extra": 1}), "exactly"),
    ('<tool_call>\n{"name": "sql", "arguments": {"x": NaN}}\n</tool_call>', "non-finite"),
    ('<tool_call>\n{"name": "sql", "arguments": {}, "id": 1}\n</tool_call>', "name, arguments"),
    ('<tool_call>\n{"name": "sql", "arguments": {}', "unbalanced"),
    ("".join(call("sql", {"action": "schema"}) for _ in range(9)), "more than"),
])
def test_ambiguous_responses_are_malformed(text, reason):
    d = parse_response(text)
    assert d.kind == "malformed" and reason in d.reason


def test_strict_loads_rejects_nested_duplicates():
    with pytest.raises(ValueError):
        strict_loads('{"a": {"b": 1, "b": 2}}')


def test_history_shows_calls_hides_timing_and_counts_turns():
    tools = function_tools({"sql": {"description": "db", "parameters": {"type": "object"}}})
    assert [t["function"]["name"] for t in tools] == ["sql", SUBMIT]

    def run(cpu_ns):
        c = Conversation("Count rows.", tools, max_turns=5)
        d = parse_response(call("sql", {"action": "query", "sql": "SELECT COUNT(*) FROM t"}))
        c.record_turn(d, ["t00c0"])
        c.tool_result("t00c0", "sql", "ok", {"rows": [[3]], "tool_accounting": {"cpu_ns": cpu_ns, "elapsed_ns": cpu_ns}})
        return c

    a, b = run(1_000_000), run(9_999_999)
    # V6 regression: prompts of paired arms differed only in timing values.
    assert json.dumps(a.request(), sort_keys=True) == json.dumps(b.request(), sort_keys=True)
    messages = a.request()["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool"]
    assert messages[2]["tool_calls"][0]["function"] == {"name": "sql", "arguments": {"action": "query", "sql": "SELECT COUNT(*) FROM t"}}
    body = json.loads(messages[3]["content"])
    assert body == {"status": "ok", "result": {"rows": [[3]]}, "turns_remaining": 4}
    assert "tool_accounting" not in json.dumps(messages)
    assert visible({"a": [{"cpu_ns": 1, "b": 2}]}) == {"a": [{"b": 2}]}


def test_outcome_classes_and_paired_seeds():
    assert outcome_class("completed", "pass", None) == "passed"
    assert outcome_class("completed", "fail", None) == "wrong_answer"
    assert outcome_class("timed_out", "unavailable", None) == "deadline_exceeded"
    assert outcome_class("incomplete", "unavailable", "output_truncated") == "output_truncated"
    assert turn_seed(0, "task-r0", 1) == turn_seed(0, "task-r0", 1) != turn_seed(0, "task-r0", 2)


class SleepTool:
    def execute(self, seconds, workers=1):
        time.sleep(seconds)
        return {"slept": seconds}


def test_dependent_calls_share_one_absolute_deadline():
    started = time.monotonic_ns()
    executor = BoundedToolExecutor({"sleep": SleepTool()}, timeout_seconds=30, deadline_ns=started + int(2.5e9))
    outcomes = executor.execute([
        ToolCall("a", "sleep", {"seconds": 1.5}),
        ToolCall("b", "sleep", {"seconds": 1.5}, ("a",)),
    ])
    assert outcomes["a"].status == "completed"
    # b alone fits its own 30 s allowance; the goal deadline stops it.
    assert outcomes["b"].status == "timed_out" and "deadline" in outcomes["b"].error
    assert (time.monotonic_ns() - started) / 1e9 < 6


def _pack_run(tmp_path, case, *extra):
    output = tmp_path / "run"
    if case == "tool_failure":
        # Failure injection lives in the default workload runtime, not the task pack.
        tasks = []
    else:
        spec = tmp_path / "spec.json"
        spec.write_text(json.dumps([dict(kind="business", rows=128, seed=7)]))
        tasks = ["--task-pack", str(spec)]
    campaign.main(["--mode", "fixture", "--output", str(output), *tasks, "--policies", "demand",
                   "--max-runs", "1", "--deadline", "60", "--fixture-case", case, *extra])
    traces = [json.loads(p.read_text()) for p in sorted((output / "goals").glob("*/agent-trace.json"))]
    records = [json.loads(p.with_name("record.json").read_text()) for p in sorted((output / "goals").glob("*/agent-trace.json"))]
    return traces, records


@pytest.mark.parametrize("case,outcome,status", [
    ("success", "passed", "completed"),
    ("wrong_answer", "wrong_answer", "completed"),
    ("truncated_output", "output_truncated", "incomplete"),
    ("no_action", "turn_budget_exhausted", "incomplete"),
    ("tool_failure", "turn_budget_exhausted", "incomplete"),
])
def test_goal_outcomes_are_classified(tmp_path, case, outcome, status):
    traces, records = _pack_run(tmp_path, case)
    assert len(traces) == 1
    trace, record = traces[0], records[0]
    assert trace["protocol"] == "chat-tools-v1" and trace["outcome"] == outcome
    assert record["execution_status"] == status
    if case == "no_action":
        assert {t["kind"] for t in trace["turns"]} == {"no_action"}
    if case == "tool_failure":
        # A failing tool is an observation for the model, not a crashed goal.
        assert record["execution_status"] != "crashed"
        calls = json.loads((Path(tmp_path) / "run" / "goals" / record["goal_execution_id"] / "model-calls.json").read_text())
        assert '\\"status\\": \\"error\\"' in json.dumps(calls[-1]["request"]["messages"][-1])


def test_sampled_decoding_is_recorded_and_paired(tmp_path):
    traces, _ = _pack_run(tmp_path, "success", "--decoding", "sampled", "--sampling-seed", "11")
    assert traces[0]["sampling"]["mode"] == "sampled" and traces[0]["sampling"]["temperature"] == 0.7
    assert all(isinstance(t["sampling_seed"], int) for t in traces[0]["turns"])


def test_verification_after_deadline_is_not_a_pass(tmp_path, monkeypatch):
    from studies.energy_diagnosis.moe import business_workload
    original = business_workload.BusinessRuntime.verify

    def slow(self, task, answer):
        time.sleep(9)
        return original(self, task, answer)

    monkeypatch.setattr(business_workload.BusinessRuntime, "verify", slow)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps([dict(kind="business", rows=128, seed=7)]))
    output = tmp_path / "run"
    campaign.main(["--mode", "fixture", "--output", str(output), "--task-pack", str(spec), "--policies", "demand",
                   "--max-runs", "1", "--deadline", "8", "--fixture-case", "success"])
    record = json.loads(next((output / "goals").glob("*/record.json")).read_text())
    trace = json.loads(next((output / "goals").glob("*/agent-trace.json")).read_text())
    assert record["verifier"]["outcome"] != "pass" and record["execution_status"] == "timed_out"
    assert trace["outcome"] == "deadline_exceeded"


def test_legacy_protocol_remains_available(tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps([dict(kind="business", rows=128, seed=7)]))
    output = tmp_path / "run"
    campaign.main(["--mode", "fixture", "--output", str(output), "--task-pack", str(spec), "--policies", "demand",
                   "--max-runs", "1", "--deadline", "60", "--agent-protocol", "legacy-json-v1"])
    calls = json.loads(next((output / "goals").glob("*/model-calls.json")).read_text())
    assert "prompt" in calls[0] and not list((output / "goals").glob("*/agent-trace.json"))
