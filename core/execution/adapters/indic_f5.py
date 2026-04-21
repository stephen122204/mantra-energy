"""
================================================================================
INDIC F5 ADAPTER — IndicF5 voice cloning
================================================================================

Purpose:
    MediaABC implementation for IndicF5 voice cloning.
    Requires a reference audio file to clone voice characteristics.
    Runs inside /opt/ai-stack/envs/indicf5-env.

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


class IndicF5Adapter(MediaABC):
    """
    Voice cloning adapter for IndicF5.

    process() input: text string
    process() kwargs: reference_audio (path), language
    process() output: {audio_bytes, sample_rate, duration_sec, total_time_ms}
    """

    def __init__(self, provider_config: Dict, model_config: Dict):
        """
        Args:
            provider_config: provider block (env_path)
            model_config:    model block (model_id)
        """
        super().__init__(provider_config, model_config)
        self._model = None   # lazy-loaded

    def get_name(self) -> str:
        """Returns: str"""
        return f"IndicF5Adapter({self.model_id})"

    def is_available(self) -> bool:
        """
        Check env_path exists.

        Returns:
            bool
        """
        return os.path.exists(self.env_path)

    def process(self, input_data: Any, **kwargs) -> Dict[str, Any]:
        """
        Clone voice and synthesise speech.

        Args:
            input_data: text string to synthesise
            **kwargs:
                reference_audio (str): path to reference WAV file (required)
                language (str):        ISO 639-1 code, default 'hi'

        Returns:
            Dict: audio_bytes, sample_rate, duration_sec, total_time_ms
        """
        text = str(input_data)
        reference_audio = kwargs.get("reference_audio", "")
        language = kwargs.get("language", "hi")

        # Reference audio is mandatory for voice cloning
        if not reference_audio or not os.path.exists(reference_audio):
            msg = f"reference_audio missing or not found: {reference_audio}"
            logger.error(msg)
            return {"error": msg, "total_time_ms": 0.0}

        t_start = time.time()
        try:
            audio_bytes, sample_rate = self._clone(text, reference_audio, language)
        except Exception as e:
            logger.error("IndicF5 cloning failed: %s", e)
            return {"error": str(e), "total_time_ms": (time.time() - t_start) * 1000}

        total_ms = (time.time() - t_start) * 1000
        num_samples = len(audio_bytes) // 2  # 16-bit PCM
        duration_sec = num_samples / sample_rate

        return {
            "content": f"[cloned audio: {duration_sec:.2f}s]",
            "audio_bytes": audio_bytes,
            "sample_rate": sample_rate,
            "duration_sec": duration_sec,
            "total_time_ms": total_ms,
        }

    # -------------------------------------------------------------------------

    def _clone(self, text: str, reference_audio: str, language: str):
        """
        Run IndicF5 voice clone pipeline. Lazy-loads model.

        Args:
            text:            target text
            reference_audio: path to reference WAV
            language:        ISO 639-1 language code

        Returns:
            Tuple[bytes, int]: (audio_bytes, sample_rate)

        Raises:
            Exception on failure
        """
        if self._model is None:
            # indicf5 must be installed in indicf5-env
            from indicf5 import IndicF5
            logger.info("Loading IndicF5 model (first call)")
            self._model = IndicF5()

        audio_array, sample_rate = self._model.clone(
            text=text,
            reference_audio=reference_audio,
            language=language,
        )

        import numpy as np
        audio_int16 = (audio_array * 32767).astype(np.int16)
        return audio_int16.tobytes(), sample_rate
