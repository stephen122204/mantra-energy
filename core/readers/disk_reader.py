"""
Disk I/O reader using /proc/diskstats.

Linux only — gracefully returns None on macOS/ARM where /proc is absent.
Reads delta between two snapshots for accurate per-interval byte counts.

Method ID: disk_io_stats
"""

import os
import time
from typing import Optional, Dict


DISKSTATS_PATH = "/proc/diskstats"


def is_available() -> bool:
    """Return True only on Linux where /proc/diskstats exists."""
    return os.path.exists(DISKSTATS_PATH)


def _read_device(device: str) -> Optional[Dict]:
    """
    Read one device line from /proc/diskstats.
    Fields per kernel docs: https://www.kernel.org/doc/Documentation/iostats.txt
    Returns None if device not found or read fails.
    """
    try:
        with open(DISKSTATS_PATH) as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 14 and parts[2] == device:
                    return {
                        "read_sectors":       int(parts[5]),
                        "read_time_ms":       int(parts[6]),
                        "write_sectors":      int(parts[9]),
                        "write_time_ms":      int(parts[10]),
                        "io_time_ms":         int(parts[12]),
                    }
    except Exception:
        pass
    return None


def _read_page_faults(pid: int) -> tuple:
    """
    Read minor and major page faults from /proc/[pid]/stat.
    Returns (minor_faults, major_faults) or (0, 0) on failure.
    """
    try:
        with open(f"/proc/{pid}/stat") as f:
            parts = f.read().split()
        return int(parts[9]), int(parts[11])   # minflt, majflt
    except Exception:
        return 0, 0


from core.readers.interfaces import DiskReaderABC
class DiskReader(DiskReaderABC):
    """
    Samples disk I/O counters at configurable Hz.

    Usage:
        reader = DiskReader(device='sda', pid=os.getpid())
        reader.start()
        ...
        samples = reader.stop()
    """

    def __init__(self, config: dict = None, device: str = "sda", pid: int = 0):
        device = (config or {}).get("hardware", {}).get("disk_device", device)
        self.device    = device
        self.pid       = pid
        self.available = is_available()
        self._samples  = []
        self._active   = False
        self._last     = None
        
    def is_available(self) -> bool:
        """Return True only on Linux where /proc/diskstats exists."""
        return os.path.exists(DISKSTATS_PATH)
    def _detect_device(self) -> str:
        """Auto-detect primary disk if /proc/diskstats exists."""
        if not self.available:
            return self.device
        try:
            with open(DISKSTATS_PATH) as f:
                for line in f:
                    parts = line.split()
                    name = parts[2]
                    # skip virtual devices — prefer real storage
                    if any(name.startswith(x) for x in ("loop", "zram", "ram", "dm-")):
                        continue
                    if any(name.startswith(x) for x in ("sd", "nvme", "vd", "hd", "xvd")):
                        return name              # real storage device found
        except Exception:
            pass
        return self.device

    def sample(self) -> Optional[Dict]:
        """
        Take one delta sample. Returns None on first call (no previous snapshot).
        Call at desired Hz from sampling loop.
        """
        if not self.available:
            return None

        start_ns = time.time_ns()
        current  = _read_device(self.device)
        end_ns   = time.time_ns()

        if current is None:
            return None

        if self._last is None:
            self._last = current          # prime the pump — no delta yet
            return None

        minor_faults, major_faults = _read_page_faults(self.pid)

        sample = {
            "sample_start_ns":  start_ns,
            "sample_end_ns":    end_ns,
            "interval_ns":      end_ns - start_ns,
            "device":           self.device,
            "disk_read_bytes":  (current["read_sectors"]  - self._last["read_sectors"])  * 512,
            "disk_write_bytes": (current["write_sectors"] - self._last["write_sectors"]) * 512,
            "io_block_time_ms": current["io_time_ms"]    - self._last["io_time_ms"],
            "disk_latency_ms":  current["read_time_ms"]  - self._last["read_time_ms"],
            "minor_page_faults": minor_faults,
            "major_page_faults": major_faults,
        }

        self._last = current
        return sample
