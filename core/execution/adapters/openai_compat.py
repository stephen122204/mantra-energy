"""
================================================================================
OPENAI COMPAT ADAPTER — covers vLLM, Groq, OpenAI, and Ollama
================================================================================

Purpose:
    One adapter class for OpenAI-compatible HTTP APIs and Ollama's native API.
    Endpoint selection, authentication, and execution locality are independent.

    Providers handled:
      groq          cloud_api    api.groq.com
      openai        cloud_api    api.openai.com
      ollama_local  local_ollama localhost:11434
      ollama_remote local_ollama 129.153.71.47:11434

    Network metrics are captured for non-local providers and zeroed for local
    loopback providers, regardless of which response protocol they use.

PAC: inherits TextGenABC — factory resolves, never imported directly elsewhere.

Author: A-LEMS Chunk 7
================================================================================
"""

import logging
import time
from typing import Any, Dict, Optional, Tuple

import psutil
import requests

from core.execution.adapters.base import TextGenABC

logger = logging.getLogger(__name__)

# Ollama chat endpoint path — same for local and remote
_OLLAMA_CHAT_PATH = "/api/chat"

# OpenAI-compat chat completions path (groq, openai)
_OAI_CHAT_PATH = "/chat/completions"


class OpenAICompatAdapter(TextGenABC):
    """
    Single adapter for all OpenAI-compatible endpoints.

    Dispatches to /api/chat (Ollama) or /chat/completions (cloud)
    based on provider type — both return the same shape to callers.
    """

    def __init__(self, provider_config: Dict, model_config: Dict):
        """
        Args:
            provider_config: models.json provider block
            model_config:    models.json per-model block
        """
        super().__init__(provider_config, model_config)

        self._base_url = provider_config.get("base_url", "").rstrip("/")
        self._api_key_env = provider_config.get("api_key_env", "")
        self._is_ollama = provider_config.get("provider_id", "").startswith("ollama")      # controls endpoint + response parsing
        # Protocol and locality are independent. vLLM and Ollama can both use
        # loopback HTTP, while their remote variants use the same wire format.
        is_local = provider_config.get("is_local", model_config.get("is_local"))
        network_type = provider_config.get(
            "network_type", model_config.get("network_type", ""))
        execution_site = provider_config.get(
            "execution_site", model_config.get("execution_site", ""))
        transport = provider_config.get(
            "transport", model_config.get("transport", ""))
        if is_local is None:
            is_local = (
                network_type == "loopback" or
                execution_site == "host" or
                transport == "loopback_http"
            )
        self._is_local = bool(is_local)
        self._is_cloud = not self._is_local
        self._requires_api_key = bool(self._api_key_env)

        # Lazy-resolve API key at call time — env may be set after init
        import os
       # use pre-resolved key if executor injected it, else resolve from env
        self._api_key = model_config.get('_resolved_api_key') or \
                        (os.getenv(self._api_key_env) if self._api_key_env else None)

    # -------------------------------------------------------------------------
    # Public ABC interface
    # -------------------------------------------------------------------------

    def get_name(self) -> str:
        """
        Returns:
            str: human-readable name for logs
        """
        return f"OpenAICompatAdapter({self.model_id} @ {self._base_url})"

    def is_available(self) -> bool:
        """
        Check adapter readiness without raising.

        Providers requiring credentials are ready when their API key is set.
        Ollama probes /api/tags; unauthenticated OpenAI-compatible services
        (including local or remote vLLM) probe /models.

        Returns:
            bool
        """
        if self._requires_api_key:
            # Cloud requires API key in env
            return bool(self._api_key)
        # Server readiness follows protocol, independently of execution site.
        readiness_url = (
            f"{self._base_url}/api/tags" if self._is_ollama
            else f"{self._base_url}/models"
        )
        try:
            r = requests.get(readiness_url, timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def call(self, prompt: str, temperature: float) -> Dict[str, Any]:
        """
        Execute one inference call against the OpenAI-compat endpoint.

        Phase timing mirrors old _call_ollama / _call_cloud exactly
        so harness.py sees identical _current_llm_metrics shape.

        Args:
            prompt:      full prompt string
            temperature: sampling temperature

        Returns:
            Standard adapter result dict (see TextGenABC.call docstring)
        """
        # Reset stream metrics — prevents stale bleed between calls (SPEC_04)
        self._last_stream_metrics = {}
        self._last_token_provenance = "unknown"
        # ── Phase 1: PRE-PROCESSING — local JSON build ────────────────────────
        t_pre = time.time()
        payload = self._build_payload(prompt, temperature)
        prompt_bytes = len(str(payload).encode("utf-8"))
        preprocess_ms = (time.time() - t_pre) * 1000

        # ── Network snapshot (cloud only) ─────────────────────────────────────
        net_before = self._get_network_counters() if self._is_cloud else None

        # ── Phase 2: WAIT / INFERENCE ─────────────────────────────────────────
        t_call = time.time()
        try:
            raw = self._http_call(payload)
        except Exception as e:
            logger.error("HTTP call failed [%s]: %s", self.get_name(), e)
            return self._error_result(str(e), preprocess_ms)

        call_ms = (time.time() - t_call) * 1000

        # CPU sample during remote wait — meaningful only for cloud
        cpu_wait = psutil.cpu_percent(interval=0.05) if self._is_cloud else 0.0

        # ── Phase 3: POST-PROCESSING — parse response ─────────────────────────
        t_post = time.time()
        content, tokens = self._parse_response(raw, prompt)
        response_bytes = len(content.encode("utf-8"))
        postprocess_ms = (time.time() - t_post) * 1000

        # ── Assign phase times by execution locality ──────────────────────────
        # Protocol selection is intentionally independent of this decision.
        if self._is_local:
            non_local_ms = 0.0
            local_compute_ms = call_ms
            # Throughput over total time for local (no network bottleneck)
            kbps = self._throughput_kbps(prompt_bytes, response_bytes,
                                          preprocess_ms + call_ms + postprocess_ms)
        else:
            non_local_ms = call_ms
            local_compute_ms = 0.0
            # Throughput over network time only for cloud
            kbps = self._throughput_kbps(prompt_bytes, response_bytes, non_local_ms)

        total_ms = preprocess_ms + call_ms + postprocess_ms

        # ── Network delta (cloud only) ────────────────────────────────────────
        net_delta = {"bytes_sent": 0, "bytes_recv": 0, "tcp_retransmits": 0}
        if self._is_cloud and net_before:
            net_delta = self._network_delta(net_before, self._get_network_counters())
        stream_metrics = getattr(self, '_last_stream_metrics', {})
        phase_metrics = self._make_phase_metrics(
            total_time_ms=total_ms,
            preprocess_ms=preprocess_ms,
            non_local_ms=non_local_ms,
            local_compute_ms=local_compute_ms,
            postprocess_ms=postprocess_ms,
            app_throughput_kbps=kbps,
            cpu_percent_during_wait=cpu_wait,
            # ttft_ms / tpot_ms populated by Chunk 4 streaming — NULL for now
            ttft_ms=stream_metrics.get("ttft_ms"),
            tpot_ms=stream_metrics.get("tpot_ms"),
            token_throughput=stream_metrics.get("token_throughput"),
            streaming_enabled=stream_metrics.get("streaming_enabled", 0),
            first_token_time_ns=stream_metrics.get("first_token_time_ns"),
            last_token_time_ns=stream_metrics.get("last_token_time_ns"), 
            request_start_ns=stream_metrics.get("request_start_ns"),           
        )

        return {
            "content": content,
            "tokens": tokens,
            "token_provenance": self._last_token_provenance,
            "total_time_ms": total_ms,
            "phase_metrics": phase_metrics,
            **net_delta,  # bytes_sent, bytes_recv, tcp_retransmits
        }

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _build_payload(self, prompt: str, temperature: float) -> Dict:
        """
        Build request payload for the appropriate endpoint.

        Ollama uses /api/chat with options.num_predict.
        OpenAI-compat uses /chat/completions with max_tokens.

        Args:
            prompt:      user prompt
            temperature: sampling temperature

        Returns:
            dict payload ready for requests.post json=
        """
        messages = [{"role": "user", "content": prompt}]
        if self._is_ollama:
            return {
                "model": self.model_id,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": self.max_tokens,
                },
            }
        # OpenAI-compat format (groq, openai)
        return {
            "model": self.model_id,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": temperature,
        }

    def _build_headers(self) -> Dict:
        """
        Build HTTP headers — Bearer token for cloud, none for ollama.

        Returns:
            dict headers
        """
        headers = {"Content-Type": "application/json"}
        if self._is_cloud and self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _endpoint_url(self) -> str:
        """
        Resolve full endpoint URL based on provider type.

        Returns:
            str URL
        """
        path = _OLLAMA_CHAT_PATH if self._is_ollama else _OAI_CHAT_PATH
        return f"{self._base_url}{path}"

    def _http_call(self, payload: Dict) -> Dict:
        """
        Execute HTTP POST with streaming enabled to capture TTFT and TPOT.
 
        Streams the response and records first-token and last-token timestamps.
        Assembles the full response body so _parse_response() sees identical
        input as before. Stores timing in self._last_stream_metrics for call()
        to pick up — avoids changing the return type of this method.
 
        For providers that do not support SSE streaming (e.g. custom endpoints
        with openai_compat=True but no stream support), falls back to
        non-streaming POST gracefully.
 
        Args:
            payload: dict ready for requests.post json= parameter
 
        Returns:
            dict: parsed JSON response (identical shape to non-streaming)
 
        Raises:
            requests.HTTPError on non-2xx response
        """
        import json as _json
 
        # Ask OpenAI-compatible servers for a terminal usage chunk. Native
        # Ollama /api/chat has a different payload contract.
        stream_payload = {**payload, "stream": True}
        if (not self._is_ollama and
                self.provider_config.get("stream_usage_supported", True)):
            stream_payload["stream_options"] = {"include_usage": True}
 
        url = self._endpoint_url()
        headers = self._build_headers()
 
        first_token_ns = None
        last_token_ns = None
        chunk_count = 0
        usage_completion_tokens = None
        usage_total_tokens = None
        assembled_content = []
        usage_prompt_tokens = None
 
        request_start_ns = time.time_ns()
 
        try:
            resp = requests.post(
                url,
                json=stream_payload,
                headers=headers,
                timeout=120,
                stream=True,
            )
            resp.raise_for_status()
 
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                # SSE lines are: b"data: {...}" or b"data: [DONE]"
                line = raw_line.decode("utf-8", errors="replace")
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
 
                try:
                    chunk = _json.loads(data_str)
                except _json.JSONDecodeError:
                    continue
 
                # Capture usage from final chunk if provider sends it
                if chunk.get("usage"):
                    usage_completion_tokens = chunk["usage"].get("completion_tokens")
                    usage_prompt_tokens = chunk["usage"].get("prompt_tokens")
                    usage_total_tokens = chunk["usage"].get("total_tokens")
 
                delta = ""
                choices = chunk.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {}).get("content") or ""
 
                if delta:
                    if first_token_ns is None:
                        first_token_ns = time.time_ns()
                    chunk_count += 1
                    assembled_content.append(delta)
                    last_token_ns = time.time_ns()
 
        except Exception as e:
            # Streaming failed — fall back to non-streaming, no TTFT data
            logger.warning(
                "Streaming failed for %s, falling back to non-streaming: %s",
                self.get_name(), e,
            )
            # Capture timing for non-streaming fallback — api_latency_ms
            # must be non-zero for llm_wait_energy_uj to be computed correctly
            _fallback_start_ns = time.time_ns()
            response = requests.post(
                self._endpoint_url(), json=payload, headers=headers, timeout=120
            )
            response.raise_for_status()
            _fallback_end_ns = time.time_ns()
            _fallback_ms = (_fallback_end_ns - _fallback_start_ns) / 1e6
            self._last_stream_metrics = {
                "streaming_enabled": 0,
                "ttft_ms": _fallback_ms,  # no TTFT distinction — full round-trip
                "tpot_ms": 0.0,
                "token_throughput": 0.0,
                "first_token_time_ns": _fallback_start_ns,  # request start as proxy
                "last_token_time_ns": _fallback_end_ns,
                "request_start_ns": request_start_ns,
            }
            return response.json()
 
        # Prefer API token count — providers batch tokens per chunk (Groq)
        provider_usage = (
            usage_prompt_tokens is not None and
            usage_completion_tokens is not None
        )
        token_count = (usage_completion_tokens
                       if provider_usage else chunk_count)
        prompt_token_count = usage_prompt_tokens if provider_usage else 0
        total_token_count = (
            usage_total_tokens if provider_usage and usage_total_tokens is not None
            else prompt_token_count + token_count
        )
 
        total_ms = (
            (last_token_ns - request_start_ns) / 1e6 if last_token_ns else 0.0
        )
        ttft_ms = (
            (first_token_ns - request_start_ns) / 1e6
            if first_token_ns else total_ms
        )
        decode_ms = total_ms - ttft_ms
 
        tpot_ms = (
            decode_ms / max(token_count - 1, 1) if token_count > 1 else 0.0
        )
        throughput = (
            token_count / (decode_ms / 1000)
            if token_count > 1 and decode_ms > 0 else 0.0
        )
 
        # Store for call() to read — avoids changing return type
        self._last_stream_metrics = {
            "ttft_ms": ttft_ms,
            "tpot_ms": tpot_ms,
            "token_throughput": throughput,
            "streaming_enabled": 1,
            "first_token_time_ns": first_token_ns,
            "last_token_time_ns": last_token_ns,
            "request_start_ns": request_start_ns,
        }
 
        # Reconstruct a minimal OpenAI-compat response dict so _parse_response
        # sees the same shape it always has — no changes needed there
        full_content = "".join(assembled_content)
        return {
            "choices": [
                {"message": {"content": full_content}, "finish_reason": "stop"}
            ],
            "usage": {
                "prompt_tokens": prompt_token_count,
                "completion_tokens": token_count,
                "total_tokens": total_token_count,
            },
            "_streamed": True,            # internal flag, ignored by _parse_response
            "_token_provenance": "provider" if provider_usage else "estimated",
        }
 

    def _parse_response(self, data: Dict, prompt: str) -> Tuple[str, Dict]:
        """
        Extract content + token counts from provider response.

        Ollama chat: data['message']['content'], no token counts in body.
        OpenAI-compat: data['choices'][0]['message']['content'] + usage.

        Falls back to word-count tokens if provider omits usage field.

        Args:
            data:   parsed JSON response
            prompt: original prompt (used for word-count fallback)

        Returns:
            Tuple[str, dict]: (content, {prompt, completion, total})
        """
        if self._is_ollama:
            # Ollama returns message.content directly
            content = data.get("message", {}).get("content", "")
            # Ollama does not reliably return token counts in non-stream mode
            tokens = {
                "prompt": len(prompt.split()),
                "completion": len(content.split()),
                "total": len(prompt.split()) + len(content.split()),
            }
            self._last_token_provenance = "estimated"
        else:
            # OpenAI-compat: choices[0].message.content
            if "choices" in data:
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage") or {}
                prompt_tokens = usage.get("prompt_tokens")
                completion_tokens = usage.get("completion_tokens")
                if prompt_tokens is not None and completion_tokens is not None:
                    total_tokens = usage.get("total_tokens")
                    tokens = {
                        "prompt": prompt_tokens,
                        "completion": completion_tokens,
                        "total": (total_tokens if total_tokens is not None
                                  else prompt_tokens + completion_tokens),
                    }
                    self._last_token_provenance = data.get(
                        "_token_provenance", "provider")
                else:
                    tokens = {
                        "prompt": len(prompt.split()),
                        "completion": len(content.split()),
                        "total": len(prompt.split()) + len(content.split()),
                    }
                    self._last_token_provenance = "estimated"
            else:
                # Unexpected format — log and return raw
                logger.warning("Unexpected response format from %s", self.get_name())
                content = str(data)
                tokens = {}
                self._last_token_provenance = "unknown"

        return content, tokens

    def _error_result(self, error_msg: str, preprocess_ms: float) -> Dict:
        """
        Build standard error result dict — never raises, always returns.

        Args:
            error_msg:     exception message
            preprocess_ms: time spent before failure

        Returns:
            Standard adapter result dict with empty/zero values
        """
        phase_metrics = self._make_phase_metrics(
            total_time_ms=preprocess_ms,
            preprocess_ms=preprocess_ms,
            non_local_ms=0.0,
            local_compute_ms=0.0,
            postprocess_ms=0.0,
            app_throughput_kbps=0.0,
            cpu_percent_during_wait=0.0,
        )
        return {
            "content": f"Error: {error_msg}",
            "tokens": {"prompt": 0, "completion": 0, "total": 0},
            "token_provenance": "unknown",
            "total_time_ms": preprocess_ms,
            "phase_metrics": phase_metrics,
            "bytes_sent": 0,
            "bytes_recv": 0,
            "tcp_retransmits": 0,
        }
