"""
core/readers/darwin/nic_reader.py
Darwin NIC byte counter reader via psutil.

SPEC_03A: Implements NICReaderABC for macOS. Reads tx_bytes/rx_bytes/
tx_packets/rx_packets from psutil.net_io_counters(). No subprocess,
no sudo required. Auto-detects primary interface (en0 preferred).

PAC-2: Only imported in core/readers/nic_collector.py _make_reader().
PAC-4: Never raises — returns None on any failure.
DC-1:  ~30% inline comment coverage explaining WHY not WHAT.
PVC-1: Python 3.9 compatible. No walrus operator, no 3.10+ syntax.
"""

import logging
import platform
from typing import Dict, Optional

from core.readers.interfaces import NICReaderABC

logger = logging.getLogger(__name__)

# Interfaces to skip — virtual, loopback, tunnel, Apple-internal
_SKIP_PREFIXES = ("lo", "utun", "bridge", "llw", "awdl", "anpi", "ap", "gif", "stf")


class DarwinNICReader(NICReaderABC):
    """
    Reads NIC byte/packet counters via psutil on macOS.

    Detects the primary active interface once at init (en0 preferred —
    it is the primary WiFi/Ethernet port on all Apple Silicon Macs).
    Falls back to any en* interface with non-zero byte counters.
    """

    def __init__(self, config=None):
        # type: (Optional[Dict]) -> None
        self._config = config or {}
        # Detect interface once at init — stable for the life of the reader
        self._iface = self._detect_interface()

    def is_available(self):
        # type: () -> bool
        """True only on Darwin with psutil available and interface detected."""
        if platform.system() != "Darwin":
            return False
        try:
            import psutil  # noqa: F401 — availability check only
            return self._iface is not None
        except ImportError:
            logger.warning("DarwinNICReader: psutil not available")
            return False

    def get_name(self):
        # type: () -> str
        """Reader identifier for logging."""
        return "DarwinNICReader({})".format(self._iface or "no-iface")

    def detect_interface(self):
        # type: () -> Optional[str]
        """Public accessor for the detected interface name."""
        return self._iface

    def get_pci_address(self):
        # type: () -> Optional[str]
        """
        PCI address not available on macOS (no sysfs).
        Returns None — callers must handle None (MIC-1).
        """
        return None

    def read_sample(self):
        # type: () -> Optional[Dict]
        """
        Read one NIC counter snapshot via psutil.

        Returns dict with keys: interface, tx_bytes, rx_bytes,
        tx_packets, rx_packets. Returns None on any failure (PAC-4).
        Timestamps (sample_ns, sample_start_ns, sample_end_ns) are
        added by NICCollector — not here.
        """
        if not self._iface:
            return None
        try:
            import psutil
            counters = psutil.net_io_counters(pernic=True)
            if self._iface not in counters:
                # Interface disappeared (e.g. WiFi disconnected) — degrade gracefully
                logger.warning(
                    "DarwinNICReader: interface %s not in counters", self._iface
                )
                return None
            c = counters[self._iface]
            return {
                "interface":  self._iface,
                "tx_bytes":   c.bytes_sent,
                "rx_bytes":   c.bytes_recv,
                "tx_packets": c.packets_sent,
                "rx_packets": c.packets_recv,
            }
        except Exception as exc:
            # PAC-4: never propagate exceptions from sampling loop
            logger.warning("DarwinNICReader: read_sample failed: %s", exc)
            return None

    # =================================================================
    # Internal
    # =================================================================

    def _detect_interface(self):
        # type: () -> Optional[str]
        """
        Find the primary active NIC. en0 is preferred — it is always
        the primary WiFi or Ethernet port on Apple Silicon Macs.
        Falls back to any en* with non-zero byte counters.
        Returns None if no suitable interface found (PAC-4 safe).
        """
        try:
            import psutil
            counters = psutil.net_io_counters(pernic=True)

            # en0 is the canonical primary interface on all Apple Silicon
            if "en0" in counters and counters["en0"].bytes_sent > 0:
                logger.debug("DarwinNICReader: using en0 as primary interface")
                return "en0"

            # Fall back: any non-virtual interface with traffic
            for iface in sorted(counters.keys()):
                if any(iface.startswith(p) for p in _SKIP_PREFIXES):
                    continue
                c = counters[iface]
                if c.bytes_sent > 0 or c.bytes_recv > 0:
                    logger.debug(
                        "DarwinNICReader: en0 inactive, falling back to %s", iface
                    )
                    return iface

            # Last resort: en0 even if no traffic yet (machine just booted)
            if "en0" in counters:
                return "en0"

            return None

        except Exception as exc:
            logger.warning("DarwinNICReader: interface detection failed: %s", exc)
            return None
