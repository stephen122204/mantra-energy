"""
Fallback Disk Reader — unknown/unsupported platforms.

Used by factory when neither Linux /proc/diskstats nor macOS IOKit
is available. Returns None for all samples — never raises.

Platforms: ARM VM without /proc, Windows, unknown OS.
"""

from typing import Optional, Dict
from core.readers.interfaces import DiskReaderABC


class FallbackDiskReader(DiskReaderABC):
    """No-op disk reader for unsupported platforms."""

    def __init__(self, config: dict = None, device: str = "", pid: int = 0):
        self.device = device
        self.pid    = pid
        self._last  = None

    def is_available(self) -> bool:
        """Never available — this is the last-resort fallback."""
        return False

    def sample(self) -> Optional[Dict]:
        """Returns None — no disk I/O data available on this platform."""
        return None

    def _detect_device(self) -> str:
        """No device to detect."""
        return ""
