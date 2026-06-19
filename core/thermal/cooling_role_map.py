"""
COOLING_ROLE_MAP — compile-time registry mapping kernel cooling device type
strings to canonical cooling roles.

Canonical roles:
    FAN                  — cooling fan (passive on GN100: max_state=0)
    CPU_FREQ_THROTTLE    — CPU frequency reduction (Processor devices)
    PCIE_LINK_THROTTLE   — PCIe link speed reduction
    POWER_CLAMP          — Intel power clamping (intel_powerclamp)
    TCC_OFFSET           — Intel TCC offset (thermal control circuit)
    OTHER                — unknown device type (still sampled)

cp to: core/thermal/cooling_role_map.py
"""

from typing import Dict


COOLING_ROLE_MAP: Dict[str, str] = {
    "Fan":               "FAN",
    "Processor":         "CPU_FREQ_THROTTLE",   # GN100: 20 devices, max_state=3
    "intel_powerclamp":  "POWER_CLAMP",
    "TCC Offset":        "TCC_OFFSET",
}

# PCIe link speed devices use a prefix match (device name encodes PCI address)
PCIE_LINK_PREFIX = "PCIe_Port_Link_Speed"


def resolve_cooling_role(device_type: str) -> str:
    """
    Map a kernel cooling device type string to a canonical role.

    PCIe_Port_Link_Speed_* devices are matched by prefix — their full name
    encodes the PCI bus address (e.g. PCIe_Port_Link_Speed_0000:00:1c.0).
    Unknown device types return 'OTHER' — still sampled and stored.

    Args:
        device_type: Kernel cooling device type from
                     /sys/class/thermal/cooling_deviceN/type file.

    Returns:
        Canonical role string.
    """
    if device_type.startswith(PCIE_LINK_PREFIX):
        return "PCIE_LINK_THROTTLE"
    return COOLING_ROLE_MAP.get(device_type, "OTHER")


# Roles used for throttle detection in detect_throttle()
THROTTLE_ROLES = {"CPU_FREQ_THROTTLE", "POWER_CLAMP", "TCC_OFFSET"}
