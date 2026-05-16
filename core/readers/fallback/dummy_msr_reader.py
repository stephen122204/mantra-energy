"""
core/readers/fallback/dummy_msr_reader.py

Fallback MSRReader for platforms where MSR access is unavailable.
Used on macOS, Linux ARM, or any platform without msr_read C binary.

Returns None/empty for all reads — never raises.
Satisfies MSRReaderABC contract for graceful degradation (PAC-4).

macOS IOKit MSR implementation deferred to Chunk 1.2.
Linux ARM MSR implementation deferred to Chunk 1.3.
"""

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class DummyMSRReader:
    """
    No-op MSRReader for non-Linux-x86 platforms.
    All methods return safe empty values — never raises.
    Measurement mode: LIMITED — no C-state or MSR data.
    """

    def __init__(self, config=None, **kwargs):
        # type: (Optional[Dict], Any) -> None
        """Accept same signature as MSRReader — ignore all args."""
        # Expose same availability flags as MSRReader — both False
        self.helper_available = False
        self.rdmsr_available = False
        self._cstate_start = None
        self._cstate_end = None
        logger.debug("DummyMSRReader: initialized (LIMITED mode — no MSR access)")

    def is_available(self):
        # type: () -> bool
        """Always False — MSR not available on this platform."""
        return False

    def get_name(self):
        # type: () -> str
        """Identify this reader for logging."""
        return "DummyMSRReader(LIMITED)"

    def read_msr(self, msr_addr, cpu=0, pin=True):
        # type: (int, int, bool) -> Optional[int]
        """Return None — no MSR access on this platform."""
        return None

    def read_msr_all_cpus(self, msr_addr, pin=True):
        # type: (int, bool) -> Dict[int, int]
        """Return empty dict — no MSR access."""
        return {}

    def read_cstate_counters(self, cpu=0, pin=True):
        # type: (int, bool) -> Dict[str, Any]
        """Return empty dict — no C-state data available."""
        return {}

    def read_cstate_counters_all_cpus(self):
        # type: () -> Dict[int, Dict]
        """Return empty dict — no C-state data available."""
        return {}

    def snapshot_cstate_counters(self):
        # type: () -> Optional[Dict]
        """Return None — no snapshot possible without MSR."""
        return None

    def snapshot_thermal_state(self):
        # type: () -> Optional[Dict]
        """Return None — no thermal MSR data."""
        return None

    def read_thermal_throttle_status(self, cpu=0):
        # type: (int) -> Optional[Dict]
        """Return None — no thermal MSR data."""
        return None

    def read_core_thermal_status(self, cpu=0):
        # type: (int) -> Optional[Dict]
        """Return None — no thermal MSR data."""
        return None

    def get_ring_bus_frequency(self):
        # type: () -> Optional[float]
        """Return None — no ring bus MSR access."""
        return None

    def get_wakeup_latency(self):
        # type: () -> Optional[float]
        """Return None — no MSR wakeup data."""
        return None

    def ticks_to_seconds(self, ticks):
        # type: (int) -> float
        """Return 0.0 — no TSC frequency available."""
        return 0.0

    def ticks_to_microseconds(self, ticks):
        # type: (int) -> float
        """Return 0.0 — no TSC frequency available."""
        return 0.0

    def pin_to_cpu(self, cpu):
        # type: (int) -> bool
        """No-op — no CPU pinning without MSR."""
        return False

    def unpin(self):
        # type: () -> None
        """No-op."""
        pass

    def read_cstate_counters_for_wakeup(self, *args, **kwargs):
        # type: (*Any, **Any) -> Dict
        """Return empty dict — no C-state wakeup data."""
        return {}

    def calculate_wakeup_delta(self, *args, **kwargs):
        # type: (*Any, **Any) -> Dict
        """Return empty dict — no wakeup delta without MSR."""
        return {}

    def get_baseline_dict(self):
        # type: () -> Dict
        """Return empty dict — no baseline without MSR."""
        return {}
