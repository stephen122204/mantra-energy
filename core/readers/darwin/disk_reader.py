"""
macOS Disk I/O Reader via ioreg IOBlockStorageDriver statistics.
Counter-style: cumulative read/write bytes since device attach.
Emits every field io_samples requires (sample_start_ns, sample_end_ns,
interval_ns), not just byte counts, confirmed against the real table
schema and insert_io_samples()'s real contract 2026-07-06.
"""

import os
import re
import time
import subprocess
from typing import Optional, Dict

from core.readers.interfaces import DiskReaderABC


class IOKitDiskReader(DiskReaderABC):
    """macOS disk reader via ioreg IOBlockStorageDriver statistics."""

    def __init__(self, config: dict = None, device: str = "", pid: int = 0):
        self.device = device
        self.pid = pid
        self._last = None
        self._last_sample_ns = None

    def is_available(self) -> bool:
        return os.uname().sysname == "Darwin"

    def sample(self) -> Optional[Dict]:
        if not self.is_available():
            return None

        sample_start_ns = time.time_ns()
        try:
            result = subprocess.run(
                ["ioreg", "-c", "IOBlockStorageDriver", "-r", "-w0"],
                capture_output=True, text=True, timeout=5,
            )
            sample_end_ns = time.time_ns()

            if result.returncode != 0:
                return None

            read_match = re.search(r'"Bytes \(Read\)"\s*=\s*(\d+)', result.stdout)
            write_match = re.search(r'"Bytes \(Write\)"\s*=\s*(\d+)', result.stdout)

            if read_match is None and write_match is None:
                return None

            # interval_ns: elapsed since the previous sample call, not the
            # duration of this ioreg subprocess itself. First call has no
            # prior reference, use the subprocess duration as a reasonable
            # first interval rather than 0 (0 could misleadingly suggest
            # an instantaneous, zero-duration sample).
            if self._last_sample_ns is not None:
                interval_ns = sample_start_ns - self._last_sample_ns
            else:
                interval_ns = sample_end_ns - sample_start_ns
            self._last_sample_ns = sample_start_ns

            return {
                "sample_start_ns": sample_start_ns,
                "sample_end_ns": sample_end_ns,
                "interval_ns": interval_ns,
                "device": self.device or "ioreg_aggregate",
                "disk_read_bytes": int(read_match.group(1)) if read_match else None,
                "disk_write_bytes": int(write_match.group(1)) if write_match else None,
                # Not available via IOBlockStorageDriver statistics on this
                # platform, documented NULL, not a bug (MIC-3).
                "io_block_time_ms": None,
                "disk_latency_ms": None,
                "minor_page_faults": None,
                "major_page_faults": None,
            }
        except Exception:
            return None

    def _detect_device(self) -> str:
        return ""
