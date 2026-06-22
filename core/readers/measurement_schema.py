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
