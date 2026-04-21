"""
================================================================================
GEMINI ADAPTER — Google Gemini API via google-generativeai SDK
================================================================================

Purpose:
    Wraps google.generativeai.GenerativeModel.generate_content.
    Lazy-imports SDK so missing package returns is_available=False.

PAC: inherits TextGenABC.
Author: A-LEMS Chunk 7
================================================================================
"""

import logging
import os
import time
from typing import Any, Dict

from core.execution.adapters.base import TextGenABC

logger = logging.getLogger(__name__)


class GeminiAdapter(TextGenABC):
    """
    Adapter for Google Gemini models via generativeai SDK.

    Cloud provider — non_local_ms captures full round-trip.
    """

    def __init__(self, provider_config: Dict, model_config: Dict):
        """
        Args:
            provider_config: provider block (api_key_env)
            model_config:    model block (model_id, max_tokens, temperature)
        """
        super().__init__(provider_config, model_config)
        self._api_key_env = provider_config.get("api_key_env", "GEMINI_API_KEY")

    def get_name(self) -> str:
        """Returns: str"""
        return f"GeminiAdapter({self.model_id})"

    def is_available(self) -> bool:
        """
        Check API key set and google-generativeai installed.

        Returns:
            bool
        """
        if not os.getenv(self._api_key_env):
            return False
        try:
            import google.generativeai  # noqa: F401
            return True
        except ImportError:
            return False

    def call(self, prompt: str, temperature: float) -> Dict[str, Any]:
        """
        Execute Gemini inference.

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

        net_before = self._get_network_counters()

        # ── Phase 2: CLOUD WAIT ───────────────────────────────────────────────
        t_call = time.time()
        try:
            import google.generativeai as genai
            genai.configure(api_key=os.getenv(self._api_key_env))
            model = genai.GenerativeModel(
                self.model_id,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=self.max_tokens,
                    temperature=temperature,
                ),
            )
            response = model.generate_content(prompt)
        except Exception as e:
            logger.error("Gemini call failed: %s", e)
            return self._error_result(str(e), preprocess_ms)

        non_local_ms = (time.time() - t_call) * 1000
        import psutil
        cpu_wait = psutil.cpu_percent(interval=0.05)

        # ── Phase 3: POST ─────────────────────────────────────────────────────
        t_post = time.time()
        content = response.text
        response_bytes = len(content.encode("utf-8"))
        # Gemini returns usage_metadata with token counts
        usage = response.usage_metadata
        tokens = {
            "prompt": getattr(usage, "prompt_token_count", 0),
            "completion": getattr(usage, "candidates_token_count", 0),
            "total": getattr(usage, "total_token_count", 0),
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
