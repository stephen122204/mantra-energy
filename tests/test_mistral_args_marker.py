"""chat-tools-v3: a Mistral call without the [ARGS] marker is the same call (no GPU, no model).

vLLM 0.10.2 detokenizes Mistral output without every control token except [TOOL_CALLS], so its tool
parser reads [TOOL_CALLS]name[ARGS]{json} and [TOOL_CALLS]name{json} identically. v2 keeps the
strict parser; v3 accepts the second form under the same name and JSON rules.
"""
import json
import time
from types import SimpleNamespace

import pytest

from studies.energy_diagnosis.agent_protocol import SUBMIT, parse_mistral_response, parse_tool_response
from studies.energy_diagnosis.local_run import GoalExecutor
from studies.energy_diagnosis.moe import program_workload as pw
from studies.paper2.cohort import make_plan, pilot
from studies.paper2.cohort.cohort import CohortSpec, _Session
from studies.paper2.cohort.records import EventLog


def mcall(name, arguments, args_marker=True):
    return f"[TOOL_CALLS]{name}{'[ARGS]' if args_marker else ''}{json.dumps(arguments)}"


def v3(text):
    return parse_mistral_response(text, accept_missing_args_marker=True)


def test_missing_args_marker_is_the_same_call_under_v3_only():
    for name, arguments in (("sql", {"action": "schema"}), ("program", {"action": "write", "content": "x = {1: 2}"})):
        strict, bare = parse_mistral_response(mcall(name, arguments)), v3(mcall(name, arguments, args_marker=False))
        assert (bare.kind, bare.calls) == (strict.kind, strict.calls) == ("tool_calls", ((name, arguments),))
        assert bare.repaired == "tool call without [ARGS] marker accepted" and strict.repaired == ""
        assert v3(mcall(name, arguments)).repaired == ""  # well-formed calls are not marked
        assert parse_mistral_response(mcall(name, arguments, args_marker=False)).reason == "tool call without an arguments object"
    d = v3("Writing it now." + mcall(SUBMIT, {"answer": {"ids": [1, 2]}}, args_marker=False))
    assert (d.kind, d.answer, d.content) == ("answer", {"ids": [1, 2]}, "Writing it now.")
    # mixed forms in one response: each segment is read on its own
    d = v3(mcall("sql", {"a": 1}, args_marker=False) + mcall("sql", {"b": 2}))
    assert d.calls == (("sql", {"a": 1}), ("sql", {"b": 2}))
    assert parse_tool_response(mcall("sql", {}, args_marker=False), "mistral", accept_missing_args_marker=True).kind == "tool_calls"


@pytest.mark.parametrize("text,reason", [
    ("[TOOL_CALLS]sql", "without an arguments object"),               # no object at all
    ('[TOOL_CALLS]sql[ARGS]{}[ARGS]{}', "without an arguments object"),
    ('[TOOL_CALLS]{"action": "schema"}', "name missing"),
    ('[TOOL_CALLS]my tool{"a": 1}', "name missing or invalid"),
    ('[TOOL_CALLS]sql{"action": "schema"', "invalid tool call JSON"),
    ('[TOOL_CALLS]sql{"a": 1} trailing', "invalid tool call JSON"),
    ('[TOOL_CALLS]sql{"a": 1, "a": 2}', "duplicate"),
    ('[TOOL_CALLS]sql{"x": NaN}', "non-finite"),
    (mcall(SUBMIT, {"answer": {}, "extra": 1}, args_marker=False), "exactly"),
    (mcall(SUBMIT, {"answer": {}}, args_marker=False) + mcall("sql", {}, args_marker=False), "mixed"),
])
def test_v3_keeps_every_other_rule(text, reason):
    d = v3(text)
    assert d.kind == "malformed" and reason in d.reason and d.content == text.strip()


# First W8A8 turn of python-conditional-dedup (qualification 12ab541-a7): control [TOOL_CALLS], no [ARGS].
RECORDED = ('[TOOL_CALLS]program{"action": "read", "content": "def solve(data):\\n    seen = set()\\n    '
            'return [r[\'id\'] for r in data if r[\'keep\'] or r[\'url\'] not in seen]\\n\\ndata = [\\n    '
            '{\'id\': 1, \'url\': \'a\', \'keep\': False},\\n]"}')


def test_recorded_response_is_a_program_call_under_v3():
    assert parse_mistral_response(RECORDED).kind == "malformed"
    d = v3(RECORDED)
    assert d.kind == "tool_calls" and d.calls[0][0] == "program" and d.calls[0][1]["action"] == "read"


class Model:
    """Production adapter interface; replays scripted Mistral responses and keeps each request."""

    def __init__(self, replies):
        self.model_config = {"max_tokens": None}
        self.fit_to_context = True
        self.replies, self.requests = list(replies), []

    def chat(self, request, sampling, meta):
        self.requests.append(json.loads(json.dumps(request)))
        return dict(content=self.replies.pop(0), finish_reason="stop", status="ok", allowance=900,
                    tokens=dict(prompt=100, completion=20), token_provenance="estimated")


def run(tmp_path, protocol, replies):
    from studies.energy_diagnosis.moe.task_pack import PackRuntime
    task = pw.create_task(tmp_path / "assets", case="conditional-dedup", rows=32, seed=7)
    rt = PackRuntime({task.task_id: pw}, tmp_path / "runtime")
    lease = SimpleNamespace(execution_id="v3", attempt_id="v3", started_ns=time.monotonic_ns(), clock_domain="host-monotonic")
    rt.begin(task, lease)
    plan = SimpleNamespace(setting_id="cohort", planned_run_id="v3-cohort", model_sha256="fixture",
                           tool_concurrency=False, tool_workers=1)
    model = Model(replies)
    ex = GoalExecutor({task.task_id: task}, model, None, tmp_path, max_steps=3, timeout_seconds=60, simulated=True,
                      workload_runtime=rt, protocol=protocol, tool_call_format="mistral")
    trace = dict(terminal=None, turns=[])
    status, *_ = ex._chat(task, lease, plan, rt.context(task), [], [], [], [], trace, [], None)
    return status, trace, model


REPLIES = [mcall("program", {"action": "read"}, args_marker=False), mcall(SUBMIT, {"answer": {}}, args_marker=False)]


def test_turn_loop_executes_the_call_and_records_it_as_a_normal_call_under_v3(tmp_path):
    status, trace, model = run(tmp_path, "chat-tools-v3", REPLIES)
    assert status == "completed"
    assert [t["kind"] for t in trace["turns"]] == ["tool_calls", "answer"]
    assert all(t["repaired"] == "tool call without [ARGS] marker accepted" for t in trace["turns"])
    # the model sees its call rendered as a structured tool call, then the tool result, as from a stock server
    history = model.requests[1]["messages"]
    assert history[-2]["role"] == "assistant" and history[-2]["tool_calls"][0]["function"] == dict(name="program", arguments={"action": "read"})
    assert history[-1]["role"] == "tool" and "[TOOL_CALLS]" not in json.dumps(history)


def test_turn_loop_under_v2_is_unchanged(tmp_path):
    status, trace, model = run(tmp_path, "chat-tools-v2", REPLIES + [REPLIES[1]])
    assert status != "completed"
    assert {t["reason"] for t in trace["turns"]} == {"tool call without an arguments object"}


def spec(**kw):
    return CohortSpec(cohort_id="c", config_id="cfg", served_model="m", base_url="http://127.0.0.1:1", max_model_len=1000,
                      tekken="t", tasks=[dict(task_id="t1", task_pickle="p", task_kind="business", pair_key="k1")], **kw)


def test_cohort_sessions_carry_the_plan_protocol(tmp_path):
    with pytest.raises(ValueError, match="agent protocol"):
        spec(protocol="chat-tools-v9").validate()
    spec().validate()
    s = spec(protocol="chat-tools-v3")
    s.validate()
    session = _Session(s, s.tasks[0], tmp_path, EventLog(tmp_path / "events.jsonl"))
    assert json.loads(session.spec_path.read_text())["protocol"] == "chat-tools-v3"
    session = _Session(spec(), spec().tasks[0], tmp_path / "default", EventLog(tmp_path / "events2.jsonl"))
    assert json.loads(session.spec_path.read_text())["protocol"] == "chat-tools-v2"


def test_plans_name_the_protocol(tmp_path):
    assert make_plan.build(tmp_path, "gpu", "alloc")["protocol"] == "chat-tools-v2"
    assert make_plan.build(tmp_path, "gpu", "alloc", protocol="chat-tools-v3")["protocol"] == "chat-tools-v3"
    out = tmp_path / "plan.json"
    make_plan.main(["--work", str(tmp_path), "--gpu-uuid", "gpu", "--allocation", "alloc", "--out", str(out),
                    "--protocol", "chat-tools-v3"])
    assert json.loads(out.read_text())["protocol"] == "chat-tools-v3"


def test_driver_rejects_an_unknown_protocol_before_anything_runs(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(dict(protocol="chat-tools-v9", passes=[])))
    with pytest.raises(SystemExit, match="agent protocol"):
        pilot.main(["--plan", str(path), "--out", str(tmp_path / "out"), "--budget-s", "60",
                    "--cutoff-utc", "2099-01-01T00:00:00Z", "--fixture-server"])
    assert not (tmp_path / "out").exists()
