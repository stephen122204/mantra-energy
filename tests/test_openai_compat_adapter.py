"""Provider-response fixtures for the shared OpenAI-compatible adapter."""

import json
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
    def __init__(self, *, lines=(), body=None):
        self._lines = list(lines)
        self._body = body
        self.status_code = 200

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
    responses = iter([requests.ConnectionError("stream unavailable"), non_streaming])

    def post(*args, **kwargs):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(requests, "post", post)

    result = ollama_adapter.call("Say hello", temperature=0.0)

    assert result["content"] == "Hello world"
    assert result["phase_metrics"]["streaming_enabled"] == 0


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
