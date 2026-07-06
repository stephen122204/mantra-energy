"""
macOS Disk I/O Reader via ioreg IOBlockStorageDriver statistics.
Counter-style: cumulative read/write bytes since device attach.
Callers compute deltas between two sample() calls.
"""

import os
import re
import subprocess
from typing import Optional, Dict

from core.readers.interfaces import DiskReaderABC


class IOKitDiskReader(DiskReaderABC):
    """macOS disk reader via ioreg IOBlockStorageDriver statistics."""

    def __init__(self, config: dict = None, device: str = "", pid: int = 0):
        self.device = device
        self.pid = pid
        self._last = None

    def is_available(self) -> bool:
        return os.uname().sysname == "Darwin"

    def sample(self) -> Optional[Dict]:
        if not self.is_available():
            return None
        try:
            result = subprocess.run(
                ["ioreg", "-c", "IOBlockStorageDriver", "-r", "-w0"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return None

            read_match = re.search(r'"Bytes \(Read\)"\s*=\s*(\d+)', result.stdout)
            write_match = re.search(r'"Bytes \(Write\)"\s*=\s*(\d+)', result.stdout)

            if read_match is None and write_match is None:
                return None

            return {
                "disk_read_bytes": int(read_match.group(1)) if read_match else None,
                "disk_write_bytes": int(write_match.group(1)) if write_match else None,
            }
        except Exception:
            return None

    def _detect_device(self) -> str:
        return ""
