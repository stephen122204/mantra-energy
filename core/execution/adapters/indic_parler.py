"""
================================================================================
INDIC PARLER ADAPTER — TTS for 13 Indian languages
================================================================================

Purpose:
    MediaABC implementation for Indic Parler TTS.
    Supports hi, ta, te, bn, mr, gu, kn, ml, pa, or, as, ur, si.
    Runs inside /opt/ai-stack/envs/indic-tts-env.

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

# Supported ISO 639-1 language codes for validation
SUPPORTED_LANGUAGES = {"hi","ta","te","bn","mr","gu","kn","ml","pa","or","as","ur","si"}


class IndicParlerAdapter(MediaABC):
    """
    TTS adapter for Indic Parler — 13 Indian language support.

    process() input: text string
    process() output: {audio_bytes, sample_rate, duration_sec, language, total_time_ms}
    """

    def __init__(self, provider_config: Dict, model_config: Dict):
        """
        Args:
            provider_config: provider block (env_path)
            model_config:    model block (sample_rate, languages)
        """
        super().__init__(provider_config, model_config)
        self._sample_rate = model_config.get("sample_rate", 24000)
        self._model = None   # lazy-loaded

    def get_name(self) -> str:
        """Returns: str"""
        return f"IndicParlerAdapter({self.model_id})"

    def is_available(self) -> bool:
        """
        Check env_path exists.

        Returns:
            bool
        """
        return os.path.exists(self.env_path)

    def process(self, input_data: Any, **kwargs) -> Dict[str, Any]:
        """
        Synthesise speech in specified Indian language.

        Args:
            input_data: text string to synthesise
            **kwargs:
                language (str): ISO 639-1 code, default 'hi' (Hindi)

        Returns:
            Dict: audio_bytes, sample_rate, duration_sec, language, total_time_ms
        """
        text = str(input_data)
        language = kwargs.get("language", "hi")

        # Validate language code early — better error than silent failure
        if language not in SUPPORTED_LANGUAGES:
            logger.warning("Unsupported language '%s', falling back to 'hi'", language)
            language = "hi"

        t_start = time.time()
        try:
            audio_bytes, sample_rate = self._synthesise(text, language)
        except Exception as e:
            logger.error("IndicParler synthesis failed: %s", e)
            return {"error": str(e), "total_time_ms": (time.time() - t_start) * 1000}

        total_ms = (time.time() - t_start) * 1000
        num_samples = len(audio_bytes) // 2  # 16-bit PCM
        duration_sec = num_samples / sample_rate

        return {
            "content": f"[audio: {duration_sec:.2f}s, lang={language}]",
            "audio_bytes": audio_bytes,
            "sample_rate": sample_rate,
            "duration_sec": duration_sec,
            "language": language,
            "total_time_ms": total_ms,
        }

    # -------------------------------------------------------------------------

    def _synthesise(self, text: str, language: str):
        """
        Run IndicParler pipeline for given language. Lazy-loads model.

        Args:
            text:     input text
            language: ISO 639-1 language code

        Returns:
            Tuple[bytes, int]: (audio_bytes, sample_rate)

        Raises:
            Exception on failure
        """
        if self._model is None:
            # indic_parler must be installed in indic-tts-env
            from indic_parler_tts import IndicParlerTTS
            logger.info("Loading IndicParler model (first call)")
            self._model = IndicParlerTTS()

        audio_array = self._model.synthesize(text, language=language)

        import numpy as np
        audio_int16 = (audio_array * 32767).astype(np.int16)
        return audio_int16.tobytes(), self._sample_rate
