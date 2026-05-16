"""
core/readers/fallback/dummy_scheduler_monitor.py

Fallback SchedulerMonitor for platforms where /proc is unavailable.
Used on macOS and any non-Linux platform.

Returns safe empty values for all reads — never raises.
Satisfies SchedulerMonitorABC contract for graceful degradation (PAC-4).

macOS sysctl-based implementation deferred to Chunk 1.3.
"""

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


class DummySchedulerMonitor:
    """
    No-op SchedulerMonitor for non-Linux platforms.
    All methods return safe empty values — never raises.
    Measurement mode: LIMITED — no /proc scheduler data.
    """

    def __init__(self, config=None):
        # type: (Any) -> None
        """Accept same signature as SchedulerMonitor — ignore config."""
        # Expose same state flags as SchedulerMonitor
        self._interrupt_sampling_active = False
        self._interrupt_samples = []
        self._last_interrupt_counts = None
        self._last_sample_time_ns = None
        self._start_epoch_ns = None
        self._start_monotonic_ns = None
        logger.debug("DummySchedulerMonitor: initialized (LIMITED mode — no /proc)")

    def is_available(self):
        # type: () -> bool
        """Always False — /proc not available on this platform."""
        return False

    def get_name(self):
        # type: () -> str
        """Identify this monitor for logging."""
        return "DummySchedulerMonitor(LIMITED)"

    def read_context_switches(self):
        # type: () -> Tuple[int, int]
        """Return (0, 0) — no context switch data."""
        return (0, 0)

    def read_cpu_times(self):
        # type: () -> Tuple[float, float]
        """Return (0.0, 0.0) — no CPU time data."""
        return (0.0, 0.0)

    def read_loadavg(self):
        # type: () -> Dict[str, float]
        """Return empty dict — no load average data."""
        return {}

    def read_all(self):
        # type: () -> Dict[str, Any]
        """Return empty dict — no scheduler metrics available."""
        return {}

    def start_interrupt_sampling(self, pid=0):
        # type: (int) -> None
        """No-op — no interrupt sampling without /proc."""
        logger.debug("DummySchedulerMonitor: start_interrupt_sampling no-op")

    def stop_interrupt_sampling(self):
        # type: () -> List
        """Return empty list — no interrupt samples collected."""
        return []

    def sample_interrupts(self):
        # type: () -> None
        """No-op — no interrupt data without /proc."""
        pass

    def reset_interrupt_samples(self):
        # type: () -> None
        """No-op."""
        pass

    def get_swap_metrics(self):
        # type: () -> Dict[str, float]
        """Return empty dict — no swap data without /proc."""
        return {}

    def __str__(self):
        # type: () -> str
        return "DummySchedulerMonitor(LIMITED)"
