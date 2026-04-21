"""
Adapters package — model provider implementations.

Import via ModelFactory, not directly.
PAC rule: factory resolves adapters — no direct imports in linear/agentic.
"""

from core.execution.adapters.base import TextGenABC, MediaABC, BaseAdapterMixin
from core.execution.adapters.openai_compat import OpenAICompatAdapter
from core.execution.adapters.llama_cpp import LlamaCppAdapter
from core.execution.adapters.anthropic import AnthropicAdapter
from core.execution.adapters.gemini import GeminiAdapter
from core.execution.adapters.kokoro import KokoroAdapter
from core.execution.adapters.indic_parler import IndicParlerAdapter
from core.execution.adapters.indic_f5 import IndicF5Adapter
from core.execution.adapters.faster_whisper import FasterWhisperAdapter

__all__ = [
    "TextGenABC", "MediaABC", "BaseAdapterMixin",
    "OpenAICompatAdapter", "LlamaCppAdapter",
    "AnthropicAdapter", "GeminiAdapter",
    "KokoroAdapter", "IndicParlerAdapter", "IndicF5Adapter", "FasterWhisperAdapter",
]
