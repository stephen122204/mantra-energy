import json
from types import SimpleNamespace

import pytest

from studies.paper2.cohort.client import SharedServerAdapter


def adapter_with_stream(monkeypatch, chunks):
    lines = [f"data: {c if isinstance(c, str) else json.dumps(c)}\n\n".encode() for c in chunks]
    class Response:
        status = 200
        def __iter__(self):
            return iter(lines)
    conn = SimpleNamespace(request=lambda *a, **k: None, getresponse=Response, close=lambda: None)
    monkeypatch.setattr('studies.paper2.cohort.client.http.client.HTTPConnection', lambda *a, **k: conn)
    return SharedServerAdapter('http://localhost:8100', 'model', None, max_tokens=4,
                               max_model_len=100, record=lambda r: None, session_id='test')


def test_http_200_stream_error_is_not_an_empty_model_answer(monkeypatch):
    a = adapter_with_stream(monkeypatch, [dict(error=dict(message='', type='BadRequestError', code=400)), '[DONE]'])
    with pytest.raises(RuntimeError, match='BadRequestError'):
        a._stream({}, 1)


@pytest.mark.parametrize('chunks', [[], ['[DONE]'], [dict(choices=[dict(token_ids=[2], finish_reason='stop')])]])
def test_truncated_or_missing_completion_fails(monkeypatch, chunks):
    a = adapter_with_stream(monkeypatch, chunks)
    with pytest.raises(RuntimeError, match='incomplete completion stream'):
        a._stream({}, 1)


def test_reported_tokens_require_returned_ids(monkeypatch):
    a = adapter_with_stream(monkeypatch, [dict(choices=[dict(finish_reason='stop')], usage=dict(completion_tokens=1)), '[DONE]'])
    with pytest.raises(RuntimeError, match='without token IDs'):
        a._stream({}, 1)


def test_terminal_stream_preserves_ids_and_usage(monkeypatch):
    a = adapter_with_stream(monkeypatch, [dict(choices=[dict(text='x', token_ids=[17], finish_reason='stop')]),
                                        dict(choices=[], usage=dict(completion_tokens=1)), '[DONE]'])
    first, ids, finish, usage, text = a._stream({}, 1)
    assert first is not None and ids == [17] and finish == 'stop'
    assert usage == dict(completion_tokens=1) and text == 'x'


class Clock:
    """time.monotonic that advances one second per read, so a stream that never pauses still runs out of time."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 1.0
        return self.t


def endless_stream(monkeypatch, closed):
    token = f"data: {json.dumps(dict(choices=[dict(text='x', token_ids=[17], finish_reason=None)]))}\n\n".encode()

    class Response:
        status = 200

        def __iter__(self):
            while True:  # a runaway generation: the server never stops sending tokens
                yield token
    conn = SimpleNamespace(request=lambda *a, **k: None, getresponse=Response, close=lambda: closed.append(True))
    monkeypatch.setattr('studies.paper2.cohort.client.http.client.HTTPConnection', lambda *a, **k: conn)
    monkeypatch.setattr('studies.paper2.cohort.client.time.monotonic', Clock())


def test_a_stream_that_keeps_sending_tokens_still_ends_at_the_request_deadline(monkeypatch):
    from studies.paper2.cohort.client import StreamDeadline, stream_completion
    closed = []
    endless_stream(monkeypatch, closed)
    with pytest.raises(StreamDeadline) as exc:
        stream_completion('localhost', 8100, {}, 10)
    assert 0 < len(exc.value.ids) < 12 and set(exc.value.ids) == {17} and closed == [True]  # closing aborts it in vLLM


class Renderer:
    def encode(self, messages, tools):
        return [1, 2, 3]

    def decode(self, ids):
        return 'x' * len(ids)


def test_adapter_reports_the_deadline_and_keeps_the_partial_tokens(monkeypatch):
    closed, records = [], []
    endless_stream(monkeypatch, closed)
    a = SharedServerAdapter('http://localhost:8100', 'model', Renderer(), max_tokens=None, max_model_len=1000,
                            record=records.append, session_id='test')
    a.model_config['request_timeout_seconds'] = 10
    out = a.chat(dict(messages=[], tools=[]), dict(mode='greedy'), {})
    assert out['status'] == 'error' and out['owned_work_terminated'] is True and 'deadline' in out['error']
    rec = records[-1]
    assert rec['partial_completion_tokens'] == len(rec['partial_output_ids']) > 0 and 'output_ids' not in rec
    assert closed == [True]


def test_a_request_cut_at_the_session_deadline_ends_the_session_timed_out(tmp_path):
    """The session watchdog holds even when one response would outlast it (the turn loop sets the
    request timeout to the time left; the cut request is classified as the deadline, not a crash)."""
    import time
    from studies.energy_diagnosis.local_run import GoalExecutor
    from studies.energy_diagnosis.moe import program_workload as pw
    from studies.energy_diagnosis.moe.task_pack import PackRuntime

    class Model:
        def __init__(self):
            self.model_config = {"max_tokens": None, "request_timeout_seconds": 600}
            self.fit_to_context = True
            self.timeouts = []

        def chat(self, request, sampling, meta):
            limit = self.model_config["request_timeout_seconds"]
            self.timeouts.append(limit)
            time.sleep(limit + 0.05)  # the response is still streaming when its time runs out
            return dict(status='error', error='StreamDeadline: request deadline reached mid-stream after 9 tokens',
                        tokens={}, token_provenance='unknown', owned_work_terminated=True)

    task = pw.create_task(tmp_path / "assets", case="conditional-dedup", rows=32, seed=7)
    rt = PackRuntime({task.task_id: pw}, tmp_path / "runtime")
    lease = SimpleNamespace(execution_id="dl", attempt_id="dl", started_ns=time.monotonic_ns(), clock_domain="host-monotonic")
    rt.begin(task, lease)
    plan = SimpleNamespace(setting_id="cohort", planned_run_id="dl-cohort", model_sha256="fixture",
                           tool_concurrency=False, tool_workers=1)
    model = Model()
    ex = GoalExecutor({task.task_id: task}, model, None, tmp_path, max_steps=5, timeout_seconds=0.5, simulated=True,
                      workload_runtime=rt, protocol="chat-tools-v3", tool_call_format="mistral")
    trace = dict(terminal=None, turns=[])
    status, error, *_ = ex._chat(task, lease, plan, rt.context(task), [], [], [], [], trace, [], None)
    assert status == "timed_out" and trace["terminal"] == "deadline_exceeded" and "mid-stream" in error
    assert len(model.timeouts) == 1 and 0 < model.timeouts[0] <= 0.5
