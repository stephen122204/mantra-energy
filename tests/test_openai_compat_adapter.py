"""Provider-response fixtures for the shared OpenAI-compatible adapter."""

import json
import hashlib
import sys
from pathlib import Path
from types import ModuleType

import pytest
import requests

# Import the adapter without executing core.execution.__init__, which eagerly
# imports the complete tool stack (and its optional runtime dependencies).
_EXECUTION_DIR = Path(__file__).parents[1] / "core" / "execution"
_execution_package = ModuleType("core.execution")
_execution_package.__path__ = [str(_EXECUTION_DIR)]
sys.modules.setdefault("core.execution", _execution_package)
_adapters_package = ModuleType("core.execution.adapters")
_adapters_package.__path__ = [str(_EXECUTION_DIR / "adapters")]
sys.modules.setdefault("core.execution.adapters", _adapters_package)

from core.execution.adapters.openai_compat import OpenAICompatAdapter


class StubResponse:
    def __init__(self, *, lines=(), body=None, headers=None):
        self._lines = list(lines)
        self._body = body
        self.status_code = 200
        self.headers = headers or {}
        self.closed = False

    def close(self):
        self.closed = True

    def raise_for_status(self):
        return None

    def iter_lines(self):
        return iter(self._lines)

    def json(self):
        return self._body


class InterruptedResponse(StubResponse):
    def iter_lines(self):
        yield from self._lines
        raise requests.ConnectionError("stream interrupted")


def encoded_lines(*chunks):
    return [json.dumps(chunk).encode("utf-8") for chunk in chunks]


@pytest.fixture
def ollama_adapter():
    return OpenAICompatAdapter(
        {
            "provider_id": "ollama_local",
            "base_url": "http://localhost:11434",
            "network_type": "loopback",
            "is_local": True,
        },
        {
            "model_id": "tinyllama-1b",
            "max_tokens": 32,
            "network_type": "loopback",
            "is_local": True,
        },
    )


@pytest.fixture
def openai_adapter():
    return OpenAICompatAdapter(
        {
            "provider_id": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "network_type": "internet",
            "is_local": False,
        },
        {
            "model_id": "fixture-model",
            "max_tokens": 32,
            "network_type": "internet",
            "is_local": False,
            "_resolved_api_key": "fixture-key",
        },
    )


@pytest.fixture
def ollama_stream_response():
    return StubResponse(
        lines=encoded_lines(
            {
                "model": "tinyllama-1b",
                "message": {"role": "assistant", "content": "Hello"},
                "done": False,
            },
            {
                "model": "tinyllama-1b",
                "message": {"role": "assistant", "content": " world"},
                "done": False,
            },
            {
                "model": "tinyllama-1b",
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 5,
                "eval_count": 2,
            },
        )
    )


def test_ollama_streamed_ndjson_assembles_content(
    monkeypatch, ollama_adapter, ollama_stream_response
):
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: ollama_stream_response)

    result = ollama_adapter.call("Say hello", temperature=0.0)

    assert result["content"] == "Hello world"


def test_ollama_streamed_ndjson_preserves_terminal_token_metadata(
    monkeypatch, ollama_adapter, ollama_stream_response
):
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: ollama_stream_response)

    result = ollama_adapter.call("Say hello", temperature=0.0)

    assert result["tokens"] == {"prompt": 5, "completion": 2, "total": 7}


def test_ollama_non_streaming_output(monkeypatch, ollama_adapter):
    non_streaming = StubResponse(
        body={
            "model": "tinyllama-1b",
            "message": {"role": "assistant", "content": "Hello world"},
            "done": True,
            "prompt_eval_count": 5,
            "eval_count": 2,
        }
    )
    ollama_adapter.model_config["stream"] = False
    calls = []
    def post(*args, **kwargs):
        calls.append(kwargs)
        return non_streaming
    monkeypatch.setattr(requests, "post", post)

    result = ollama_adapter.call("Say hello", temperature=0.0)

    assert result["content"] == "Hello world"
    assert result["phase_metrics"]["streaming_enabled"] == 0
    assert len(calls) == 1
    assert calls[0]["json"]["stream"] is False
    assert non_streaming.closed


def test_openai_compatible_sse_streaming_regression(monkeypatch, openai_adapter):
    response = StubResponse(
        lines=[
            b'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            b'data: {"choices":[{"delta":{"content":" world"}}]}',
            b'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2,"total_tokens":7}}',
            b"data: [DONE]",
        ]
    )
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: response)
    monkeypatch.setattr(openai_adapter, "_get_network_counters", lambda: {
        "bytes_sent": 0,
        "bytes_recv": 0,
        "tcp_retransmits": 0,
    })
    adapter_module = sys.modules["core.execution.adapters.openai_compat"]
    monkeypatch.setattr(adapter_module.psutil, "cpu_percent", lambda **kwargs: 0.0)

    result = openai_adapter.call("Say hello", temperature=0.0)

    assert result["content"] == "Hello world"
    assert result["tokens"] == {"prompt": 5, "completion": 2, "total": 7}
    assert result["phase_metrics"]["streaming_enabled"] == 1


def test_interrupted_ollama_stream_is_visible_and_not_retried(monkeypatch, ollama_adapter):
    response = InterruptedResponse(
        lines=encoded_lines({
            "message": {"role": "assistant", "content": "partial"},
            "done": False,
        })
    )
    calls = []

    def post(*args, **kwargs):
        calls.append(kwargs)
        return response

    monkeypatch.setattr(requests, "post", post)

    result = ollama_adapter.call("Say hello", temperature=0.0)

    assert len(calls) == 1
    assert result["content"] == "Error: stream interrupted"


def test_malformed_ollama_ndjson_is_visible_as_failure(monkeypatch, ollama_adapter):
    response = StubResponse(lines=[b"not-json"])
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: response)

    result = ollama_adapter.call("Say hello", temperature=0.0)

    assert result["content"].startswith("Error:")


def test_ollama_missing_terminal_counts_uses_estimates(monkeypatch, ollama_adapter):
    response = StubResponse(lines=encoded_lines(
        {"message": {"role": "assistant", "content": "Hello world"}, "done": False},
        {"message": {"role": "assistant", "content": ""}, "done": True},
    ))
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: response)

    result = ollama_adapter.call("Say hello", temperature=0.0)

    assert result["tokens"] == {"prompt": 2, "completion": 2, "total": 4}
    assert result["token_provenance"] == "estimated"


def test_ollama_provider_zero_token_counts_are_preserved(monkeypatch, ollama_adapter):
    response = StubResponse(lines=encoded_lines({
        "message": {"role": "assistant", "content": ""},
        "done": True,
        "prompt_eval_count": 0,
        "eval_count": 0,
    }))
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: response)

    result = ollama_adapter.call("Say hello", temperature=0.0)

    assert result["tokens"] == {"prompt": 0, "completion": 0, "total": 0}
    assert result["token_provenance"] == "provider"


def test_ollama_error_chunk_is_visible_as_failure(monkeypatch, ollama_adapter):
    response = StubResponse(lines=encoded_lines({"error": "model unavailable"}))
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: response)

    result = ollama_adapter.call("Say hello", temperature=0.0)

    assert result["content"] == "Error: model unavailable"


def test_ollama_stream_without_terminal_done_is_visible_as_failure(
    monkeypatch, ollama_adapter
):
    response = StubResponse(lines=encoded_lines({
        "message": {"role": "assistant", "content": "partial"},
        "done": False,
    }))
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: response)

    result = ollama_adapter.call("Say hello", temperature=0.0)

    assert result["content"].startswith("Error:")

@pytest.mark.parametrize('provider', ['ollama_adapter', 'openai_adapter'])
def test_timeout_before_first_chunk_never_retries(monkeypatch, request, provider):
    adapter = request.getfixturevalue(provider)
    calls = []
    def post(*args, **kwargs):
        calls.append(kwargs)
        raise requests.ReadTimeout('request accepted but no response yet')
    monkeypatch.setattr(requests, 'post', post)
    result = adapter.call('hello', 0)
    assert len(calls) == 1
    assert result['status'] == 'error'
    assert result['token_provenance'] == 'unknown'
    assert result['tokens'] == {}

@pytest.mark.parametrize('provider', ['ollama_adapter', 'openai_adapter'])
def test_interruption_preserves_partial_output_and_elapsed_time(monkeypatch, request, provider):
    adapter = request.getfixturevalue(provider)
    clock = {'now': 100.0}
    class TimedResponse(StubResponse):
        def iter_lines(self):
            clock['now'] += .5
            yield from self._lines
            clock['now'] += .5
            raise requests.ConnectionError('interrupted')
    lines = (encoded_lines({'message': {'content': 'partial'}, 'done': False})
             if provider == 'ollama_adapter' else
             [b'data: {"choices":[{"delta":{"content":"partial"}}]}'])
    response = TimedResponse(lines=lines)
    calls = []
    def post(*args, **kwargs):
        calls.append(kwargs)
        return response
    monkeypatch.setattr(requests, 'post', post)
    module = sys.modules['core.execution.adapters.openai_compat']
    monkeypatch.setattr(module.time, 'time', lambda: clock['now'])
    monkeypatch.setattr(module.time, 'perf_counter', lambda: clock['now'])
    monkeypatch.setattr(module.time, 'perf_counter_ns', lambda: int(clock['now'] * 1e9))
    result = adapter.call('hello', 0)
    assert len(calls) == 1
    assert result['total_time_ms'] == pytest.approx(1000)
    assert result['partial_content'] == 'partial'
    assert result['content'].startswith('Error:')
    assert result['token_provenance'] == 'unknown'
    phase = 'local_compute_ms' if provider == 'ollama_adapter' else 'non_local_ms'
    assert result['phase_metrics'][phase] == pytest.approx(1000)

@pytest.mark.parametrize('usage,expected,provenance', [
    (None, {'prompt': 2, 'completion': 4, 'total': 6}, 'estimated'),
    ({'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0},
     {'prompt': 0, 'completion': 0, 'total': 0}, 'provider'),
    ({'prompt_tokens': 9}, {'prompt': 9, 'completion': 4, 'total': 13}, 'estimated'),
    ({'completion_tokens': 7}, {'prompt': 2, 'completion': 7, 'total': 9}, 'estimated'),
])
def test_sse_usage_provenance(monkeypatch, openai_adapter, usage, expected, provenance):
    lines = [b'data: {"choices":[{"delta":{"content":"one two three four"}}]}']
    if usage is not None:
        lines += [b'data: ' + json.dumps({'choices': [], 'usage': usage}).encode()]
    lines += [b'data: [DONE]']
    monkeypatch.setattr(requests, 'post', lambda *a, **k: StubResponse(lines=lines))
    result = openai_adapter.call('hello world', 0)
    assert result['tokens'] == expected
    assert result['token_provenance'] == provenance
    from studies.energy_diagnosis.contracts import ModelResponse
    # The executor supplies request identity and its own clock-domain endpoints.
    normalized = ModelResponse(
        request_id='fixture-request', status='completed', model_hash='fixture-model',
        started_ns=1, ended_ns=2, clock_domain='fixture-clock', text=result['content'],
        prompt_tokens=result['tokens']['prompt'], completion_tokens=result['tokens']['completion'],
        token_provenance=result['token_provenance'],
    )
    assert ModelResponse.from_json(normalized.to_json()) == normalized
    if not usage or 'completion_tokens' not in usage:
        assert result['phase_metrics']['tpot_ms'] is None
        assert result['phase_metrics']['token_throughput'] is None

@pytest.mark.parametrize('provider', ['ollama_adapter', 'openai_adapter'])
def test_server_can_return_json_without_a_second_request(monkeypatch, request, provider):
    adapter = request.getfixturevalue(provider)
    body = ({'message': {'content': 'answer'}, 'done': True,
             'prompt_eval_count': 0, 'eval_count': 3}
            if provider == 'ollama_adapter' else
            {'choices': [{'message': {'content': 'answer'}}],
             'usage': {'prompt_tokens': 0, 'completion_tokens': 3}})
    response = StubResponse(body=body, headers={'Content-Type': 'application/json; charset=utf-8'})
    calls = []
    def post(*a, **k):
        calls.append(k)
        return response
    monkeypatch.setattr(requests, 'post', post)
    result = adapter.call('hello', 0)
    assert len(calls) == 1
    assert result['content'] == 'answer'
    assert result['tokens'] == {'prompt': 0, 'completion': 3, 'total': 3}
    assert result['token_provenance'] == 'provider'
    assert result['phase_metrics']['streaming_enabled'] == 0
    assert result['phase_metrics']['ttft_ms'] is None
    assert result['phase_metrics']['first_token_time_ns'] is None
    assert response.closed


@pytest.mark.parametrize('provider,body,expected', [
    ('ollama_adapter',
     {'message': {'content': False}, 'done': True,
      'prompt_eval_count': 4, 'eval_count': 2},
     {'prompt': 4, 'completion': 2}),
    ('openai_adapter',
     {'choices': [{'message': {'content': False}}],
      'usage': {'prompt_tokens': 4, 'completion_tokens': 2}},
     {'prompt': 4, 'completion': 2}),
])
def test_json_parse_failure_retains_provider_token_observations(
    monkeypatch, request, provider, body, expected
):
    adapter = request.getfixturevalue(provider)
    adapter.model_config['stream'] = False
    monkeypatch.setattr(requests, 'post', lambda *a, **k: StubResponse(body=body))

    result = adapter.call('hello', 0)

    assert result['status'] == 'error'
    assert result['tokens'] == {}
    assert result['token_provenance'] == 'unknown'
    assert result['observed_tokens'] == expected


@pytest.mark.parametrize('provider,bad_content', [
    ('ollama_adapter', 0),
    ('ollama_adapter', False),
    ('ollama_adapter', []),
    ('openai_adapter', 0),
    ('openai_adapter', False),
    ('openai_adapter', []),
])
def test_stream_rejects_falsy_non_text_content(
    monkeypatch, request, provider, bad_content
):
    adapter = request.getfixturevalue(provider)
    chunk = ({'message': {'content': bad_content}, 'done': True}
             if provider == 'ollama_adapter' else
             {'choices': [{'delta': {'content': bad_content}, 'finish_reason': 'stop'}]})
    lines = (encoded_lines(chunk) if provider == 'ollama_adapter' else
             [b'data: ' + json.dumps(chunk).encode(), b'data: [DONE]'])
    monkeypatch.setattr(requests, 'post', lambda *a, **k: StubResponse(lines=lines))

    result = adapter.call('hello', 0)

    assert result['status'] == 'error'
    assert result['content'] == 'Error: provider content must be text'


def test_malformed_ollama_terminal_retains_provider_token_observations(
    monkeypatch, ollama_adapter
):
    response = StubResponse(lines=encoded_lines({
        'message': {'content': False},
        'done': True,
        'prompt_eval_count': 7,
        'eval_count': 3,
    }))
    monkeypatch.setattr(requests, 'post', lambda *a, **k: response)

    result = ollama_adapter.call('hello', 0)

    assert result['status'] == 'error'
    assert result['tokens'] == {}
    assert result['token_provenance'] == 'unknown'
    assert result['observed_tokens'] == {'prompt': 7, 'completion': 3}
    assert result['content'] == 'Error: provider content must be text'


def locality_adapter(provider_id, *, is_cloud):
    return OpenAICompatAdapter(
        {
            'provider_id': provider_id,
            'type': 'cloud_api' if is_cloud else 'local_openai',
            'base_url': 'https://example.invalid' if is_cloud else 'http://127.0.0.1:8000',
        },
        {
            'model_id': 'fixture-model',
            'max_tokens': 32,
            'network_type': 'internet' if is_cloud else 'loopback',
            'is_local': not is_cloud,
            '_resolved_api_key': 'fixture-key' if is_cloud else None,
            'stream': False,
        },
    )


@pytest.mark.parametrize('provider_id,is_cloud,body', [
    ('ollama_remote', True,
     {'message': {'content': 'answer'}, 'done': True,
      'prompt_eval_count': 1, 'eval_count': 1}),
    ('vllm_local', False,
     {'choices': [{'message': {'content': 'answer'}}],
      'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}),
])
@pytest.mark.parametrize('fails', [False, True])
def test_timing_attribution_follows_locality_not_protocol(
    monkeypatch, provider_id, is_cloud, body, fails
):
    adapter = locality_adapter(provider_id, is_cloud=is_cloud)
    times = iter([1.0, 1.1, 2.0, 3.0] if fails else [1.0, 1.1, 2.0, 3.0, 4.0, 4.1])
    throughput_latencies = []
    module = sys.modules['core.execution.adapters.openai_compat']
    monkeypatch.setattr(module.time, 'perf_counter', lambda: next(times))
    if fails:
        def fail(*args, **kwargs):
            raise requests.ConnectionError('provider unavailable')
        monkeypatch.setattr(requests, 'post', fail)
    else:
        monkeypatch.setattr(requests, 'post', lambda *a, **k: StubResponse(body=body))
        monkeypatch.setattr(
            adapter, '_throughput_kbps',
            lambda prompt_bytes, response_bytes, latency_ms: throughput_latencies.append(
                latency_ms
            ) or 1.0,
        )
    if is_cloud:
        monkeypatch.setattr(adapter, '_get_network_counters', lambda: None)
        monkeypatch.setattr(module.psutil, 'cpu_percent', lambda **kwargs: 0.0)

    result = adapter.call('hello', 0)

    assert result['status'] == ('error' if fails else 'ok')
    local_ms = result['phase_metrics']['local_compute_ms']
    non_local_ms = result['phase_metrics']['non_local_ms']
    expected = (0.0, 1000.0) if is_cloud else (1000.0, 0.0)
    assert (local_ms, non_local_ms) == expected
    if not fails:
        assert throughput_latencies == pytest.approx(
            [1000.0 if is_cloud else 1200.0]
        )

@pytest.mark.parametrize('response', [
    StubResponse(lines=[b'data: malformed']),
    StubResponse(lines=[b'data: {"choices":[{"delta":{"content":"partial"}}]}']),
    StubResponse(lines=[b'data: {"error":{"message":"server failed"}}']),
    InterruptedResponse(lines=[b'data: {"choices":[{"delta":{"content":"partial"}}]}']),
    StubResponse(body={'choices': []}, headers={'Content-Type': 'application/json'}),
])
def test_openai_bad_responses_fail_close_and_never_retry(monkeypatch, openai_adapter, response):
    calls = []
    def post(*a, **k):
        calls.append(k)
        return response
    monkeypatch.setattr(requests, 'post', post)
    result = openai_adapter.call('hello', 0)
    assert len(calls) == 1
    assert result['status'] == 'error'
    assert result['content'].startswith('Error:')
    assert response.closed


def test_http_rejection_does_not_retry(monkeypatch, ollama_adapter):
    response = StubResponse()
    calls = []
    def reject():
        raise requests.HTTPError('400 stream unsupported')
    response.raise_for_status = reject
    def post(*a, **k):
        calls.append(k)
        return response
    monkeypatch.setattr(requests, 'post', post)
    result = ollama_adapter.call('hello', 0)
    assert result['status'] == 'error'
    assert len(calls) == 1
    assert response.closed


def test_usage_fields_in_separate_sse_chunks_are_preserved(monkeypatch, openai_adapter):
    response = StubResponse(lines=[
        b'data: {"choices":[{"delta":{"content":"hello"}}],"usage":{"prompt_tokens":10}}',
        b'data: {"choices":[],"usage":{"completion_tokens":8}}',
        b'data: [DONE]',
    ])
    monkeypatch.setattr(requests, 'post', lambda *a, **k: response)
    result = openai_adapter.call('hello', 0)
    assert result['tokens'] == {'prompt': 10, 'completion': 8, 'total': 18}
    assert result['token_provenance'] == 'provider'


def test_failed_call_does_not_reuse_previous_content_or_usage(monkeypatch, ollama_adapter, ollama_stream_response):
    monkeypatch.setattr(requests, 'post', lambda *a, **k: ollama_stream_response)
    assert ollama_adapter.call('hello', 0)['status'] == 'ok'
    def fail(*a, **k):
        raise requests.ReadTimeout('no response')
    monkeypatch.setattr(requests, 'post', fail)
    failed = ollama_adapter.call('hello', 0)
    assert failed['partial_content'] == ''
    assert failed['observed_tokens'] == {}
    assert failed['tokens'] == {}
    assert failed['phase_metrics']['first_token_time_ns'] is None


def test_failure_retains_observed_provider_counts_and_network_delta(monkeypatch, openai_adapter):
    response = InterruptedResponse(lines=[
        b'data: {"choices":[{"delta":{"content":"partial"}}],"usage":{"prompt_tokens":4}}',
    ])
    snapshots = iter([{'bytes_sent': 10, 'bytes_recv': 20, 'tcp_retransmits': 0},
                      {'bytes_sent': 110, 'bytes_recv': 220, 'tcp_retransmits': 1}])
    monkeypatch.setattr(openai_adapter, '_get_network_counters', lambda: next(snapshots))
    monkeypatch.setattr(requests, 'post', lambda *a, **k: response)
    result = openai_adapter.call('hello', 0)
    assert result['observed_tokens'] == {'prompt': 4}
    assert result['tokens'] == {}
    assert result['bytes_sent'] == 100
    assert result['bytes_recv'] == 200
    assert result['tcp_retransmits'] == 1


def test_stream_durations_ignore_wall_clock_adjustments(monkeypatch, ollama_adapter):
    mono = iter([100_000_000, 200_000_000, 300_000_000])
    wall = iter([3_000_000_000, 2_000_000_000, 1_000_000_000])
    module = sys.modules['core.execution.adapters.openai_compat']
    monkeypatch.setattr(module.time, 'perf_counter_ns', lambda: next(mono))
    monkeypatch.setattr(module.time, 'time_ns', lambda: next(wall))
    response = StubResponse(lines=encoded_lines(
        {'message': {'content': 'one '}, 'done': False},
        {'message': {'content': 'two'}, 'done': True, 'prompt_eval_count': 2, 'eval_count': 2},
    ))
    monkeypatch.setattr(requests, 'post', lambda *a, **k: response)
    result = ollama_adapter.call('hello', 0)
    assert result['phase_metrics']['ttft_ms'] == pytest.approx(100)
    assert result['phase_metrics']['tpot_ms'] == pytest.approx(100)
    assert result['phase_metrics']['token_throughput'] == pytest.approx(20)


@pytest.mark.parametrize('provider', ['ollama_adapter', 'openai_adapter'])
@pytest.mark.parametrize('capture', [False, True])
def test_real_http_client_reads_local_fixture_stream(request, provider, capture, tmp_path):
    """Exercise requests' real line iterator/headers, without a model or remote API."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    adapter = request.getfixturevalue(provider)
    if capture:
        adapter.model_config['response_capture_path'] = str(tmp_path / 'provider.body')
    seen = []
    if provider == 'ollama_adapter':
        body = b'\n'.join(encoded_lines(
            {'message': {'content': 'hello'}, 'done': False},
            {'message': {'content': ''}, 'done': True, 'prompt_eval_count': 2, 'eval_count': 1},
        )) + b'\n'
        media_type = 'application/x-ndjson'
    else:
        body = (b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
                b'data: {"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":1}}\n\n'
                b'data: [DONE]\n\n')
        media_type = 'text/event-stream'
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200)
            self.send_header('Content-Type', media_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        adapter._base_url = f'http://127.0.0.1:{server.server_port}'
        try:
            result = adapter.call('hello', 0)
        finally:
            server.shutdown()
            thread.join(timeout=2)
    assert len(seen) == 1
    assert result['status'] == 'ok'
    assert result['content'] == 'hello'
    assert result['tokens'] == {'prompt': 2, 'completion': 1, 'total': 3}
    if capture:
        saved = (tmp_path / 'provider.body').read_bytes()
        assert saved == body
        assert result['provider_response'] == dict(body_complete=True, bytes_received=len(body),
                                                   sha256=hashlib.sha256(body).hexdigest())
    else:
        assert 'provider_response' not in result


class ByteBodyResponse(requests.Response):
    def __init__(self, body, *, fail=False, **kwargs):
        super().__init__()
        self.status_code = 200
        self.headers = requests.structures.CaseInsensitiveDict(kwargs.get('headers', {}))
        self.encoding = requests.utils.get_encoding_from_headers(self.headers)
        self.closed = False
        self.body, self.fail = body, fail

    def close(self):
        self.closed = True

    def iter_content(self, chunk_size):
        # Deliberately split UTF-8 characters, CRLF separators and JSON tokens.
        for offset in range(0, len(self.body), 3):
            yield self.body[offset:offset + 3]
        if self.fail:
            raise requests.ConnectionError('fixture interrupted body')


@pytest.mark.parametrize('stream', [True, False])
def test_capture_keeps_exact_body_and_native_fields_without_headers(monkeypatch, ollama_adapter, tmp_path, stream):
    chunk = {'message': {'content': 'h\u00e9', 'tool_calls': [{'function': {'name': 'inspect_asset', 'arguments': {}}}]},
             'done': True, 'prompt_eval_count': 3, 'eval_count': 2, 'extra': 'retained'}
    body = json.dumps(chunk, ensure_ascii=False).encode('utf-8')
    if stream:
        body = b'\r\n' + body + b'\r\n\r\nAFTER_DONE_TRAILER\n'
    response = ByteBodyResponse(body, headers={'Content-Type': 'application/x-ndjson' if stream else 'application/json',
                                             'Set-Cookie': 'fixture-cookie-secret'})
    path = tmp_path / 'raw.body'
    ollama_adapter.model_config.update(response_capture_path=str(path), stream=stream)
    ollama_adapter._api_key = 'fixture-credential-secret'
    # Ollama normally omits authorization; inject a header to test capture's
    # exclusion independently of provider authentication policy.
    monkeypatch.setattr(ollama_adapter, '_build_headers', lambda: {
        'Authorization': 'Bearer fixture-credential-secret'})
    sent = []
    def post(*args, **kwargs):
        sent.append(kwargs)
        return response
    monkeypatch.setattr(requests, 'post', post)
    result = ollama_adapter.call('request-only-sensitive-text', 0)
    assert result['status'] == 'ok' and result['content'] == 'h\u00e9'
    assert len(sent) == 1 and sent[0]['headers']['Authorization'].endswith('fixture-credential-secret')
    assert path.read_bytes() == body
    assert b'inspect_asset' in body and b'fixture-credential-secret' not in body
    assert b'fixture-cookie-secret' not in body and b'request-only-sensitive-text' not in body
    assert result['provider_response'] == dict(body_complete=True, bytes_received=len(body),
                                               sha256=hashlib.sha256(body).hexdigest())
    assert response.closed


@pytest.mark.parametrize('failure', ['transport', 'malformed', 'http'])
def test_capture_preserves_failed_body_without_retry_or_fabricated_completion(monkeypatch, ollama_adapter, tmp_path, failure):
    if failure == 'transport':
        body = b'{"message":{"content":"partial"},"done":false}\n'
    else:
        body = b'invalid-provider-json\r\n'
    response = ByteBodyResponse(body, fail=failure == 'transport')
    if failure == 'http':
        def raise_http_error():
            raise requests.HTTPError('fixture 500')
        response.raise_for_status = raise_http_error
    path = tmp_path / 'failed.body'
    ollama_adapter.model_config['response_capture_path'] = str(path)
    sent = []
    monkeypatch.setattr(requests, 'post', lambda *a, **k: sent.append(k) or response)
    result = ollama_adapter.call('inspect', 0)
    assert result['status'] == 'error' and len(sent) == 1
    assert path.read_bytes() == body
    assert result['provider_response']['body_complete'] is (failure != 'transport')
    assert result['provider_response']['sha256'] == hashlib.sha256(body).hexdigest()
    assert result['tokens'] == {} and response.closed
    if failure == 'transport':
        assert result['partial_content'] == 'partial'
    ollama_adapter.model_config.pop('response_capture_path')
    monkeypatch.setattr(requests, 'post', lambda *a, **k: StubResponse(lines=encoded_lines(
        {'message': {'content': 'next'}, 'done': True, 'prompt_eval_count': 1, 'eval_count': 1})))
    following = ollama_adapter.call('next', 0)
    assert following['status'] == 'ok' and 'provider_response' not in following


def test_capture_does_not_overwrite_existing_evidence(monkeypatch, ollama_adapter, tmp_path):
    path = tmp_path / 'existing.body'
    path.write_bytes(b'preserved evidence')
    ollama_adapter.model_config['response_capture_path'] = str(path)
    def forbidden_post(*args, **kwargs):
        pytest.fail('HTTP must not start when capture evidence already exists')
    monkeypatch.setattr(requests, 'post', forbidden_post)
    result = ollama_adapter.call('inspect', 0)
    assert result['status'] == 'error' and 'provider_response' not in result
    assert path.read_bytes() == b'preserved evidence'


def test_capture_deadline_retains_partial_bytes_and_never_claims_complete(monkeypatch, ollama_adapter, tmp_path):
    import itertools
    import core.execution.adapters.response_capture as capture_module
    path = tmp_path / 'deadline.body'
    response = ByteBodyResponse(b'partial received bytes')
    ollama_adapter.model_config['response_capture_path'] = str(path)
    # Exceed the existing request deadline on the first received chunk. This
    # tests capture accounting, not a real wall-clock or hardware timeout.
    ticks = itertools.count(step=10)
    monkeypatch.setattr(capture_module.time, 'perf_counter_ns', lambda: next(ticks))
    ollama_adapter.model_config['request_timeout_seconds'] = 1e-9
    monkeypatch.setattr(requests, 'post', lambda *a, **k: response)
    result = ollama_adapter.call('inspect', 0)
    assert result['status'] == 'error'
    assert path.read_bytes() == b'par'
    assert result['provider_response']['body_complete'] is False
    assert result['provider_response']['sha256'] == hashlib.sha256(b'par').hexdigest()
    assert response.closed


@pytest.mark.parametrize('stream', [False, True], ids=['non_streaming', 'streaming_json_fallback'])
def test_capture_json_matches_requests_declared_encoding_with_one_body_read(
        monkeypatch, ollama_adapter, tmp_path, stream):
    """Real localhost HTTP and Requests decoder; no model or GPU execution."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    value = {'message': {'content': 'caf\u00e9'}, 'done': True,
             'prompt_eval_count': 3, 'eval_count': 2}
    body = json.dumps(value, ensure_ascii=False).encode('iso-8859-1')
    content_type = 'application/json; charset=iso-8859-1'
    # Establish the original decoder result without another HTTP request.
    baseline = requests.Response()
    baseline.headers['Content-Type'] = content_type
    baseline.encoding = requests.utils.get_encoding_from_headers(baseline.headers)
    baseline._content = body
    baseline._content_consumed = True
    expected = baseline.json()
    assert expected['message']['content'] == 'caf\u00e9'

    observed = dict(http_requests=0, post_calls=0, transport_reads=0,
                    transport_bytes=0, json_calls=0, decoded=None)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            observed['http_requests'] += 1
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    def observe_response(response, *args, **kwargs):
        # The hook runs before Requests eagerly reads a non-streaming body.
        original_stream, original_json = response.raw.stream, response.json

        def read_once(*args, **kwargs):
            observed['transport_reads'] += 1
            for chunk in original_stream(*args, **kwargs):
                observed['transport_bytes'] += len(chunk)
                yield chunk

        def decode_original(*args, **kwargs):
            observed['json_calls'] += 1
            observed['decoded'] = original_json(*args, **kwargs)
            return observed['decoded']

        response.raw.stream, response.json = read_once, decode_original

    original_post = requests.post

    def post_once(*args, **kwargs):
        observed['post_calls'] += 1
        assert kwargs['stream'] is stream
        return original_post(*args, **kwargs, hooks={'response': observe_response})

    path = tmp_path / 'latin1.body'
    ollama_adapter.model_config.update(stream=stream, response_capture_path=str(path))
    monkeypatch.setattr(requests, 'post', post_once)
    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        ollama_adapter._base_url = f'http://127.0.0.1:{server.server_port}'
        try:
            result = ollama_adapter.call('encoding diagnostic', 0)
        finally:
            server.shutdown()
            thread.join(timeout=2)
    assert result['status'] == 'ok' and result['content'] == expected['message']['content']
    assert result['tokens'] == {'prompt': 3, 'completion': 2, 'total': 5}
    assert observed == dict(http_requests=1, post_calls=1, transport_reads=1,
                            transport_bytes=len(body), json_calls=1, decoded=expected)
    assert path.read_bytes() == body and b'caf\xe9' in body
    assert result['provider_response'] == dict(body_complete=True, bytes_received=len(body),
                                               sha256=hashlib.sha256(body).hexdigest())
