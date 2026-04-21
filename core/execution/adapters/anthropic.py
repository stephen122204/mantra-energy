"""
================================================================================
ANTHROPIC ADAPTER — Claude API (non-OpenAI-compat SDK)
================================================================================

Purpose:
    Wraps the official anthropic SDK (messages.create).
    Not OpenAI-compat — uses client.messages.create, not /v1/chat/completions.
    Lazy-imports anthropic so missing package returns is_available=False.

PAC: inherits TextGenABC.
Author: A-LEMS Chunk 7
================================================================================
"""

import logging
import os
import time
from typing import Any, Dict, Tuple

from core.execution.adapters.base import TextGenABC

logger = logging.getLogger(__name__)


class AnthropicAdapter(TextGenABC):
    """
    Adapter for Anthropic Claude models via official SDK.

    Cloud provider — non_local_ms captures full round-trip.
    Network OS counters captured for bytes_sent/recv tracking.
    """

    def __init__(self, provider_config: Dict, model_config: Dict):
        """
        Args:
            provider_config: provider block (api_key_env, base_url)
            model_config:    model block (model_id, max_tokens, temperature)
        """
        super().__init__(provider_config, model_config)
        self._api_key_env = provider_config.get("api_key_env", "ANTHROPIC_API_KEY")
        # Resolve at call time — env may not be set at init
        self._api_key = os.getenv(self._api_key_env)

    def get_name(self) -> str:
        """Returns: str"""
        return f"AnthropicAdapter({self.model_id})"

    def is_available(self) -> bool:
        """
        Check API key set and anthropic package installed.

        Returns:
            bool
        """
        if not os.getenv(self._api_key_env):
            return False
        try:
            import anthropic  # noqa: F401
            return True
        except ImportError:
            return False

    def call(self, prompt: str, temperature: float) -> Dict[str, Any]:
        """
        Execute inference via anthropic.messages.create.

        Args:
            prompt:      user prompt
            temperature: sampling temperature

        Returns:
            Standard adapter result dict
        """
        # ── Phase 1: PRE ──────────────────────────────────────────────────────
        t_pre = time.time()
        prompt_bytes = len(prompt.encode("utf-8"))
        preprocess_ms = (time.time() - t_pre) * 1000

        # Network snapshot before cloud call
        net_before = self._get_network_counters()

        # ── Phase 2: CLOUD WAIT ───────────────────────────────────────────────
        t_call = time.time()
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=os.getenv(self._api_key_env))
            response = client.messages.create(
                model=self.model_id,
                max_tokens=self.max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            logger.error("Anthropic call failed: %s", e)
            return self._error_result(str(e), preprocess_ms)

        non_local_ms = (time.time() - t_call) * 1000
        import psutil
        cpu_wait = psutil.cpu_percent(interval=0.05)

        # ── Phase 3: POST ─────────────────────────────────────────────────────
        t_post = time.time()
        content = response.content[0].text
        response_bytes = len(content.encode("utf-8"))
        tokens = {
            "prompt": response.usage.input_tokens,
            "completion": response.usage.output_tokens,
            "total": response.usage.input_tokens + response.usage.output_tokens,
        }
        postprocess_ms = (time.time() - t_post) * 1000

        total_ms = preprocess_ms + non_local_ms + postprocess_ms
        kbps = self._throughput_kbps(prompt_bytes, response_bytes, non_local_ms)
        net_delta = self._network_delta(net_before, self._get_network_counters())

        phase_metrics = self._make_phase_metrics(
            total_time_ms=total_ms,
            preprocess_ms=preprocess_ms,
            non_local_ms=non_local_ms,
            local_compute_ms=0.0,
            postprocess_ms=postprocess_ms,
            app_throughput_kbps=kbps,
            cpu_percent_during_wait=cpu_wait,
            ttft_ms=None,
            tpot_ms=None,
        )

        return {
            "content": content,
            "tokens": tokens,
            "total_time_ms": total_ms,
            "phase_metrics": phase_metrics,
            **net_delta,
        }

    def _error_result(self, error_msg: str, preprocess_ms: float) -> Dict:
        """Standard error result. Args: error_msg, preprocess_ms. Returns: dict."""
        phase_metrics = self._make_phase_metrics(
            total_time_ms=preprocess_ms, preprocess_ms=preprocess_ms,
            non_local_ms=0.0, local_compute_ms=0.0, postprocess_ms=0.0,
            app_throughput_kbps=0.0, cpu_percent_during_wait=0.0,
        )
        return {
            "content": f"Error: {error_msg}",
            "tokens": {"prompt": 0, "completion": 0, "total": 0},
            "total_time_ms": preprocess_ms,
            "phase_metrics": phase_metrics,
            "bytes_sent": 0, "bytes_recv": 0, "tcp_retransmits": 0,
        }
