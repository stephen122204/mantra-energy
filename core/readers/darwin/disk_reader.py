"""
macOS Disk I/O Reader — IOKit stub.

Returns None for all samples until IOKit implementation is added (Chunk 14).
Inherits DiskReaderABC so factory can route correctly on macOS.

Future implementation:
    Use IOKit IOBlockStorageDriver statistics:
    kIOBlockStorageDriverStatisticsReadsKey  → read bytes
    kIOBlockStorageDriverStatisticsWritesKey → write bytes
"""

import os
from typing import Optional, Dict
from core.readers.interfaces import DiskReaderABC


class IOKitDiskReader(DiskReaderABC):
    """macOS disk reader — stub until IOKit implementation (Chunk 14)."""

    def __init__(self, config: dict = None, device: str = "", pid: int = 0):
        self.device = device
        self.pid    = pid
        self._last  = None

    def is_available(self) -> bool:
        """Only available on macOS — returns False on other platforms."""
        return os.uname().sysname == "Darwin"

    def sample(self) -> Optional[Dict]:
        """Not yet implemented — returns None gracefully."""
        return None

    def _detect_device(self) -> str:
        """No device detection until IOKit implemented."""
        return ""
