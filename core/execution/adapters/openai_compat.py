"""
================================================================================
OPENAI COMPAT ADAPTER — covers Groq, OpenAI, Ollama Local, Ollama Remote
================================================================================

Purpose:
    One adapter class for all OpenAI-compatible HTTP APIs.
    Ollama NDJSON and OpenAI-compatible SSE are normalized explicitly.

    Providers handled:
      groq          cloud_api    api.groq.com
      openai        cloud_api    api.openai.com
      ollama_local  local_ollama localhost:11434
      ollama_remote local_ollama 129.153.71.47:11434

    Network metrics captured for cloud providers, zeroed for local ollama —
    because local HTTP to 127.0.0.1 / LAN produces meaningless OS counters.

PAC: inherits TextGenABC — factory resolves, never imported directly elsewhere.

Author: A-LEMS Chunk 7
================================================================================
"""

import logging
import time
from typing import Any, Dict, Optional, Tuple

import psutil
import requests

from core.execution.adapters.base import AdapterCallError, TextGenABC

logger = logging.getLogger(__name__)

# Providers where HTTP goes over real network — capture OS network counters
_CLOUD_TYPES = {"cloud_api"}

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

        self._type = provider_config.get("type", "")          # local_ollama vs cloud_api
        self._base_url = provider_config.get("base_url", "").rstrip("/")
        self._api_key_env = provider_config.get("api_key_env", "")
        self._is_ollama = provider_config.get("provider_id", "").startswith("ollama")      # controls endpoint + response parsing
        # derive is_cloud from network_type or is_local — works for all providers
        self._is_cloud = (
            self._type in _CLOUD_TYPES or
            model_config.get("network_type") == "internet" or
            model_config.get("is_local") == False
        )

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

        For cloud: API key env var must be set.
        For ollama: attempt HEAD to /api/tags — timeout 2s.

        Returns:
            bool
        """
        if self._is_cloud:
            # Cloud requires API key in env
            return bool(self._api_key)
        # Local ollama: ping tags endpoint to verify server is running
        try:
            r = requests.get(f"{self._base_url}/api/tags", timeout=2)
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
        self._partial_content = ""
        self._observed_tokens = {}
        # ── Phase 1: PRE-PROCESSING — local JSON build ────────────────────────
        t_pre = time.perf_counter()
        payload = self._build_payload(prompt, temperature)
        prompt_bytes = len(str(payload).encode("utf-8"))
        preprocess_ms = (time.perf_counter() - t_pre) * 1000

        # ── Network snapshot (cloud only) ─────────────────────────────────────
        net_before = self._get_network_counters() if self._is_cloud else None

        # ── Phase 2: WAIT / INFERENCE ─────────────────────────────────────────
        t_call = time.perf_counter()
        try:
            raw = self._http_call(payload)
        except Exception as e:
            logger.error("HTTP call failed [%s]: %s", self.get_name(), e)
            return self._error_result(
                str(e), preprocess_ms, (time.perf_counter() - t_call) * 1000,
                net_before=net_before,
            )

        call_ms = (time.perf_counter() - t_call) * 1000

        # CPU sample during remote wait — meaningful only for cloud
        cpu_wait = psutil.cpu_percent(interval=0.05) if self._is_cloud else 0.0

        # ── Phase 3: POST-PROCESSING — parse response ─────────────────────────
        t_post = time.perf_counter()
        try:
            content, tokens = self._parse_response(raw, prompt)
        except Exception as e:
            return self._error_result(
                str(e), preprocess_ms, call_ms,
                postprocess_ms=(time.perf_counter() - t_post) * 1000,
                net_before=net_before,
            )
        response_bytes = len(content.encode("utf-8"))
        postprocess_ms = (time.perf_counter() - t_post) * 1000

        # ── Assign phase times by execution locality ──────────────────────────
        if self._is_cloud:
            non_local_ms = call_ms
            local_compute_ms = 0.0
            kbps = self._throughput_kbps(prompt_bytes, response_bytes, non_local_ms)
        else:
            non_local_ms = 0.0
            local_compute_ms = call_ms
            kbps = self._throughput_kbps(prompt_bytes, response_bytes,
                                          preprocess_ms + call_ms + postprocess_ms)

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
            "status": "ok",
            "content": content,
            "tokens": tokens,
            "token_provenance": self._last_token_provenance,
            "total_time_ms": total_ms,
            "phase_metrics": phase_metrics,
            **net_delta,  # bytes_sent, bytes_recv, tcp_retransmits
        }

    def require_success(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Reject this adapter's explicit structured failure at persistence boundaries."""
        if result.get("status") == "error":
            raise AdapterCallError(result)
        return result

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
        """Send exactly one request; never hide an ambiguous failure with a retry.

        Set ``stream: false`` in the model or provider configuration for an
        endpoint without streaming support. A JSON response to a streaming
        request is also decoded in place, without submitting inference again.
        Epoch timestamps remain compatible with existing consumers; elapsed
        stream durations use a monotonic clock.
        """
        import json

        stream = self.model_config.get("stream", self.provider_config.get("stream", True))
        if not isinstance(stream, bool):
            raise ValueError("stream configuration must be a boolean")
        request_start_ns = time.time_ns()
        start = time.perf_counter_ns()
        first = last = None
        first_epoch = last_epoch = None
        content = []
        prompt_count = completion_count = None
        terminal = {}
        finish_reason = None
        complete = False
        response = None
        self._last_stream_metrics = {"request_start_ns": request_start_ns}
        try:
            response = requests.post(
                self._endpoint_url(), json={**payload, "stream": stream},
                headers=self._build_headers(), timeout=120, stream=stream,
            )
            response.raise_for_status()
            media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if not stream or media_type == "application/json":
                stream = False
                raw = response.json()
                if not isinstance(raw, dict):
                    raise ValueError("provider response must be a JSON object")
                if self._is_ollama:
                    prompt_count = raw.get("prompt_eval_count")
                    completion_count = raw.get("eval_count")
                else:
                    usage = raw.get("usage")
                    if isinstance(usage, dict):
                        prompt_count = usage.get("prompt_tokens")
                        completion_count = usage.get("completion_tokens")
                if raw.get("error"):
                    raise RuntimeError(str(raw["error"]))
                if self._is_ollama and raw.get("done") is not True:
                    raise RuntimeError("Ollama response ended without done=true")
                return raw

            for raw_line in response.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8")
                if self._is_ollama:
                    data_str = line.strip()
                else:
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        complete = True
                        break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError as e:
                    raise ValueError("malformed provider stream chunk") from e
                if not isinstance(chunk, dict):
                    raise ValueError("provider stream chunk must be a JSON object")
                if chunk.get("error"):
                    raise RuntimeError(str(chunk["error"]))
                if self._is_ollama:
                    terminal = chunk
                    if chunk.get("prompt_eval_count") is not None:
                        prompt_count = chunk["prompt_eval_count"]
                    if chunk.get("eval_count") is not None:
                        completion_count = chunk["eval_count"]
                    delta = chunk.get("message", {}).get("content")
                    if delta is None:
                        delta = ""
                    elif not isinstance(delta, str):
                        raise ValueError("provider content must be text")
                    complete = chunk.get("done") is True
                else:
                    usage = chunk.get("usage") or {}
                    if usage.get("prompt_tokens") is not None:
                        prompt_count = usage["prompt_tokens"]
                    if usage.get("completion_tokens") is not None:
                        completion_count = usage["completion_tokens"]
                    choices = chunk.get("choices") or []
                    delta = ""
                    if choices:
                        delta = choices[0].get("delta", {}).get("content")
                        if delta is None:
                            delta = ""
                        elif not isinstance(delta, str):
                            raise ValueError("provider content must be text")
                        if choices[0].get("finish_reason") is not None:
                            finish_reason = choices[0]["finish_reason"]
                            complete = True
                if delta:
                    now = time.perf_counter_ns()
                    epoch = time.time_ns()
                    if first is None:
                        first, first_epoch = now, epoch
                    last, last_epoch = now, epoch
                    content.append(delta)
                if self._is_ollama and complete:
                    break
            if not complete:
                raise RuntimeError("provider stream ended without a completion marker")

            if self._is_ollama:
                return {
                    **terminal, "message": {"content": "".join(content)},
                    "prompt_eval_count": prompt_count, "eval_count": completion_count,
                }
            # Only actual provider usage is reconstructed. Chunks are not tokens.
            return {
                "choices": [{"message": {"content": "".join(content)},
                             "finish_reason": finish_reason}],
                "usage": {"prompt_tokens": prompt_count, "completion_tokens": completion_count},
            }
        finally:
            self._partial_content = "".join(content)
            self._observed_tokens = {
                key: value for key, value in
                (("prompt", prompt_count), ("completion", completion_count))
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0
            }
            decode_ms = (last - first) / 1e6 if first is not None else None
            valid_count = (isinstance(completion_count, int)
                           and not isinstance(completion_count, bool) and completion_count > 1)
            measured_decode = valid_count and decode_ms is not None and decode_ms > 0
            self._last_stream_metrics = {
                "request_start_ns": request_start_ns,
                "first_token_time_ns": first_epoch,
                "last_token_time_ns": last_epoch,
                "ttft_ms": (first - start) / 1e6 if first is not None else None,
                "tpot_ms": decode_ms / (completion_count - 1) if measured_decode else None,
                "token_throughput": completion_count / (decode_ms / 1000) if measured_decode else None,
                "streaming_enabled": int(stream),
            }
            if response is not None:
                response.close()

    def _parse_response(self, data: Dict, prompt: str) -> Tuple[str, Dict]:
        """Normalize content using the shared provider/estimated provenance values."""
        if data.get("error"):
            raise RuntimeError(str(data["error"]))
        if self._is_ollama:
            content = data["message"]["content"]
            prompt_count = data.get("prompt_eval_count")
            completion_count = data.get("eval_count")
        else:
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            prompt_count = usage.get("prompt_tokens")
            completion_count = usage.get("completion_tokens")
        if not isinstance(content, str):
            raise ValueError("provider content must be text")
        self._partial_content = content
        for value in (prompt_count, completion_count):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                raise ValueError("provider token counts must be nonnegative integers")
        provided = sum(value is not None for value in (prompt_count, completion_count))
        # The shared contract has one provenance for the entire count record.
        # Any estimated field makes that record estimated; retain known counts.
        self._last_token_provenance = "provider" if provided == 2 else "estimated"
        prompt_count = len(prompt.split()) if prompt_count is None else prompt_count
        completion_count = len(content.split()) if completion_count is None else completion_count
        return content, {"prompt": prompt_count, "completion": completion_count,
                         "total": prompt_count + completion_count}

    def _error_result(self, error_msg: str, preprocess_ms: float,
                      call_ms: float = 0.0, postprocess_ms: float = 0.0,
                      net_before: Optional[Dict] = None) -> Dict:
        """Retain failed-request observations without treating partial text as success.

        An empty token dictionary means unknown, not measured zero. Existing
        consumers can still use their missing-key defaults. Partial provider
        counts are observations, not final usage for a completed request.
        """
        total_ms = preprocess_ms + call_ms + postprocess_ms
        phase_metrics = self._make_phase_metrics(
            total_time_ms=total_ms, preprocess_ms=preprocess_ms,
            non_local_ms=call_ms if self._is_cloud else 0.0,
            local_compute_ms=0.0 if self._is_cloud else call_ms,
            postprocess_ms=postprocess_ms, app_throughput_kbps=0.0,
            cpu_percent_during_wait=0.0, **self._last_stream_metrics,
        )
        net_delta = {"bytes_sent": 0, "bytes_recv": 0, "tcp_retransmits": 0}
        if self._is_cloud and net_before:
            net_delta = self._network_delta(net_before, self._get_network_counters())
        return {
            "status": "error", "error": error_msg,
            "content": f"Error: {error_msg}",
            "partial_content": self._partial_content,
            "tokens": {}, "token_provenance": "unknown",
            "observed_tokens": self._observed_tokens,
            "total_time_ms": total_ms, "phase_metrics": phase_metrics, **net_delta,
        }
