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
