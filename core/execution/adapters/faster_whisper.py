"""
================================================================================
FASTER WHISPER ADAPTER — speech-to-text via faster-whisper
================================================================================

Purpose:
    MediaABC implementation for FasterWhisper speech-to-text.
    Input is audio file path, output is transcript text.
    Lazy-loads WhisperModel on first call.
    Runs inside /opt/ai-stack/envs/whisper-env.

PAC: inherits MediaABC.
Author: A-LEMS Chunk 7
================================================================================
"""

import logging
import os
import time
from typing import Any, Dict

from core.execution.adapters.base import MediaABC

logger = logging.getLogger(__name__)


class FasterWhisperAdapter(MediaABC):
    """
    STT adapter for FasterWhisper.

    process() input: audio file path (str)
    process() output: {content (transcript), language, duration_sec, total_time_ms}
    """

    def __init__(self, provider_config: Dict, model_config: Dict):
        """
        Args:
            provider_config: provider block (env_path)
            model_config:    model block (model_size, compute_type, beam_size)
        """
        super().__init__(provider_config, model_config)
        self._model_size = model_config.get("model_size", "small")
        self._compute_type = model_config.get("compute_type", "int8")
        self._beam_size = model_config.get("beam_size", 5)
        self._whisper = None   # lazy-loaded on first call

    def get_name(self) -> str:
        """Returns: str"""
        return f"FasterWhisperAdapter({self._model_size}, {self._compute_type})"

    def is_available(self) -> bool:
        """
        Check env_path exists and faster_whisper importable.

        Returns:
            bool
        """
        if not os.path.exists(self.env_path):
            return False
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def process(self, input_data: Any, **kwargs) -> Dict[str, Any]:
        """
        Transcribe audio file to text.

        Args:
            input_data: path to audio file (str)
            **kwargs:
                language (str): force language code, default 'auto' (detect)

        Returns:
            Dict: content (full transcript), language, duration_sec, total_time_ms
        """
        audio_path = str(input_data)
        language = kwargs.get("language", None)  # None = auto-detect

        # Validate file exists before loading model
        if not os.path.exists(audio_path):
            msg = f"Audio file not found: {audio_path}"
            logger.error(msg)
            return {"error": msg, "total_time_ms": 0.0}

        t_start = time.time()
        try:
            self._ensure_loaded()
            segments, info = self._whisper.transcribe(
                audio_path,
                beam_size=self._beam_size,
                language=language,  # None triggers auto-detection
            )
            # Segments is a generator — consume fully for complete transcript
            full_text = " ".join(seg.text.strip() for seg in segments)
        except Exception as e:
            logger.error("FasterWhisper transcription failed: %s", e)
            return {"error": str(e), "total_time_ms": (time.time() - t_start) * 1000}

        total_ms = (time.time() - t_start) * 1000

        return {
            "content": full_text,
            "language": info.language,
            "duration_sec": info.duration,
            "total_time_ms": total_ms,
        }

    # -------------------------------------------------------------------------

    def _ensure_loaded(self):
        """
        Lazy-load WhisperModel on first call.

        Kept separate to keep process() under 50 lines.
        Raises on failure — caller catches.
        """
        if self._whisper is not None:
            return  # already loaded — early return
        from faster_whisper import WhisperModel
        logger.info("Loading FasterWhisper model: %s (%s)", self._model_size, self._compute_type)
        self._whisper = WhisperModel(
            self._model_size,
            compute_type=self._compute_type,
        )
