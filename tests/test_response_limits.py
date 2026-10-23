"""No per-response cap: responses may use the context left after the prompt (no GPU, no model)."""
import json
import time
from types import SimpleNamespace

import pytest

from studies.energy_diagnosis.local_run import GoalExecutor
from studies.energy_diagnosis.moe import program_workload as pw
from studies.paper2.cohort.client import SharedServerAdapter
from studies.paper2.cohort.session import OUTCOMES


class Renderer:
    def __init__(self, prompt_len):
        self.prompt_len = prompt_len

    def encode(self, messages, tools):
        return list(range(self.prompt_len))

    def decode(self, ids):
        return "x" * len(ids)


def adapter(prompt_len, max_tokens, max_model_len=1000, generate=None):
    records, sent = [], []
    a = SharedServerAdapter("http://127.0.0.1:1", "fixture", Renderer(prompt_len), max_tokens=max_tokens,
                            max_model_len=max_model_len, record=records.append, session_id="s")

    def stream(payload, timeout):
        sent.append(payload)
        n = payload["max_tokens"] if generate is None else min(generate, payload["max_tokens"])
        finish = "length" if n >= payload["max_tokens"] else "stop"
        return 1, list(range(n)), finish, dict(prompt_tokens=prompt_len, completion_tokens=n), ""

    a._stream = stream
    return a, records, sent


REQUEST = dict(messages=[], tools=[])


def test_no_cap_sends_the_remaining_context():
    a, records, sent = adapter(100, None, generate=10)
    out = a.chat(REQUEST, dict(mode="greedy"), {})
    assert sent[0]["max_tokens"] == 900 and out["allowance"] == 900 and out["finish_reason"] == "stop"
    assert records[0]["max_tokens_policy"] == "remaining_context"
    a.model_config["max_tokens"] = 50  # a total output budget set by the turn loop still bounds the request
    assert a.chat(REQUEST, dict(mode="greedy"), {})["allowance"] == 50 and sent[1]["max_tokens"] == 50


def test_no_cap_full_context_is_exhausted_without_a_request():
    a, records, sent = adapter(1000, None)
    out = a.chat(REQUEST, dict(mode="greedy"), {})
    assert out["finish_reason"] == "context_exhausted" and out["allowance"] == 0 and not sent


def test_fixed_cap_is_unchanged():
    a, records, sent = adapter(800, 256)
    out = a.chat(REQUEST, dict(mode="greedy"), {})
    assert out["finish_reason"] == "context_exhausted" and not sent and records[0]["max_tokens_policy"] == "fixed"
    a, records, sent = adapter(100, 256, generate=10)
    assert a.chat(REQUEST, dict(mode="greedy"), {})["allowance"] == 256 and sent[0]["max_tokens"] == 256


class Model:
    """Production adapter interface; answers with ``reply(allowance)``."""

    def __init__(self, reply, fit=True):
        self.model_config = {"max_tokens": None}
        self.fit_to_context = fit
        self.reply, self.allowances = reply, []

    def chat(self, request, sampling, meta):
        allowance = 900 if self.model_config["max_tokens"] is None else self.model_config["max_tokens"]
        self.allowances.append(self.model_config["max_tokens"])
        return dict(self.reply(allowance), status="ok", allowance=allowance, token_provenance="estimated")


def run(tmp_path, model, max_output_tokens=None):
    from studies.energy_diagnosis.moe.task_pack import PackRuntime
    task = pw.create_task(tmp_path / "assets", case="conditional-dedup", rows=32, seed=7)
    rt = PackRuntime({task.task_id: pw}, tmp_path / "runtime")
    lease = SimpleNamespace(execution_id="lim", attempt_id="lim", started_ns=time.monotonic_ns(), clock_domain="host-monotonic")
    rt.begin(task, lease)
    plan = SimpleNamespace(setting_id="cohort", planned_run_id="lim-cohort", model_sha256="fixture",
                           tool_concurrency=False, tool_workers=1)
    ex = GoalExecutor({task.task_id: task}, model, None, tmp_path, max_steps=3, timeout_seconds=60, simulated=True,
                      workload_runtime=rt, protocol="chat-tools-v2", max_output_tokens=max_output_tokens)
    calls, trace = [], dict(terminal=None, turns=[])
    status, error, answer, *_ = ex._chat(task, lease, plan, rt.context(task), calls, [], [], [], trace, [], None)
    return status, error, answer, trace, calls


ANSWER = "<tool_call>" + json.dumps(dict(name="submit_answer", arguments=dict(answer={}))) + "</tool_call>"


def test_loop_without_cap_completes_and_records_the_allowance(tmp_path):
    model = Model(lambda n: dict(content=ANSWER, finish_reason="stop", tokens=dict(prompt=100, completion=40)))
    status, error, answer, trace, calls = run(tmp_path, model)
    assert status == "completed" and model.allowances == [None]
    assert trace["turns"][0]["output_budget"] == 900 and trace["limits"]["output_tokens_per_turn"] is None


def test_response_that_fills_the_context_is_context_exhausted(tmp_path):
    model = Model(lambda n: dict(content="x", finish_reason="length", tokens=dict(prompt=100, completion=n)))
    status, error, answer, trace, calls = run(tmp_path, model)
    assert (status, OUTCOMES[status], trace["terminal"]) == ("incomplete", "agent_failed", "context_exhausted")
    assert "filled the remaining context (900" in error


def test_total_output_budget_still_bounds_each_request(tmp_path):
    model = Model(lambda n: dict(content="x", finish_reason="length", tokens=dict(prompt=100, completion=n)))
    status, error, answer, trace, calls = run(tmp_path, model, max_output_tokens=300)
    assert model.allowances == [300] and trace["terminal"] == "output_budget_exhausted"


def test_completion_beyond_the_sent_allowance_is_infrastructure(tmp_path):
    model = Model(lambda n: dict(content=ANSWER, finish_reason="stop", tokens=dict(prompt=100, completion=n + 1)))
    status, error, answer, trace, calls = run(tmp_path, model)
    assert (status, trace["terminal"]) == ("crashed", "infrastructure_failure")


def test_no_cap_requires_an_adapter_that_fits_the_context(tmp_path):
    model = Model(lambda n: dict(content=ANSWER, finish_reason="stop", tokens=dict(prompt=100, completion=1)), fit=False)
    with pytest.raises(ValueError, match="remaining context"):
        run(tmp_path, model)


def test_plan_caps_are_options_with_unchanged_defaults(tmp_path):
    from studies.paper2.cohort.make_plan import _cap, build_sweep
    limits = build_sweep(tmp_path, "GPU-x", "lease", 7505)["limits"]
    assert (limits["max_tokens"], limits["max_total_output_tokens"]) == (4096, 65536)
    limits = build_sweep(tmp_path, "GPU-x", "lease", 7505, max_tokens=None, max_total_output_tokens=None)["limits"]
    assert (limits["max_tokens"], limits["max_total_output_tokens"], limits["max_turns"]) == (None, None, 250)
    assert _cap("none") is None and _cap("8192") == 8192
    with pytest.raises(Exception):
        _cap("0")
