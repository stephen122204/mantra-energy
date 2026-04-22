"""
================================================================================
LLAMA CPP ADAPTER — local GGUF model via llama-cpp-python
================================================================================

Purpose:
    Wraps llama_cpp.Llama for local GGUF file inference.
    Lazy-loads the model on first call — avoids startup cost when not used.
    Previously this logic lived inline in linear.py _call_local() and
    agentic.py _call_llm() provider=='local' branch — now centralised here.

PAC: inherits TextGenABC.
Author: A-LEMS Chunk 7
================================================================================
"""

import logging
import time
from typing import Any, Dict, Optional, Tuple
import os

from core.execution.adapters.base import TextGenABC

logger = logging.getLogger(__name__)


class LlamaCppAdapter(TextGenABC):
    """
    Adapter for llama-cpp-python GGUF local models.

    No network traffic — all three phases (pre/compute/post) are local CPU.
    non_local_ms is always 0. bytes_sent/recv always 0.
    """

    def __init__(self, provider_config: Dict, model_config: Dict):
        """
        Args:
            provider_config: provider block (type=local_gguf)
            model_config:    model block (model_path, max_tokens, temperature)
        """
        super().__init__(provider_config, model_config)
        self._model_path = model_config.get("model_path", "")
        self._llm = None   # lazy-loaded on first call — avoids cold start on import

    def get_name(self) -> str:
        """Returns: str adapter name"""
        return f"LlamaCppAdapter({self.model_id} @ {self._model_path})"

    def is_available(self) -> bool:
        """
        Check GGUF file exists and llama_cpp importable.

        Returns:
            bool — False if file missing or package not installed
        """
        if not os.path.exists(self._model_path):
            logger.debug("GGUF file not found: %s", self._model_path)
            return False
        try:
            import llama_cpp  # noqa: F401
            return True
        except ImportError:
            logger.debug("llama_cpp not installed")
            return False

    def call(self, prompt: str, temperature: float) -> Dict[str, Any]:
        """
        Run local GGUF inference with phase timing.

        Phase 1: pre-processing (prompt byte count — trivial for local)
        Phase 2: local_compute (llama_cpp inference — the expensive part)
        Phase 3: post-processing (parse response dict)

        Args:
            prompt:      full prompt string
            temperature: sampling temperature

        Returns:
            Standard adapter result dict
        """
        # ── Phase 1: PRE ──────────────────────────────────────────────────────
        t_pre = time.time()
        prompt_bytes = len(prompt.encode("utf-8"))
        preprocess_ms = (time.time() - t_pre) * 1000

        # ── Phase 2: LOCAL COMPUTE ────────────────────────────────────────────
        t_compute = time.time()
        first_token_ns = None
        last_token_ns = None
        chunk_count = 0
        assembled = []
        completion_tokens_from_usage = None
        usage_prompt_tokens = None
        request_start_ns = time.time_ns()
        try:
            self._ensure_loaded()
            stream = self._llm(
                prompt,
                max_tokens=self.max_tokens,
                temperature=temperature,
                echo=False,
                stream=True,
            )
            for chunk in stream:
                text = chunk["choices"][0].get("text", "")
                if chunk.get("usage"):
                    completion_tokens_from_usage = chunk["usage"].get("completion_tokens")
                    usage_prompt_tokens = chunk["usage"].get("prompt_tokens")
                if text:
                    if first_token_ns is None:
                        first_token_ns = time.time_ns()
                    chunk_count += 1
                    assembled.append(text)
                    last_token_ns = time.time_ns()
        except Exception as e:
            logger.error("LlamaCpp inference failed: %s", e)
            return self._error_result(str(e), preprocess_ms)
        local_compute_ms = (time.time() - t_compute) * 1000

        # ── Phase 3: POST ─────────────────────────────────────────────────────
        t_post = time.time()
        content = "".join(assembled).strip()
        response_bytes = len(content.encode("utf-8"))
        token_count = completion_tokens_from_usage if completion_tokens_from_usage else chunk_count
        prompt_token_count = (self._llm.n_tokens - token_count) if self._llm.n_tokens > token_count else 0
        tokens = {
            "prompt": prompt_token_count,
            "completion": token_count,
            "total": token_count + prompt_token_count,
        }
        postprocess_ms = (time.time() - t_post) * 1000

        total_ms = preprocess_ms + local_compute_ms + postprocess_ms

        # Throughput over total time — no network bottleneck for local
        kbps = self._throughput_kbps(prompt_bytes, response_bytes, total_ms)

        phase_metrics = self._make_phase_metrics(
            total_time_ms=total_ms,
            preprocess_ms=preprocess_ms,
            non_local_ms=0.0,         # purely local — no network
            local_compute_ms=local_compute_ms,
            postprocess_ms=postprocess_ms,
            app_throughput_kbps=kbps,
            cpu_percent_during_wait=0.0,  # no wait phase — all active compute
            ttft_ms=(first_token_ns - request_start_ns) / 1e6 if first_token_ns else None,
            tpot_ms=((last_token_ns - first_token_ns) / 1e6) / max(token_count - 1, 1) if first_token_ns and last_token_ns and token_count > 1 else None,
            token_throughput=token_count / (((last_token_ns - first_token_ns) / 1e6) / 1000) if first_token_ns and last_token_ns and token_count > 1 else None,
            streaming_enabled=1,
            first_token_time_ns=first_token_ns,
            last_token_time_ns=last_token_ns,
        )

        return {
            "content": content,
            "tokens": tokens,
            "total_time_ms": total_ms,
            "phase_metrics": phase_metrics,
            "bytes_sent": 0,      # no network
            "bytes_recv": 0,
            "tcp_retransmits": 0,
        }

    # -------------------------------------------------------------------------

    def _ensure_loaded(self):
        """
        Lazy-load the GGUF model on first call.

        Kept separate so call() stays under 50 lines.
        Raises on failure — caller catches and returns error result.
        """
        if self._llm is not None:
            return  # already loaded — early return
        from llama_cpp import Llama
        logger.info("Loading GGUF model: %s", self._model_path)
        
        self._llm = Llama(model_path=self._model_path)

    def _error_result(self, error_msg: str, preprocess_ms: float) -> Dict:
        """
        Standard error result — never raises.

        Args:
            error_msg:     exception string
            preprocess_ms: time before failure

        Returns:
            Standard adapter result dict with zeros
        """
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
