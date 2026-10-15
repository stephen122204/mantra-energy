import json
import importlib
import os
import unittest
from unittest.mock import Mock, patch

from core.execution.adapters.openai_compat import OpenAICompatAdapter
from core.execution.agentic import AgenticExecutor
from core.execution.model_factory import ModelFactory


# Resolve the actual module object: earlier fixture modules may prepopulate
# sys.modules without parent attributes, which breaks Python 3.10 string patches.
adapter_module = importlib.import_module("core.execution.adapters.openai_compat")


def provider(provider_id, **overrides):
    values = {
        "provider_id": provider_id,
        "base_url": "http://127.0.0.1:8000/v1",
        "is_local": provider_id.endswith("_local"),
        "network_type": "loopback" if provider_id.endswith("_local") else "lan",
        "execution_site": "host" if provider_id.endswith("_local") else "remote_vm",
        "transport": "loopback_http" if provider_id.endswith("_local") else "remote_http",
        "api_key_env": None,
        "openai_compat": True,
    }
    values.update(overrides)
    return values


def model():
    return {"model_id": "test-model", "max_tokens": 32}


class FakeStreamResponse:
    status_code = 200
    headers = {}

    def close(self):
        pass

    def __init__(self, chunks):
        self._chunks = chunks

    def raise_for_status(self):
        return None

    def iter_lines(self):
        for chunk in self._chunks:
            if chunk == "[DONE]":
                yield b"data: [DONE]"
            else:
                yield ("data: " + json.dumps(chunk)).encode("utf-8")


class OpenAICompatAvailabilityTests(unittest.TestCase):
    @patch.object(adapter_module.requests, "get")
    def test_vllm_local_uses_models_endpoint(self, get):
        get.return_value.status_code = 200
        adapter = OpenAICompatAdapter(provider("vllm_local"), model())
        self.assertTrue(adapter.is_available())
        get.assert_called_once_with("http://127.0.0.1:8000/v1/models", timeout=2)

    @patch.object(adapter_module.requests, "get")
    def test_vllm_availability_handles_non_2xx_and_connection_failure(self, get):
        adapter = OpenAICompatAdapter(provider("vllm_local"), model())
        get.return_value.status_code = 503
        self.assertFalse(adapter.is_available())
        get.side_effect = OSError("connection refused")
        self.assertFalse(adapter.is_available())

    @patch.object(adapter_module.requests, "get")
    def test_ollama_still_uses_tags_endpoint(self, get):
        get.return_value.status_code = 200
        config = provider(
            "ollama_local", base_url="http://127.0.0.1:11434")
        adapter = OpenAICompatAdapter(config, model())
        self.assertTrue(adapter.is_available())
        get.assert_called_once_with("http://127.0.0.1:11434/api/tags", timeout=2)

    @patch.object(adapter_module.requests, "get")
    def test_cloud_readiness_remains_api_key_based(self, get):
        config = provider(
            "openai", is_local=False, network_type="internet",
            api_key_env="ALEMS_TEST_MISSING_API_KEY",
            base_url="https://api.openai.com/v1")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALEMS_TEST_MISSING_API_KEY", None)
            self.assertFalse(OpenAICompatAdapter(config, model()).is_available())
        get.assert_not_called()


class OpenAICompatUsageTests(unittest.TestCase):
    @patch.object(adapter_module.requests, "post")
    def test_vllm_stream_requests_and_preserves_terminal_usage(self, post):
        post.return_value = FakeStreamResponse([
            {"choices": [{"delta": {"content": "hello"}}]},
            {"choices": [{"delta": {"content": " world"}}]},
            {"choices": [], "usage": {
                "prompt_tokens": 45, "completion_tokens": 7,
                "total_tokens": 55,
            }},
            "[DONE]",
        ])
        adapter = OpenAICompatAdapter(provider("vllm_local"), model())
        result = adapter.call("a short prompt", 0.0)

        sent = post.call_args.kwargs["json"]
        self.assertTrue(sent["stream"])
        self.assertEqual(sent["stream_options"], {"include_usage": True})
        self.assertEqual(result["content"], "hello world")
        self.assertEqual(result["tokens"], {
            "prompt": 45, "completion": 7, "total": 55})
        self.assertEqual(result["token_provenance"], "provider")

    def test_non_streaming_usage_is_preserved(self):
        adapter = OpenAICompatAdapter(provider("vllm_local"), model())
        content, tokens = adapter._parse_response({
            "choices": [{"message": {"content": "answer"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 3,
                      "total_tokens": 14},
        }, "prompt")
        self.assertEqual(content, "answer")
        self.assertEqual(tokens, {"prompt": 11, "completion": 3, "total": 14})
        self.assertEqual(adapter._last_token_provenance, "provider")

    @patch.object(adapter_module.requests, "post")
    def test_ollama_stream_does_not_receive_openai_stream_options(self, post):
        post.return_value = FakeStreamResponse(["[DONE]"])
        adapter = OpenAICompatAdapter(provider(
            "ollama_local", base_url="http://127.0.0.1:11434"), model())
        with self.assertRaises(ValueError):
            adapter._http_call(adapter._build_payload("prompt", 0.0))
        self.assertNotIn("stream_options", post.call_args.kwargs["json"])


class OpenAICompatTimingTests(unittest.TestCase):
    def call_with(self, provider_config):
        adapter = OpenAICompatAdapter(provider_config, model())
        adapter._http_call = Mock(return_value={
            "choices": [{"message": {"content": "answer"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2,
                      "total_tokens": 6},
        })
        adapter._get_network_counters = Mock(return_value={
            "bytes_sent": 0, "bytes_recv": 0, "tcp_retransmits": 0})
        with patch.object(adapter_module.time, "perf_counter",
                   side_effect=[1.0, 1.001, 2.0, 2.025, 3.0, 3.002]), \
             patch.object(adapter_module.psutil, "cpu_percent",
                   return_value=0.0):
            return adapter.call("prompt", 0.0)

    def test_vllm_local_is_local_compute(self):
        metrics = self.call_with(provider("vllm_local"))["phase_metrics"]
        self.assertAlmostEqual(metrics["local_compute_ms"], 25.0)
        self.assertEqual(metrics["non_local_ms"], 0.0)

    def test_ollama_local_is_local_compute(self):
        metrics = self.call_with(provider("ollama_local"))["phase_metrics"]
        self.assertAlmostEqual(metrics["local_compute_ms"], 25.0)
        self.assertEqual(metrics["non_local_ms"], 0.0)

    def test_vllm_remote_is_non_local(self):
        metrics = self.call_with(provider("vllm_remote"))["phase_metrics"]
        self.assertAlmostEqual(metrics["non_local_ms"], 25.0)
        self.assertEqual(metrics["local_compute_ms"], 0.0)

    @patch.object(adapter_module.requests, "get")
    def test_model_factory_uses_real_vllm_provider_metadata(self, get):
        get.return_value.status_code = 200
        adapter = ModelFactory.get_adapter("vllm_local", {
            "model_id": "meta-llama/Llama-3.1-8B-Instruct",
            "max_tokens": 32,
        })
        self.assertIsInstance(adapter, OpenAICompatAdapter)
        self.assertTrue(adapter._is_local)
        self.assertFalse(adapter._is_ollama)
        self.assertTrue(adapter.is_available())
        get.assert_called_once_with("http://localhost:8000/v1/models", timeout=2)

    def test_agentic_executor_retains_adapter_token_counts(self):
        executor = object.__new__(AgenticExecutor)
        executor.config = {"is_local": True, "model_id": "test-model"}
        executor.provider = "vllm_local"
        executor.temperature = 0.0
        executor.api_key = None
        executor._adapter = Mock()
        executor._adapter.require_success.side_effect = lambda result: result
        executor._adapter.call.return_value = {
            "content": "answer",
            "tokens": {"prompt": 45, "completion": 7, "total": 52},
            "token_provenance": "provider",
            "total_time_ms": 10.0,
            "phase_metrics": {
                "preprocess_ms": 0.1, "non_local_ms": 0.0,
                "local_compute_ms": 9.8, "postprocess_ms": 0.1,
                "app_throughput_kbps": 1.0,
                "cpu_percent_during_wait": 0.0,
            },
            "bytes_sent": 0, "bytes_recv": 0, "tcp_retransmits": 0,
        }
        result = executor._call_llm("prompt", 0.0)
        self.assertEqual(result["tokens"], {
            "prompt": 45, "completion": 7, "total": 52})
        self.assertEqual(result["token_provenance"], "provider")
        self.assertEqual(executor.pending_interactions[0]["prompt_tokens"], 45)
        self.assertEqual(
            executor.pending_interactions[0]["token_provenance"], "provider")


if __name__ == "__main__":
    unittest.main()
