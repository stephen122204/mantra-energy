"""
================================================================================
ADAPTERS BASE — Abstract base classes for all model adapters
================================================================================

Purpose:
    Defines the contract every adapter must fulfill.
    Two ABC families:
      TextGenABC — text-generation (LLM inference, all providers)
      MediaABC   — TTS / STT / voice-cloning (non-text input/output)

    BaseAdapterMixin provides shared helpers used by both families:
    phase timing dict construction, network counters, throughput math.

PAC rule: every adapter inherits one ABC — never instantiated directly.
MPC rule: adapters do NOT write DB — they return dicts, executor writes.

Author: A-LEMS Chunk 7
================================================================================
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import psutil

logger = logging.getLogger(__name__)


# =============================================================================
# SHARED MIXIN
# Provides helpers that both ABC families need — mixed in, not inherited alone.
# =============================================================================

class BaseAdapterMixin:
    """
    Utility methods shared across all adapter families.

    Provides: network counter reads, throughput calc, standard
    phase_metrics dict builder.  Never instantiated directly.
    """

    # -------------------------------------------------------------------------
    # Network helpers — used by OpenAICompatAdapter for cloud providers only
    # -------------------------------------------------------------------------

    def _get_network_counters(self) -> Dict[str, int]:
        """
        Read OS-level network I/O counters snapshot.

        Used as before/after pair to compute per-call network delta.
        Returns zeros on failure — never raises (PAC graceful degradation).

        Returns:
            Dict: bytes_sent, bytes_recv, tcp_retransmits
        """
        result = {"bytes_sent": 0, "bytes_recv": 0, "tcp_retransmits": 0}
        try:
            net = psutil.net_io_counters()
            result["bytes_sent"] = net.bytes_sent
            result["bytes_recv"] = net.bytes_recv
            # TCP retransmits from /proc/net/snmp — Linux only, skip on ARM/mac
            with open("/proc/net/snmp", "r") as f:
                for line in f:
                    if line.startswith("Tcp:"):
                        parts = line.split()
                        if "RetransSegs" in parts:
                            result["tcp_retransmits"] = int(
                                parts[parts.index("RetransSegs") + 1]
                            )
                        break
        except Exception as e:
            logger.debug("Network counter read failed: %s", e)
        return result

    def _network_delta(self, before: Dict, after: Dict) -> Dict[str, int]:
        """
        Compute per-call network usage from two counter snapshots.

        Args:
            before: snapshot before API call
            after:  snapshot after API call

        Returns:
            Dict: bytes_sent, bytes_recv, tcp_retransmits (deltas)
        """
        return {
            "bytes_sent": after["bytes_sent"] - before["bytes_sent"],
            "bytes_recv": after["bytes_recv"] - before["bytes_recv"],
            "tcp_retransmits": after["tcp_retransmits"] - before["tcp_retransmits"],
        }

    def _throughput_kbps(self, prompt_bytes: int, response_bytes: int, latency_ms: float) -> float:
        """
        Compute effective application throughput in kbps.

        Formula: (total_bytes * 8) / latency_seconds / 1000
        Uses non_local_ms for cloud (network time only), total_ms for local.

        Args:
            prompt_bytes:   encoded prompt size
            response_bytes: encoded response size
            latency_ms:     time denominator in milliseconds

        Returns:
            float: kbps, 0.0 if latency_ms <= 0
        """
        if latency_ms <= 0:
            return 0.0
        return (prompt_bytes + response_bytes) * 8 / (latency_ms / 1000) / 1000

    def _make_phase_metrics(
        self,
        total_time_ms: float,
        preprocess_ms: float,
        non_local_ms: float,
        local_compute_ms: float,
        postprocess_ms: float,
        app_throughput_kbps: float,
        cpu_percent_during_wait: float,
        ttft_ms: Optional[float] = None,
        tpot_ms: Optional[float] = None,
        token_throughput: Optional[float] = None,
        streaming_enabled: int = 0,
        first_token_time_ns: Optional[int] = None,
        last_token_time_ns: Optional[int] = None,   
    ) -> Dict[str, Any]:
        """
        Build the standard phase_metrics dict consumed by linear.py / agentic.py.

        Shape matches old _current_llm_metrics exactly — harness.py reads this
        at line 165 (linear) and inside _call_llm result (agentic).

        Args:
            total_time_ms:           end-to-end call time
            preprocess_ms:           local JSON serialisation time
            non_local_ms:            network+remote inference (cloud) or 0
            local_compute_ms:        local inference time (ollama/gguf) or 0
            postprocess_ms:          local response parsing time
            app_throughput_kbps:     effective bandwidth
            cpu_percent_during_wait: psutil sample during non_local wait
            ttft_ms:                 time-to-first-token, None if non-streaming
            tpot_ms:                 time-per-output-token, None if non-streaming
            token_throughput:        tokens/sec during decode, None if non-streaming
            streaming_enabled:       1 if streaming was used, 0 otherwise
            first_token_time_ns:     epoch ns of first token, None if non-streaming
            last_token_time_ns:      epoch ns of last token, None if non-streaming            

        Returns:
            Dict matching _current_llm_metrics contract
        """
        return {
            "total_time_ms": total_time_ms,
            "preprocess_ms": preprocess_ms,
            "non_local_ms": non_local_ms,
            "local_compute_ms": local_compute_ms,
            "postprocess_ms": postprocess_ms,
            "app_throughput_kbps": app_throughput_kbps,
            "cpu_percent_during_wait": cpu_percent_during_wait,
            # Chunk 4 streaming metrics — NULL until streaming implemented
            "ttft_ms": ttft_ms,
            "tpot_ms": tpot_ms,
            "token_throughput": token_throughput,
            "streaming_enabled": streaming_enabled,
            "first_token_time_ns": first_token_time_ns,
            "last_token_time_ns": last_token_time_ns,            
        }


# =============================================================================
# TEXT GENERATION ABC
# All LLM adapters (ollama, groq, openai, anthropic, gemini, llama_cpp)
# =============================================================================

class TextGenABC(BaseAdapterMixin, ABC):
    """
    Abstract base for all text-generation adapters.

    Subclasses MUST implement: call(), is_available(), get_name().
    call() return dict shape is the single contract — never change keys.
    """

    def __init__(self, provider_config: Dict, model_config: Dict):
        """
        Initialize with split provider + model config from models.json v2.

        Args:
            provider_config: top-level provider dict (type, base_url, api_key_env, ...)
            model_config:    per-model dict (model_id, max_tokens, temperature, ...)
        """
        self.provider_config = provider_config
        self.model_config = model_config
        # Flatten commonly accessed fields for convenience
        self.model_id = model_config.get("model_id", "unknown")
        self.max_tokens = model_config.get("max_tokens", 1024)
        self.temperature = model_config.get("temperature", 0.7)

    @abstractmethod
    def call(self, prompt: str, temperature: float) -> Dict[str, Any]:
        """
        Execute one LLM inference call (non-streaming).

        Args:
            prompt:      full prompt string
            temperature: sampling temperature for this call

        Returns:
            Dict with keys:
              content        str   — model response text
              tokens         dict  — {prompt, completion, total}
              total_time_ms  float — end-to-end latency
              phase_metrics  dict  — _make_phase_metrics() output
              bytes_sent     int   — network bytes sent (0 for local)
              bytes_recv     int   — network bytes received (0 for local)
              tcp_retransmits int  — TCP retransmits (0 for local)
        """

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if this adapter can be used right now.

        Returns False gracefully — never raises.
        For cloud: checks env var. For local: checks file/server.

        Returns:
            bool
        """

    @abstractmethod
    def get_name(self) -> str:
        """
        Human-readable adapter name for logging.

        Returns:
            str e.g. 'OllamaAdapter(qwen2.5-coder:14b @ localhost)'
        """


# =============================================================================
# MEDIA ABC
# TTS / STT / voice-cloning adapters — input is not always a string prompt
# =============================================================================

class MediaABC(BaseAdapterMixin, ABC):
    """
    Abstract base for media adapters (TTS, STT, voice-cloning).

    Input type varies by task:
      TTS        — prompt: str  → audio bytes
      STT        — prompt: str (file path) → transcript str
      voice-clone — prompt: str + reference_audio → audio bytes

    Subclasses MUST implement: process(), is_available(), get_name().
    """

    def __init__(self, provider_config: Dict, model_config: Dict):
        """
        Args:
            provider_config: provider dict (env_path, type, ...)
            model_config:    model dict (model_id, voice, sample_rate, ...)
        """
        self.provider_config = provider_config
        self.model_config = model_config
        self.model_id = model_config.get("model_id", "unknown")
        self.env_path = provider_config.get("env_path", "")

    @abstractmethod
    def process(self, input_data: Any, **kwargs) -> Dict[str, Any]:
        """
        Execute media processing task.

        Args:
            input_data: str prompt (TTS/voice-clone) or file path (STT)
            **kwargs:   task-specific extras (language, reference_audio, ...)

        Returns:
            Dict with at minimum: {content, duration_sec, total_time_ms}
            TTS/voice-clone also include: {audio_bytes, sample_rate}
        """

    @abstractmethod
    def is_available(self) -> bool:
        """Check env_path exists and deps importable. Never raises."""

    @abstractmethod
    def get_name(self) -> str:
        """Human-readable adapter name."""
