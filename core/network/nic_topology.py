"""
core/network/nic_topology.py
NIC topology detection for network energy strategy selection.

Determines whether the active NIC is inside the RAPL/SPBM measurement
boundary. This drives which estimation strategy the factory selects.

No subprocess calls. Uses sysfs and /proc only (fast, always available on Linux).
Returns conservative 'unknown' on any failure — never raises (PAC-4).
"""

import logging
import os
import platform
from typing import Optional

logger = logging.getLogger(__name__)

# PCI bus 0 = root complex / PCH = likely inside RAPL uncore boundary
# PCI bus > 0 = downstream PCIe slot = outside RAPL boundary
_PCH_BUS_THRESHOLD = 1


def detect_nic_topology() -> str:
    """
    Detect NIC integration topology for strategy selection.

    Returns one of:
        'pch_integrated'  — NIC on PCH bus (bus 0), inside RAPL uncore
        'discrete'        — NIC on PCIe slot (bus > 0), outside RAPL
        'unknown'         — Cannot determine (no sysfs, macOS, VM, etc.)

    Never raises. Falls back to 'unknown' on any error.
    """
    # Only Linux has sysfs — other platforms fall through to unknown
    if platform.system() != "Linux":
        logger.debug("nic_topology: non-Linux platform → unknown")
        return "unknown"

    iface = _get_active_interface()
    if not iface:
        logger.debug("nic_topology: no active interface found → unknown")
        return "unknown"

    pci_addr = _get_pci_address(iface)
    if not pci_addr:
        logger.debug("nic_topology: no PCI address for %s → unknown", iface)
        return "unknown"

    bus_num = _parse_pci_bus(pci_addr)
    if bus_num is None:
        return "unknown"

    # Bus 0 = root complex / PCH = integrated into SoC power domain
    if bus_num < _PCH_BUS_THRESHOLD:
        logger.debug(
            "nic_topology: %s at %s bus=%d → pch_integrated",
            iface, pci_addr, bus_num,
        )
        return "pch_integrated"

    logger.debug(
        "nic_topology: %s at %s bus=%d → discrete",
        iface, pci_addr, bus_num,
    )
    return "discrete"


def select_strategy_key(
    nic_topology: str,
    has_rapl: bool,
    has_spbm: bool,
) -> str:
    """
    Pure function mapping platform capabilities to strategy key.

    Testable without hardware. Called by factory to select estimator.

    Priority: rapl_slice > spbm_fraction > time_fraction
    rapl_slice requires PCH-integrated NIC + RAPL available.
    spbm_fraction requires SPBM DC_INPUT available (GN100).
    time_fraction is universal fallback.

    Args:
        nic_topology: Output of detect_nic_topology()
        has_rapl:     True if RAPL energy counters accessible
        has_spbm:     True if SPBM DC_INPUT domain accessible

    Returns:
        One of: 'rapl_slice', 'spbm_fraction', 'time_fraction'
    """
    # Strategy A: PCH NIC + RAPL = raw slice, no alpha_cpu (conf 0.93)
    if nic_topology == "pch_integrated" and has_rapl:
        return "rapl_slice"

    # Strategy B: SPBM DC_INPUT available regardless of NIC topology (conf 0.70)
    if has_spbm:
        return "spbm_fraction"

    # Strategy C: universal fallback — time fraction of dynamic energy (conf 0.50)
    return "time_fraction"


def _get_active_interface() -> Optional[str]:
    """
    Find first non-loopback interface with operstate=up via sysfs.

    Reads /sys/class/net/ — no subprocess, no ip command needed.
    Returns interface name or None.
    """
    net_dir = "/sys/class/net"
    if not os.path.isdir(net_dir):
        return None

    try:
        for iface in sorted(os.listdir(net_dir)):
            # Skip loopback — never carries LLM API traffic
            if iface == "lo":
                continue

            operstate_path = os.path.join(net_dir, iface, "operstate")
            if not os.path.exists(operstate_path):
                continue

            with open(operstate_path) as f:
                state = f.read().strip()

            if state == "up":
                return iface

    except OSError as exc:
        logger.debug("nic_topology: sysfs read error: %s", exc)

    return None


def _get_pci_address(iface: str) -> Optional[str]:
    """
    Resolve PCI address for interface via sysfs symlink.

    Reads /sys/class/net/<iface>/device symlink target.
    Returns PCI address string (e.g. '0000:00:14.3') or None.
    """
    device_path = f"/sys/class/net/{iface}/device"
    if not os.path.exists(device_path):
        return None

    try:
        # Symlink target ends with PCI address component
        target = os.readlink(device_path)
        # Extract last component: '0000:00:14.3'
        pci_addr = os.path.basename(target)
        return pci_addr
    except OSError as exc:
        logger.debug("nic_topology: readlink failed for %s: %s", iface, exc)
        return None


def _parse_pci_bus(pci_addr: str) -> Optional[int]:
    """
    Parse bus number from PCI address string.

    PCI address format: 'DDDD:BB:DD.F' where BB is hex bus number.
    Returns int bus number or None on parse failure.
    """
    try:
        # Handle both '0000:00:14.3' and '00:14.3' formats
        parts = pci_addr.split(":")
        if len(parts) == 3:
            # Full format: domain:bus:device.function
            bus_hex = parts[1]
        elif len(parts) == 2:
            # Short format: bus:device.function
            bus_hex = parts[0]
        else:
            return None
        return int(bus_hex, 16)
    except (ValueError, IndexError) as exc:
        logger.debug("nic_topology: PCI parse failed '%s': %s", pci_addr, exc)
        return None
