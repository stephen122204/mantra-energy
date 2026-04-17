#!/usr/bin/env python3
"""
================================================================================
ENERGY ESTIMATOR — ML-based Energy Estimation for ARM / No-RAPL Platforms
================================================================================

Purpose:
    Stub implementation of EnergyReaderABC for platforms where no direct
    hardware energy counter is available (e.g. Oracle Cloud ARM64 VM).

    In this release the estimator returns zero values with a logged warning.
    Full ML model integration (scikit-learn / ONNX) is planned for Chunk 7
    when the model_factory is built.

Mode:        INFERRED
Platform:    Linux aarch64 (ARM VM), Linux x86_64 without RAPL permissions
Returns:     Zero µJ values with WARNING log on every call (until model loaded)

Integration with full ML model (future):
    - Feature vector: cpu_util%, freq_mhz, instructions, task_type
    - Model file:     models/energy_estimator.onnx
    - Output:         Predicted package_energy_uj

Author: Deepak Panigrahy
================================================================================
"""

import logging
from typing import Dict, List

from core.readers.interfaces import EnergyReaderABC

logger = logging.getLogger(__name__)


class EnergyEstimator(EnergyReaderABC):
    """
    Stub energy reader for platforms without hardware energy counters.

    Implements EnergyReaderABC so the rest of the system (EnergyEngine,
    ReaderFactory) can call it identically to RAPLReader.

    Current behaviour:
        Returns zeros for all domains and logs a warning.

    Future behaviour (Chunk 7):
        Load ONNX/sklearn model and predict energy from CPU performance
        counters (utilisation, frequency, instruction count, task type).

    Attributes:
        _warned (bool): Throttle flag — only log the stub warning once
                        per process to avoid flooding logs during sampling.
    """

    # Synthetic domain names — mirrors what RAPLReader would return
    # so downstream consumers don't need special-casing for ARM
    STUB_DOMAINS = ["package-0", "core"]

    def __init__(self, config: dict = None):
        """
        Initialise the energy estimator.

        Args:
            config: hw_config dict (accepted for API consistency with
                    RAPLReader but not currently used by the stub).
        """
        # config accepted for signature compatibility; not used in stub
        self._config  = config or {}
        self._warned  = False           # throttle: warn once, not every sample
        self._model   = None            # placeholder for future ONNX model

        logger.warning(
            "EnergyEstimator initialised (INFERRED mode). "
            "No hardware energy counter available on this platform. "
            "All energy values will be ZERO until ML model is loaded (Chunk 7)."
        )

    # ------------------------------------------------------------------
    # EnergyReaderABC implementation
    # ------------------------------------------------------------------

    def read_energy_uj(self) -> Dict[str, int]:
        """
        Return estimated energy in microjoules for each domain.

        Current stub behaviour:
            Returns zeros. Logs a warning on first call only.

        Future behaviour:
            Run CPU performance metrics through the loaded ONNX model
            and return predicted µJ values per domain.

        Returns:
            Dict[str, int]: Domain → 0 µJ (stub) or predicted µJ (future).
        """
        # Warn once per process — don't flood sampling logs
        if not self._warned:
            logger.warning(
                "EnergyEstimator.read_energy_uj() returning zeros — "
                "ML model not yet loaded. Data marked as INFERRED."
            )
            self._warned = True     # suppress subsequent warnings this session

        # Return zero for every synthetic domain
        return {domain: 0 for domain in self.STUB_DOMAINS}

    def get_domains(self) -> List[str]:
        """
        Return the list of domains this estimator provides.

        Returns:
            List[str]: Synthetic domain names matching RAPLReader convention.
        """
        return list(self.STUB_DOMAINS)  # copy to prevent external mutation

    def is_available(self) -> bool:
        """
        Return False — this is a stub; no real hardware data is available.

        Callers can use this to mark measurements as estimated in the DB.

        Returns:
            bool: Always False for the stub implementation.
        """
        return False    # stub — signals INFERRED data quality to consumers

    def get_name(self) -> str:
        """
        Return the reader name for logging and platform summaries.

        Returns:
            str: 'EnergyEstimator'
        """
        return "EnergyEstimator"
