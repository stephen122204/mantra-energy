"""
Energy sample dataclasses and constants for unified multi-platform schema.

These classes replace the per-platform sample objects (SPBMSample, GpuSample)
with a single backend-neutral representation. The source_id and domain_id
constants map directly to energy_sources and energy_domains seed data.

All measurement code produces EnergySampleV2 objects.
All telemetry code produces DeviceTelemetrySample objects.
Repository layer inserts both into the normalized schema.

PAC-2 compliant: no platform logic here. source_id carries the platform identity.

cp to: core/readers/energy_sample_v2.py
"""

from dataclasses import dataclass, field
from typing import Dict, Optional

# ---------------------------------------------------------------------------
# Domain ID constants — match energy_domains seed data exactly
# Never hardcode domain integers in measurement code — use these constants
# ---------------------------------------------------------------------------

DOMAIN_PACKAGE    = 1   # Total SoC package (Intel, ARM Grace)
DOMAIN_CORE       = 2   # CPU core complex (Intel x86)
DOMAIN_UNCORE     = 3   # Uncore / system agent (Intel)
DOMAIN_DRAM       = 4   # Memory subsystem (Intel RAPL)
DOMAIN_CPU_P      = 5   # Performance cores (ARM Grace X925)
DOMAIN_CPU_E      = 6   # Efficiency cores (ARM Grace A725)
DOMAIN_GPU        = 7   # GPU energy domain (any vendor)
DOMAIN_CCD0       = 8   # Core complex die 0 (AMD EPYC)
DOMAIN_CCD1       = 9   # Core complex die 1 (AMD EPYC)
DOMAIN_IODIE      = 10  # IO die (AMD EPYC)
DOMAIN_UNIFIED    = 11  # Unified CPU+GPU package (Apple M1/M2)
DOMAIN_CPU_APPLE  = 12  # Apple CPU cluster
DOMAIN_GPU_APPLE  = 13  # Apple GPU cluster
DOMAIN_NETWORK    = 14  # Network interconnect root
DOMAIN_NVLINK_C2C = 15  # NVLink-C2C die-to-die (GN100 GB10)
DOMAIN_NVLINK     = 16  # NVLink between discrete GPUs
DOMAIN_RDMA       = 17  # RDMA operation energy
DOMAIN_INFINIBAND = 18  # InfiniBand link energy
DOMAIN_ACCELERATOR= 19  # Accelerator root
DOMAIN_DLA        = 20  # Deep Learning Accelerator (GN100 SPBM)
DOMAIN_NPU        = 21  # Neural Processing Unit (future)
DOMAIN_STORAGE    = 22  # Storage root
DOMAIN_NVME       = 23  # NVMe SSD energy
# DOMAIN_GPU_DCGM = 24 exists in energy_domains table but has no constant
# here — DCGM samples never flow through energy_sample_domains, they are
# summed in-memory by GPUCollector (core/energy_engine.py
# _resolve_gpu_total_uj), so this file never needed the constant.
# Confirmed 2026-06-21 during SPEC_SPBM_FULL_TELEMETRY prerequisite check.
# SPEC_SPBM_FULL_TELEMETRY (2026-06-21): power-only channels, no hardware
# cumulative energy counter — energy values for these domains are
# integration-derived (power * dt per sample tick) in SPBMSampler._loop(),
# not delta'd from a counter like the domains above.
# NOTE: DLA is NOT added here — DOMAIN_DLA = 20 already exists above
# (line ~37, comment "(GN100 SPBM)"), reserved but never wired up until
# now. Migration v76 seeds energy_domains.domain_id=20 for it, reusing
# this existing constant rather than creating a duplicate.
DOMAIN_SOC_PKG    = 25  # SPBM soc_pkg power rail
DOMAIN_CPU_GPU    = 26  # SPBM cpu_gpu combined power rail
DOMAIN_VCORE      = 27  # SPBM vcore voltage rail
DOMAIN_DC_INPUT   = 28  # SPBM dc_input rail, system boundary — physical
                        # measurement point not yet vendor-verified
DOMAIN_PREREG     = 29  # SPBM prereg power rail

# ---------------------------------------------------------------------------
# Source ID constants — match energy_sources seed data exactly
# source_id identifies which hardware interface produced the measurement
# ---------------------------------------------------------------------------

SOURCE_RAPL       = 1   # Intel RAPL sysfs (UBUNTU2505, Alex, TAMU)
SOURCE_SPBM       = 2   # NVIDIA spark_hwmon SoC (GN100)
SOURCE_NVML       = 3   # NVIDIA NVML cumulative counter (Alex RTX)
SOURCE_DCGM       = 4   # NVIDIA DCGM field 156 (GN100 GPU compute)
SOURCE_IOKIT      = 5   # Apple IOKit power sensor (Stephen M1)
SOURCE_AMD_ENERGY = 6   # AMD amd_energy module (future AMD)
SOURCE_SMI_INTEG  = 7   # nvidia-smi power integration (TAMU H100/Tesla)
SOURCE_MSR_PP1    = 8   # Intel MSR 0x641 PP1 (UBUNTU2505 Iris Xe)
SOURCE_SPBM_V2    = 9   # NVIDIA spark_hwmon v2 (future GH200)


@dataclass
class EnergySampleV2:
    """
    One energy measurement event from any hardware backend.

    Replaces per-platform sample objects with a single neutral representation.
    source_id identifies which interface was read (RAPL, SPBM, DCGM etc).
    domains maps domain_id to energy_uj for all measured domains in this read.

    On GN100 one SPBM atomic read produces one EnergySampleV2 with four
    domains (PACKAGE, CPU_P, CPU_E, GPU). One DCGM read produces a separate
    EnergySampleV2 with one domain (GPU). Both are inserted as separate rows
    in energy_samples_v2 and their domain rows in energy_sample_domains.
    ETL later subtracts SPBM GPU - DCGM GPU to get NVLink-C2C energy.

    Args:
        timestamp_ns: Sample timestamp in nanoseconds (UTC).
        interval_ns:  Duration this sample covers in nanoseconds.
        source_id:    Which hardware interface produced this (SOURCE_* constant).
        domains:      Dict of domain_id to energy_uj for measured domains.
                      Only include domains actually measured — absent = not NULL.
    """
    timestamp_ns: int
    interval_ns:  int
    source_id:    int
    domains:      Dict[int, float] = field(default_factory=dict)


@dataclass
class DeviceTelemetrySample:
    """
    One device state snapshot — instantaneous power, temperature, utilization.

    This is NOT energy. Power is instantaneous (mW). Energy is cumulative (µJ).
    energy_uj present when backend provides it (NVML, DCGM cumulative counter).
    energy_uj is NULL for SMI_INTEG — power integration done at ETL time.

    device_type categories:
        'GPU'     discrete or integrated GPU
        'SOC'     full SoC (dc_input_mw from SPBM dc_input channel)
        'CPU'     CPU-only telemetry (frequency, C-states)
        'NETWORK' network device (future RDMA telemetry)
        'STORAGE' storage device (future NVMe telemetry)

    Args:
        timestamp_ns: Sample timestamp in nanoseconds (UTC).
        interval_ns:  Duration this sample covers.
        source_id:    Which interface produced this (SOURCE_* constant).
        device_type:  Category string from list above.
        power_mw:     Instantaneous power in milliwatts. NULL if unavailable.
        energy_uj:    Cumulative energy delta in µJ. NULL for SMI_INTEG.
        util_pct:     Device utilization 0-100. NULL if unavailable.
        temp_c:       Device temperature in Celsius. NULL if unavailable.
        clock_mhz:    Device clock in MHz. NULL if unavailable.
        dc_input_mw:  Wall input power in mW (SPBM dc_input, SOC only).
        mem_util_pct: Memory utilization 0-100 (GPU only).
    """
    timestamp_ns: int
    interval_ns:  int
    source_id:    int
    device_type:  str
    power_mw:     Optional[float] = None
    energy_uj:    Optional[float] = None
    util_pct:     Optional[float] = None
    temp_c:       Optional[float] = None
    clock_mhz:    Optional[float] = None
    dc_input_mw:  Optional[float] = None
    mem_util_pct: Optional[float] = None
