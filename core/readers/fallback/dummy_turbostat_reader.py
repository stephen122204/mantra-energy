"""
core/readers/fallback/dummy_turbostat_reader.py

Fallback TurbostatReader for platforms where turbostat is unavailable.
Used on macOS, Windows, ARM (GN100), or any unknown platform.
Returns empty DataFrame and zero metrics — never raises.

Satisfies FULL TurbostatReaderABC contract including all attributes
accessed by energy_engine.py. No hasattr checks needed anywhere.
PAC-2 compliant: graceful degradation, never crashes caller.
PAC-4 compliant: complete stub — every attribute present, safe default value.
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class DummyTurbostatReader:
    """
    No-op TurbostatReader for non-Linux or non-x86 platforms.
    All methods return safe empty values — never raises exceptions.
    Measurement mode: LIMITED — no C-state or frequency data available.

    Class-level attributes satisfy full TurbostatReader interface contract.
    energy_engine.py reads these directly — must be present on all instances.
    """

    # --- Interface contract attributes (PAC-4) ---
    available         = False   # platform gate in energy_engine uses this
    turbostat_version = None    # metadata block: stored as NULL in runs table
    cpu_topology      = {}      # metadata block: empty topology on non-x86
    available_sensors = []      # sensor compat guard
    perf_available    = False   # perf compat guard

    def is_available(self) -> bool:
        """Always False — turbostat not available on this platform."""
        return False

    def get_name(self) -> str:
        """Identify this reader for logging."""
        return "DummyTurbostatReader(LIMITED)"

    def start_monitoring(self, interval_ms: int = 100) -> None:
        """No-op — no turbostat process to start on this platform."""
        logger.debug(
            "DummyTurbostatReader: start_monitoring called — no-op (LIMITED mode)"
        )

    def stop_monitoring(self) -> Dict:
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
            "summary":          {"cpu_active_ratio": None},
        }

    def get_latest_sample(self) -> Dict:
        """Return empty sample — no turbostat data available."""
        return {}

    def get_column_mapping(self) -> Dict:
        """Return empty mapping — no columns available in LIMITED mode."""
        return {}

    def read_temperatures(self) -> Dict:
        """Return empty temperature dict — no sensor access in LIMITED mode."""
        return {}

    def read_all_thermal(self) -> Dict:
        """Return empty thermal dict — no thermal access in LIMITED mode."""
        return {}
