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
        time.sleep(60)
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


# Responses recorded in the step-3 screen (Qwen3-30B-A3B-Instruct-2507 Q4_K_M).
UNCLOSED_SUBMIT = '<tool_call>\n{"name": "submit_answer", "arguments": {"answer": 2}}'
UNCLOSED_AFTER_TEXT = 'I will submit the final answer.\n<tool_call>\n{"name": "submit_answer", "arguments": {"answer": {"answer": 2}}\n}'


def test_unclosed_final_call_is_malformed_in_v1_and_parsed_in_v2():
    assert parse_response(UNCLOSED_SUBMIT).kind == "malformed"
    d = parse_response(UNCLOSED_SUBMIT, accept_unclosed_final=True)
    assert d.kind == "answer" and d.answer == 2 and d.repaired
    d = parse_response(UNCLOSED_AFTER_TEXT, accept_unclosed_final=True)
    assert d.kind == "answer" and d.answer == {"answer": 2} and d.content == "I will submit the final answer."
    d = parse_response(call("python", {"action": "read"}) + "\n<tool_call>\n" + json.dumps(dict(name="python", arguments={"action": "test"})),
                       accept_unclosed_final=True)
    assert d.kind == "tool_calls" and [n for n, _ in d.calls] == ["python", "python"]
    # Well-formed responses parse identically; everything else stays strict.
    for text in (call("sql", {"action": "schema"}), call(SUBMIT, {"answer": {"done": True}}), "The answer is 3."):
        assert parse_response(text, accept_unclosed_final=True) == parse_response(text)
    for text in ('{"name": "submit_answer", "arguments": {"answer": 2}}\n</tool_call>',      # closing tag only
                 '<tool_call>\n{"name": "submit_answer", "arguments": {"answer": 2}',        # truncated JSON
                 '<tool_call>{"name": "a", "arguments": {}}<tool_call>{"name": "b", "arguments": {}}</tool_call>'):
        assert parse_response(text, accept_unclosed_final=True).kind == "malformed"
    assert parse_response('{"answer": {"done": true}}', accept_unclosed_final=True).kind == "no_action"


def test_feedback_names_the_fix_only_in_v2():
    tools = function_tools({})
    v1, v2 = Conversation("g", tools, 5), Conversation("g", tools, 5, protocol="chat-tools-v2")
    for c in (v1, v2):
        c.record_turn(parse_response(UNCLOSED_SUBMIT))
        c.feedback("unbalanced tool_call tags")
    e1 = json.loads(v1.messages[-1]["content"])["error"]
    e2 = json.loads(v2.messages[-1]["content"])["error"]
    assert e1 == "unbalanced tool_call tags. Call a tool or submit_answer."
    assert "closing tag" in e2 and e2.endswith("Call a tool or submit_answer.")


@pytest.mark.parametrize("protocol,outcome", [("chat-tools-v1", "turn_budget_exhausted"), ("chat-tools-v2", "passed")])
def test_unclosed_submit_end_to_end(tmp_path, protocol, outcome):
    traces, _ = _pack_run(tmp_path, "unclosed_submit", "--agent-protocol", protocol)
    assert traces[0]["protocol"] == protocol and traces[0]["outcome"] == outcome
    if protocol == "chat-tools-v2":
        assert traces[0]["turns"][-1]["repaired"] == "unclosed final tool_call accepted"


def test_exponent_overflow_is_malformed():
    decision = parse_response('<tool_call>{"name":"sql","arguments":{"action":"query","x":1e999}}</tool_call>')
    assert decision.kind == 'malformed' and 'non-finite' in decision.reason


def test_verifier_process_is_terminated_at_deadline():
    from studies.energy_diagnosis.local_run import _VerificationTool
    def stuck(task, answer):
        time.sleep(60)
        return {'passed': True, 'reason': 'too late'}
    start = time.monotonic()
    runner = BoundedToolExecutor({'verify': _VerificationTool(stuck, None, None)},
                                timeout_seconds=1, deadline_ns=time.monotonic_ns()+1_000_000_000)
    outcome = runner.execute([ToolCall('verify', 'verify', {})])['verify']
    assert outcome.status == 'timed_out'
    assert time.monotonic()-start < 7


@pytest.mark.parametrize('overrun', [False, True])
def test_final_answer_cannot_bypass_total_output_limit(tmp_path, monkeypatch, overrun):
    from studies.energy_diagnosis.moe.backend import BackendAdapter
    limits = []
    def chat(self, request, sampling, meta):
        limit = self.model_config['max_tokens']; limits.append(limit)
        return {'status':'ok', 'content':call(SUBMIT, {'answer':{}}),
                'finish_reason':'stop' if overrun else 'length',
                'tokens':{'prompt':10, 'completion':limit+1 if overrun else limit},
                'token_provenance':'estimated'}
    monkeypatch.setattr(BackendAdapter, 'chat', chat)
    traces, records = _pack_run(tmp_path, 'success', '--max-total-output-tokens', '3')
    assert limits == [3]
    assert traces[0]['outcome'] == ('infrastructure_failure' if overrun else 'output_budget_exhausted')
    assert records[0]['verifier']['outcome'] != 'pass'


@pytest.mark.parametrize("temperature", ["inf", "nan"])
def test_cli_rejects_nonfinite_sampling_temperature(tmp_path, temperature):
    from studies.energy_diagnosis.moe.run import main
    with pytest.raises(SystemExit) as exc:
        main(["--mode", "fixture", "--output", str(tmp_path), "--decoding", "sampled", "--temperature", temperature])
    assert exc.value.code == 2


def test_paired_arms_receive_identical_model_requests(tmp_path):
    """Demand and fixed runs of one task must see byte-identical requests every turn.

    V6 prompts diverged between arms through tool timing values. Here the
    fixture model is deterministic, so any difference would come from the
    harness or the policy leaking into model-visible state.
    """
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps([dict(kind="business", rows=128, seed=7), dict(kind="etl", rows=128, seed=7)]))
    output = tmp_path / "run"
    campaign.main(["--mode", "fixture", "--output", str(output), "--task-pack", str(spec),
                   "--policies", "demand,fixed", "--comparison-order", "balanced-pairs", "--repeats", "2",
                   "--max-runs", "16", "--deadline", "60"])
    by_pair = {}
    for path in (output / "goals").glob("*/record.json"):
        record = json.loads(path.read_text())
        calls = json.loads(path.with_name("model-calls.json").read_text())
        pair = record["planned_run_id"][: -len(record["setting_id"]) - 1]
        by_pair.setdefault(pair, {})[record["setting_id"].split("-")[1]] = [json.dumps(c["request"], sort_keys=True) for c in calls]
    assert len(by_pair) == 8 and all(set(arms) == {"demand", "fixed"} for arms in by_pair.values())
    for arms in by_pair.values():
        assert arms["demand"] == arms["fixed"]


@pytest.mark.parametrize("method", ["init", "generate", "snapshot", "demands", "prepare"])
def test_backend_rpc_cannot_receive_fresh_goal_allowance(tmp_path, monkeypatch, method):
    import io
    from types import SimpleNamespace
    from studies.energy_diagnosis.moe.backend import ProcessBackend
    backend = ProcessBackend({}, python="unused", mode="fixture", log_path=tmp_path/'backend.log',
                             timeout=60, deadline_ns=1_500_000_000)
    backend.process = SimpleNamespace(stdin=io.StringIO())
    observed = []
    class Responses:
        def get(self, timeout):
            observed.append(timeout)
            return dict(id=backend.seq, ok=True, result={})
    backend.messages = Responses()
    monkeypatch.setattr('studies.energy_diagnosis.moe.backend.time.monotonic_ns', lambda: 1_000_000_000)
    assert backend._rpc(method, timeout=60) == {}
    assert observed == [0.5]
    with backend.cleanup_scope(2):
        assert backend.rpc_deadline_ns == 5_000_000_000
    assert backend.rpc_deadline_ns == 1_500_000_000


def test_expired_backend_deadline_does_not_dispatch(tmp_path, monkeypatch):
    import io
    from types import SimpleNamespace
    from studies.energy_diagnosis.moe.backend import ProcessBackend
    backend = ProcessBackend({}, python="unused", mode="fixture", log_path=tmp_path/'backend.log',deadline_ns=1)
    stream = io.StringIO(); backend.process = SimpleNamespace(stdin=stream)
    terminated = []
    monkeypatch.setattr(backend, 'end_goal', lambda: terminated.append(True))
    with pytest.raises(TimeoutError, match='deadline'):
        backend._rpc('snapshot')
    assert terminated == [True] and stream.getvalue() == ''


def test_completed_turns_survive_interruption_before_final_result(tmp_path, monkeypatch):
    from studies.energy_diagnosis.moe.backend import BackendAdapter
    original = BackendAdapter.chat
    calls = []
    def interrupt_second(self, *args):
        calls.append(1)
        if len(calls) == 2:
            raise campaign.CampaignInterrupted("injected between-turn interruption")
        return original(self, *args)
    monkeypatch.setattr(BackendAdapter, 'chat', interrupt_second)
    with pytest.raises(SystemExit) as exc:
        _pack_run(tmp_path, 'success')
    assert exc.value.code == 130
    root = tmp_path/'run'
    model = next((root/'goals').glob('*/turns/000-model.json'))
    partial = json.loads(model.read_text())
    assert partial['partial'] is True and partial['payload']['adapter']['status'] == 'ok'
    tool = json.loads(model.with_name('000-tools.json').read_text())
    assert tool['payload']['outcomes'][0]['status'] == 'completed'
    assert not model.parent.parent.joinpath('record.json').exists()
    rows = [json.loads(s) for s in (root/'exports/attempts.jsonl').read_text().splitlines()]
    assert len(rows) == 1 and rows[0]['attempt']['status'] == 'running'
    roles = {a['role'] for a in rows[0]['attempt']['artifacts']}
    assert {'agent-turn-model', 'agent-turn-tools'} <= roles
