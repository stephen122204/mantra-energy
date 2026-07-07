"""
core/readers/measurement_schema.py

MeasurementSchema and DomainDescriptor — declarative platform capability declaration.

Each EnergyReaderABC implementation returns a MeasurementSchema from
get_measurement_schema(). The EnergyCollector uses this to drive generic
sampling with zero platform-specific branching.

PAC-1 compliant: frozen dataclasses — no mutation after construction.
NFR DC-1: 30% inline comment coverage maintained throughout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class DomainDescriptor:
    """
    Describes a single measurable energy domain on a hardware platform.

    native_key maps to the dict key returned by EnergyReaderABC.read_energy().
    canonical_name maps to energy_domains.name in the DB — must match exactly.
    domain_type distinguishes energy counters (cumulative, delta computed)
    from power rails (instantaneous, stored as-is).
    parent_domain enables conservation invariant checks without hardcoding
    which domains are children of which — the hierarchy is declared here.
    """

    native_key:     str            # key in read_energy() dict e.g. "package-0", "cpu_e"
    canonical_name: str            # energy_domains.name e.g. "PACKAGE", "CPU_E"
    domain_type:    str            # "ENERGY_COUNTER" or "POWER_RAIL"
    parent_domain:  Optional[str]  # canonical_name of parent, None for roots


# Domain type constants — use these, never raw strings
ENERGY_COUNTER = "ENERGY_COUNTER"   # cumulative µJ counter, delta computed per tick
POWER_RAIL     = "POWER_RAIL"       # instantaneous mW reading, stored as-is


@dataclass(frozen=True)
class MeasurementSchema:
    """
    Declarative description of a platform's energy measurement capabilities.

    Returned by EnergyReaderABC.get_measurement_schema().
    Called ONCE at EnergyCollector startup and cached — must not perform I/O.
    Frozen to prevent mutation after construction.

    source must match energy_sources.name in the DB exactly.
    domains is a tuple (immutable) of all measurable domains on this platform.
    sampling_hz is the native maximum safe rate for this hardware interface.
    counter_width_bits drives wraparound delta correction in EnergyCollector.
    """

    source:              str                           # energy_sources.name e.g. "RAPL", "SPBM"
    domains:             Tuple[DomainDescriptor, ...]  # all measurable domains, immutable
    sampling_hz:         int                           # native max safe sampling rate
    counter_width_bits:  int                           # 32 (RAPL x86) or 64 (SPBM ARM)
    unit:                str = "microjoules"           # declared explicitly for paper citability


# ---------------------------------------------------------------------------
# Pre-built schemas for all known platforms.
# Readers return these from get_measurement_schema().
# ---------------------------------------------------------------------------

SCHEMA_RAPL_X86 = MeasurementSchema(
    source="RAPL",
    domains=(
        DomainDescriptor(
            native_key="package-0",
            canonical_name="PACKAGE",
            domain_type=ENERGY_COUNTER,
            parent_domain=None,             # PACKAGE is root
        ),
        DomainDescriptor(
            native_key="core",
            canonical_name="CORE",
            domain_type=ENERGY_COUNTER,
            parent_domain="PACKAGE",        # CORE is child of PACKAGE
        ),
        DomainDescriptor(
            native_key="uncore",
            canonical_name="UNCORE",
            domain_type=ENERGY_COUNTER,
            parent_domain="PACKAGE",        # UNCORE is child of PACKAGE
        ),
        DomainDescriptor(
            native_key="dram",
            canonical_name="DRAM",
            domain_type=ENERGY_COUNTER,
            parent_domain=None,             # DRAM is independent root on most Intel
        ),
    ),
    sampling_hz=100,
    counter_width_bits=32,                  # RAPL MSR counters wrap at 2^32 µJ
)

SCHEMA_SPBM_ARM = MeasurementSchema(
    source="SPBM",
    domains=(
        DomainDescriptor(
            native_key="pkg",
            canonical_name="PACKAGE",
            domain_type=ENERGY_COUNTER,
            parent_domain=None,             # PACKAGE is root on GN100
        ),
        DomainDescriptor(
            native_key="cpu_p",
            canonical_name="CPU_P",
            domain_type=ENERGY_COUNTER,
            parent_domain="PACKAGE",        # performance cores inside pkg
        ),
        DomainDescriptor(
            native_key="cpu_e",
            canonical_name="CPU_E",
            domain_type=ENERGY_COUNTER,
            parent_domain="PACKAGE",        # efficiency cores inside pkg
        ),
        DomainDescriptor(
            native_key="gpu",
            canonical_name="GPU",
            domain_type=ENERGY_COUNTER,
            parent_domain=None,             # GPU not a sub-domain of PACKAGE on Grace
        ),
        # SPEC_SPBM_FULL_TELEMETRY: power-only channels, no hardware cumulative
        # counter — EnergyCollector stores raw mW reading per tick (POWER_RAIL
        # branch), NormalizedWriter integrates to energy_uj via power*interval_ns.
        DomainDescriptor(
            native_key="soc_pkg",
            canonical_name="SOC_PKG",
            domain_type=POWER_RAIL,
            parent_domain="PACKAGE",
        ),
        DomainDescriptor(
            native_key="cpu_gpu",
            canonical_name="CPU_GPU",
            domain_type=POWER_RAIL,
            parent_domain="PACKAGE",
        ),
        DomainDescriptor(
            native_key="vcore",
            canonical_name="VCORE",
            domain_type=POWER_RAIL,
            parent_domain="PACKAGE",
        ),
        DomainDescriptor(
            native_key="dc_input",
            canonical_name="DC_INPUT",
            domain_type=POWER_RAIL,
            parent_domain=None,             # system boundary, not under PACKAGE
        ),
        DomainDescriptor(
            native_key="prereg",
            canonical_name="PREREG",
            domain_type=POWER_RAIL,
            parent_domain="PACKAGE",
        ),
        DomainDescriptor(
            native_key="dla",
            canonical_name="DLA",
            domain_type=POWER_RAIL,
            parent_domain="PACKAGE",
        ),
    ),
    sampling_hz=10,
    counter_width_bits=64,                  # SPBM counters are 64-bit, no early wraparound
)

SCHEMA_APPLE_IOKIT = MeasurementSchema(
    source="IOKIT",
    domains=(
        DomainDescriptor(
            native_key="cpu",
            canonical_name="CPU_APPLE",
            domain_type=ENERGY_COUNTER,
            parent_domain="UNIFIED",        # Apple unified memory: CPU under UNIFIED root
        ),
        DomainDescriptor(
            native_key="gpu",
            canonical_name="GPU_APPLE",
            domain_type=ENERGY_COUNTER,
            parent_domain="UNIFIED",        # Apple unified memory: GPU under UNIFIED root
        ),
    ),
    sampling_hz=10,
    counter_width_bits=64,
)

SCHEMA_AMD_ENERGY = MeasurementSchema(
    source="AMD_ENERGY",
    domains=(
        DomainDescriptor(
            native_key="package-0",
            canonical_name="PACKAGE",
            domain_type=ENERGY_COUNTER,
            parent_domain=None,
        ),
        DomainDescriptor(
            native_key="core",
            canonical_name="CORE",
            domain_type=ENERGY_COUNTER,
            parent_domain="PACKAGE",
        ),
    ),
    sampling_hz=100,
    counter_width_bits=32,
)

SCHEMA_DUMMY = MeasurementSchema(
    source="DUMMY",
    domains=(),                             # no domains — safe empty schema
    sampling_hz=10,
    counter_width_bits=64,
)

# ---------------------------------------------------------------------------
# Role constants for cross-platform domain resolution.
# Set on DomainDescriptor.canonical_role (field added below) to allow
# energy_analyzer.py to find the right domain on any platform without
# hardcoding domain name strings per-platform.
# ---------------------------------------------------------------------------
ROLE_TOTAL = "TOTAL"   # package / SoC root — used for idle_uj subtraction
ROLE_CPU   = "CPU"     # CPU-cores child domain — used for idle_core_uj subtraction
ROLE_GPU   = "GPU"     # GPU child domain

# Role assignments for every known schema.
# Keyed by canonical_name. Any name not listed here gets role=None.
_CANONICAL_ROLE_MAP: dict = {
    # RAPL x86
    "PACKAGE":   ROLE_TOTAL,
    "CORE":      ROLE_CPU,
    # SPBM ARM (GN100)
    # CPU_P = performance cores, the CPU energy domain for baseline subtraction.
    # CPU_E = efficiency cores, intentionally None — folded into PACKAGE total.
    "CPU_P":     ROLE_CPU,
    # Apple IOKit
    # UNIFIED root is not declared as a DomainDescriptor in SCHEMA_APPLE_IOKIT
    # (Apple does not expose a unified total counter directly). CPU_APPLE is
    # the closest available total on Apple — assign TOTAL so idle_uj resolves.
    "CPU_APPLE": ROLE_TOTAL,
    "GPU_APPLE": ROLE_GPU,
    # AMD (same RAPL naming as x86 Intel)
    # PACKAGE and CORE already covered above.
}

def validate_schema_roles(schema: MeasurementSchema) -> None:
    """Call once after defining any new schema object.
    Raises ValueError if a domain's canonical_name is not in _CANONICAL_ROLE_MAP
    and has no parent_domain=None (i.e. it is a root domain that needs a role).
    """
    for d in schema.domains:
        if d.parent_domain is None and d.canonical_name not in _CANONICAL_ROLE_MAP:
            raise ValueError(
                f"Schema '{schema.source}': root domain '{d.canonical_name}' "
                f"has no entry in _CANONICAL_ROLE_MAP. Add it before shipping."
            )
        
def find_idle_uj(min_energy: dict) -> int:
    """Return the idle baseline energy for the TOTAL/package domain.

    Searches min_energy keys against the role map. Falls back to the
    historical hardcoded name list for any reader not yet in the role map.
    Works on all platforms with zero platform-specific branching in callers.

    Args:
        min_energy: dict mapping canonical_name -> baseline energy in µJ,
                    from BaselineMeasurement.min_energy_uj().

    Returns:
        Idle energy in µJ, or 0 if no matching domain found.
    """
    for name, role in _CANONICAL_ROLE_MAP.items():
        if role == ROLE_TOTAL and name in min_energy:
            return min_energy[name]
    # Defensive fallback for any reader not yet in the role map
    return min_energy.get("PACKAGE", min_energy.get("package-0", 0))


def find_idle_core_uj(min_energy: dict) -> int:
    """Return the idle baseline energy for the CPU-cores domain.

    Args:
        min_energy: dict mapping canonical_name -> baseline energy in µJ.

    Returns:
        Idle core energy in µJ, or 0 if no matching domain found.
    """
    for name, role in _CANONICAL_ROLE_MAP.items():
        if role == ROLE_CPU and name in min_energy:
            return min_energy[name]
    # Defensive fallback
    return min_energy.get("CORE", min_energy.get("CPU_P", min_energy.get("core", 0)))
