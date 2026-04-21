"""
================================================================================
KOKORO ADAPTER — Kokoro TTS English text-to-speech
================================================================================

Purpose:
    MediaABC implementation for Kokoro 82M English TTS model.
    Runs inside /opt/ai-stack/envs/kokoro-env virtual environment.
    Returns audio bytes + duration metadata — no DB writes here.

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


class KokoroAdapter(MediaABC):
    """
    TTS adapter for Kokoro 82M English model.

    process() input: text string
    process() output: {audio_bytes, sample_rate, duration_sec, total_time_ms}
    """

    def __init__(self, provider_config: Dict, model_config: Dict):
        """
        Args:
            provider_config: provider block (env_path)
            model_config:    model block (voice, sample_rate)
        """
        super().__init__(provider_config, model_config)
        self._voice = model_config.get("voice", "af_heart")
        self._sample_rate = model_config.get("sample_rate", 24000)
        self._pipeline = None   # lazy-loaded on first call

    def get_name(self) -> str:
        """Returns: str"""
        return f"KokoroAdapter({self.model_id}, voice={self._voice})"

    def is_available(self) -> bool:
        """
        Check env_path exists.

        Returns:
            bool
        """
        if not os.path.exists(self.env_path):
            logger.debug("Kokoro env not found: %s", self.env_path)
            return False
        return True

    def process(self, input_data: Any, **kwargs) -> Dict[str, Any]:
        """
        Generate speech audio from text.

        Args:
            input_data: text string to synthesise
            **kwargs:   optional voice override

        Returns:
            Dict: audio_bytes, sample_rate, duration_sec, total_time_ms
        """
        text = str(input_data)
        voice = kwargs.get("voice", self._voice)

        t_start = time.time()
        try:
            audio_bytes, sample_rate = self._synthesise(text, voice)
        except Exception as e:
            logger.error("Kokoro synthesis failed: %s", e)
            return {"error": str(e), "total_time_ms": (time.time() - t_start) * 1000}

        total_ms = (time.time() - t_start) * 1000
        # Duration from sample count — standard audio math
        num_samples = len(audio_bytes) // 2  # 16-bit = 2 bytes per sample
        duration_sec = num_samples / sample_rate

        return {
            "content": f"[audio: {duration_sec:.2f}s]",
            "audio_bytes": audio_bytes,
            "sample_rate": sample_rate,
            "duration_sec": duration_sec,
            "total_time_ms": total_ms,
        }

    # -------------------------------------------------------------------------

    def _synthesise(self, text: str, voice: str):
        """
        Run Kokoro pipeline. Lazy-loads on first call.

        Args:
            text:  input text
            voice: voice ID string

        Returns:
            Tuple[bytes, int]: (audio_bytes, sample_rate)

        Raises:
            Exception on model load or synthesis failure
        """
        if self._pipeline is None:
            # Import inside env context — kokoro must be installed in kokoro-env
            from kokoro import KPipeline
            logger.info("Loading Kokoro pipeline (first call)")
            self._pipeline = KPipeline(lang_code="a")  # 'a' = American English

        # Pipeline returns generator of (gs, ps, audio) tuples
        audio_chunks = []
        for _, _, audio in self._pipeline(text, voice=voice):
            audio_chunks.append(audio)

        import numpy as np
        # Concatenate all chunks into single float32 array then convert to bytes
        full_audio = np.concatenate(audio_chunks) if audio_chunks else np.array([])
        audio_int16 = (full_audio * 32767).astype(np.int16)
        return audio_int16.tobytes(), self._sample_rate
