"""
core/readers/fallback/dummy_turbostat_reader.py

Fallback TurbostatReader for platforms where turbostat is unavailable.
Used on macOS, Windows, ARM without MSR access, or any unknown platform.

Returns empty DataFrame and zero metrics — never raises.
Satisfies TurbostatReaderABC contract for graceful degradation (PAC-4).
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class DummyTurbostatReader:
    """
    No-op TurbostatReader for non-Linux or non-x86 platforms.
    All methods return safe empty values — never raises exceptions.
    Measurement mode: LIMITED — no C-state or temperature data.
    """

    def is_available(self):
        # type: () -> bool
        """Always False — turbostat not available on this platform."""
        return False

    def get_name(self):
        # type: () -> str
        """Identify this reader for logging."""
        return "DummyTurbostatReader(LIMITED)"

    def start_monitoring(self, interval_ms=100):
        # type: (int) -> None
        """No-op — no turbostat process to start."""
        logger.debug(
            "DummyTurbostatReader: start_monitoring called — no-op (LIMITED mode)"
        )

    def stop_monitoring(self):
        # type: () -> Dict
        """
        Return empty result dict matching TurbostatReader contract.
        Callers must handle dataframe=None gracefully.
        """
        logger.debug(
            "DummyTurbostatReader: stop_monitoring called — returning empty (LIMITED mode)"
        )
        return {
            "dataframe":        None,   # callers check for None before processing
            "num_samples":      0,
            "duration_seconds": 0.0,
            "summary":          {},
        }

    def get_column_mapping(self):
        # type: () -> Dict
        """Return empty mapping — no columns available in LIMITED mode."""
        return {}
