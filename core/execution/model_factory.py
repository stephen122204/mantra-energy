"""
================================================================================
MODEL FACTORY — central adapter dispatch table
================================================================================

Purpose:
    Single point of truth for provider -> adapter resolution.
    Reads from models_loader (models.yaml) — no direct JSON parsing here.

    Provider type -> adapter class mapping:
      local_ollama / openai_compat cloud -> OpenAICompatAdapter
      direct_file                        -> LlamaCppAdapter
      anthropic                          -> AnthropicAdapter
      gemini                             -> GeminiAdapter
      local_process/TTS                  -> KokoroAdapter / IndicParlerAdapter / IndicF5Adapter
      local_process/STT                  -> FasterWhisperAdapter

PAC rule: factory is the ONLY place that imports adapter classes.
          linear.py / agentic.py only import ModelFactory.

Author: A-LEMS Chunk 7
================================================================================
"""

import logging
from typing import Any, Dict, Optional, Union

from core.execution.adapters.base import TextGenABC, MediaABC
from core.execution.adapters.openai_compat import OpenAICompatAdapter
from core.execution.adapters.llama_cpp import LlamaCppAdapter
from core.execution.adapters.anthropic import AnthropicAdapter
from core.execution.adapters.gemini import GeminiAdapter
from core.execution.adapters.kokoro import KokoroAdapter
from core.execution.adapters.indic_parler import IndicParlerAdapter
from core.execution.adapters.indic_f5 import IndicF5Adapter
from core.execution.adapters.faster_whisper import FasterWhisperAdapter
import core.models_loader as _loader

logger = logging.getLogger(__name__)

# Cloud providers that do NOT speak OpenAI-compat format
_NON_COMPAT_CLOUD = {
    "anthropic": AnthropicAdapter,
    "gemini":    GeminiAdapter,
}

# Media adapter dispatch: provider_id -> adapter class
_MEDIA_ADAPTERS = {
    "kokoro":          KokoroAdapter,
    "indic_parler":    IndicParlerAdapter,
    "indic_f5":        IndicF5Adapter,
    "faster_whisper":  FasterWhisperAdapter,
}


class ModelFactory:
    """
    Central factory — resolves provider name to adapter instance.

    Usage:
        adapter = ModelFactory.get_adapter(provider, flat_config)
        result  = adapter.call(prompt, temperature)
    """

    @classmethod
    def get_adapter(
        cls,
        provider: str,
        flat_config: Dict[str, Any],
    ) -> Union[TextGenABC, MediaABC]:
        """
        Resolve provider string to initialised adapter instance.

        Args:
            provider:    provider key (e.g. 'ollama_remote', 'groq', 'llama_cpp')
                         Also accepts legacy 'ollama' and 'local' strings.
            flat_config: merged flat config dict (has model_id, max_tokens, etc.)

        Returns:
            Initialised adapter ready for .call() or .process()

        Raises:
            ValueError if provider unknown
        """
        # Remap legacy provider strings from old harness calls
        provider = cls._remap_legacy(provider, flat_config)

        # Load provider block from models_loader
        data = _loader._load()
        provider_block = data["providers"].get(provider)
        if not provider_block:
            raise ValueError(
                f"ModelFactory: unknown provider '{provider}'. "
                f"Available: {list(data['providers'].keys())}"
            )

        meta = provider_block["provider_meta"]
        access_method = meta.get("access_method", "api_http")
        provider_id   = meta.get("provider_id", provider)

        # Dispatch by access_method + provider_id
        if access_method == "direct_file":
            return LlamaCppAdapter(meta, flat_config)

        if access_method == "local_process":
            return cls._resolve_media(provider_id, meta, flat_config)

        if access_method == "api_http":
            return cls._resolve_http(provider_id, meta, flat_config)

        raise ValueError(
            f"ModelFactory: unhandled access_method '{access_method}' for '{provider}'"
        )

    @classmethod
    def list_providers(cls, task: Optional[str] = None) -> Dict:
        """
        List all configured providers, optionally filtered by task.

        Args:
            task: e.g. 'text-generation', None = all

        Returns:
            Dict provider_id -> provider block
        """
        return _loader.list_providers(task=task)

    @classmethod
    def list_models(cls, provider: str) -> list:
        """
        List all models for a provider.

        Args:
            provider: provider key string

        Returns:
            List of model dicts
        """
        return _loader.list_models(provider)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    @classmethod
    def _remap_legacy(cls, provider: str, flat_config: Dict) -> str:
        """
        Map old provider strings to new v2 names.

        'local'  -> 'llama_cpp'
        'ollama' -> 'ollama_local' or 'ollama_remote' (from api_endpoint)

        Args:
            provider:    original string
            flat_config: config dict for endpoint detection

        Returns:
            str v2 provider key
        """
        if provider == "local":
            return "llama_cpp"
        if provider == "ollama":
            endpoint = flat_config.get("api_endpoint", "")
            if "129.153.71.47" in endpoint:
                return "ollama_remote"
            return "ollama_local"
        return provider

    @classmethod
    def _resolve_http(
        cls, provider_id: str, meta: Dict, flat_config: Dict
    ) -> TextGenABC:
        """
        Dispatch api_http providers to correct adapter.

        openai_compat=True  -> OpenAICompatAdapter
        anthropic/gemini    -> SDK-specific adapter

        Args:
            provider_id: provider key
            meta:        provider_meta dict
            flat_config: flat model config

        Returns:
            TextGenABC instance
        """
        if meta.get("openai_compat", False) or "ollama" in provider_id:
            # groq, openai, ollama_local, ollama_remote — all speak same format
            return OpenAICompatAdapter(meta, flat_config)

        adapter_cls = _NON_COMPAT_CLOUD.get(provider_id)
        if adapter_cls:
            return adapter_cls(meta, flat_config)

        raise ValueError(
            f"ModelFactory: no HTTP adapter for '{provider_id}'. "
            f"Set openai_compat=true or add to _NON_COMPAT_CLOUD."
        )

    @classmethod
    def _resolve_media(
        cls, provider_id: str, meta: Dict, flat_config: Dict
    ) -> MediaABC:
        """
        Dispatch local_process providers to media adapter.

        Args:
            provider_id: provider key
            meta:        provider_meta dict
            flat_config: flat model config

        Returns:
            MediaABC instance
        """
        adapter_cls = _MEDIA_ADAPTERS.get(provider_id)
        if adapter_cls:
            return adapter_cls(meta, flat_config)

        raise ValueError(
            f"ModelFactory: no media adapter for provider '{provider_id}'"
        )
