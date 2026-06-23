"""
core/readers/linux/nic_sysfs_reader.py
Linux NIC byte counter reader via sysfs.

SPEC_03A: Reads tx_bytes/rx_bytes/tx_packets/rx_packets from
/sys/class/net/<iface>/statistics/ at sample time.

Used by NIC collector to build nic_samples table — one row per
sample interval, same cadence as energy_samples (100Hz).

PAC-2: Only imported via factory.py.
PAC-4: Never raises — returns None on any failure.
DC-1:  30% inline comment coverage.
"""

import logging
import os
import platform
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# sysfs paths — all reads are O(1) kernel counter reads
_NET_DIR = "/sys/class/net"
_STATS_FIELDS = ["tx_bytes", "rx_bytes", "tx_packets", "rx_packets"]


from core.readers.interfaces import NICReaderABC


class LinuxNICSysfsReader(NICReaderABC):
    """
    Reads NIC byte/packet counters from sysfs statistics.

    Detects active interface once at init, then reads counters
    on every read_sample() call. No subprocess calls (fast, PAC-4 safe).
    """

    def __init__(self, config: dict):
        self._config = config
        self._iface: Optional[str] = None
        # Auto-detect on first read if not already detected
        self._iface = self._detect_interface()

    def is_available(self) -> bool:
        """True if sysfs net dir exists and active interface detected."""
        return (
            platform.system() == "Linux"
            and os.path.isdir(_NET_DIR)
            and self._iface is not None
        )

    def get_name(self) -> str:
        return f"LinuxNICSysfsReader({self._iface or 'no-iface'})"

    def detect_interface(self) -> Optional[str]:
        """Public accessor for detected interface name."""
        return self._iface

    def get_pci_address(self) -> Optional[str]:
        """
        Resolve PCI address for the active interface via sysfs symlink.
        Returns None if not a PCI device (USB NIC, virtual, etc.).
        """
        if not self._iface:
            return None
        device_path = f"{_NET_DIR}/{self._iface}/device"
        if not os.path.exists(device_path):
            return None
        try:
            target = os.readlink(device_path)
            return os.path.basename(target)
        except OSError:
            return None

    def read_sample(self) -> Optional[Dict[str, Optional[int]]]:
        """
        Read one NIC counter snapshot from sysfs.

        Returns dict with keys: interface, tx_bytes, rx_bytes,
        tx_packets, rx_packets. Values are cumulative counters
        (monotonically increasing, reset on interface restart).

        Returns None if interface not available or read fails.
        Never raises (PAC-4).
        """
        if not self._iface:
            return None

        result: Dict[str, Optional[int]] = {
            "interface": self._iface,
            "tx_bytes":   None,
            "rx_bytes":   None,
            "tx_packets": None,
            "rx_packets": None,
        }

        stats_dir = f"{_NET_DIR}/{self._iface}/statistics"
        if not os.path.isdir(stats_dir):
            logger.debug("nic_sysfs: stats dir missing for %s", self._iface)
            return None

        for field in _STATS_FIELDS:
            path = f"{stats_dir}/{field}"
            try:
                with open(path) as f:
                    result[field] = int(f.read().strip())
            except (OSError, ValueError) as exc:
                # Individual field failure — log and continue
                logger.debug("nic_sysfs: failed reading %s: %s", path, exc)

        return result

    # ── Private ──────────────────────────────────────────────────────────────

    def _detect_interface(self) -> Optional[str]:
        """
        Find first non-loopback interface with operstate=up via sysfs.

        Reads /sys/class/net/<iface>/operstate — no ip command, no subprocess.
        Returns interface name or None.
        """
        if platform.system() != "Linux" or not os.path.isdir(_NET_DIR):
            return None

        try:
            for iface in sorted(os.listdir(_NET_DIR)):
                # Skip loopback — never carries LLM API traffic
                if iface == "lo":
                    continue

                # Skip virtual/docker interfaces
                if iface.startswith(("docker", "br-", "virbr", "veth")):
                    continue

                operstate_path = f"{_NET_DIR}/{iface}/operstate"
                if not os.path.exists(operstate_path):
                    continue

                try:
                    with open(operstate_path) as f:
                        state = f.read().strip()
                except OSError:
                    continue

                if state == "up":
                    logger.debug("nic_sysfs: detected active interface %s", iface)
                    return iface

        except OSError as exc:
            logger.debug("nic_sysfs: interface detection failed: %s", exc)

        return None
