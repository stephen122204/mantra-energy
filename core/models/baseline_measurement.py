#!/usr/bin/env python3
"""
================================================================================
BASELINE MEASUREMENT – Layer 2: Idle Reference
================================================================================

Represents a system idle power measurement.
After v61, power_watts always uses canonical uppercase energy_domains.name keys:
    PACKAGE, CORE, CPU_P, CPU_E, GPU, DRAM, UNCORE, etc.

Raw platform keys (pkg, package-0, cpu_p) are converted to canonical form
inside measure_idle_baseline() before this object is constructed. No caller
of BaselineMeasurement ever sees raw platform keys (BDC-6).

Author: Deepak Panigrahy
================================================================================
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class BaselineMeasurement:
    """
    Layer 2 idle baseline. NEVER applied to raw data directly.

    power_watts keys are canonical uppercase energy_domains.name values:
        PACKAGE, CORE, CPU_P, CPU_E, GPU, DRAM, UNCORE, GPU_APPLE, etc.
    Raw platform keys (pkg, package-0) are never stored here (BDC-6).

    Attributes:
        baseline_id:       Unique identifier (baseline_<timestamp>_<pid>)
        timestamp:         Unix timestamp when measurement was taken
        power_watts:       Idle power per canonical domain (Watts)
        duration_seconds:  Total measurement duration (num_samples * sample_duration)
        sample_count:      Number of idle samples averaged
        std_dev_watts:     Standard deviation per canonical domain (Watts)
        cpu_temperature_c: Temperature during measurement (None if unavailable — MIC-1)
        method:            Measurement method tag
        metadata:          System state dict (governor, turbo, processes, gpu_method)
    """

    baseline_id:       str
    timestamp:         float
    power_watts:       Dict[str, float]
    duration_seconds:  float
    sample_count:      int
    std_dev_watts:     Dict[str, float] = field(default_factory=dict)
    cpu_temperature_c: Optional[float]  = None
    method:            str              = "idle_measurement"
    metadata:          Dict[str, Any]   = field(default_factory=dict)

    def __post_init__(self):
        """Validate that no power value is negative."""
        for domain, power in self.power_watts.items():
            if power < 0:
                raise ValueError(
                    f"Power cannot be negative for domain {domain}: {power}"
                )

    # ------------------------------------------------------------------
    # Properties — canonical key names after v61
    # ------------------------------------------------------------------

    @property
    def package_power_w(self):
        # type: () -> float
        """
        Package idle power in Watts.
        Uses canonical 'PACKAGE' key (covers both RAPL package-0 and SPBM pkg).
        """
        return self.power_watts.get('PACKAGE', 0.0)

    @property
    def core_power_w(self):
        # type: () -> float
        """
        Core idle power in Watts.
        'CORE' covers RAPL core domain.
        'CPU_P' covers SPBM P-cores on GN100 — checked as fallback.
        """
        return self.power_watts.get('CORE',
               self.power_watts.get('CPU_P', 0.0))

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self):
        # type: () -> Dict[str, Any]
        """Convert to dictionary for JSON serialization and DB insert."""
        return {
            "baseline_id":      self.baseline_id,
            "timestamp":        self.timestamp,
            "timestamp_iso":    datetime.fromtimestamp(self.timestamp).isoformat(),
            "power_watts":      self.power_watts,
            "duration_seconds": self.duration_seconds,
            "sample_count":     self.sample_count,
            "std_dev_watts":    self.std_dev_watts,
            "cpu_temperature_c": self.cpu_temperature_c,
            "method":           self.method,
            "metadata":         self.metadata,
        }

    def to_json(self):
        # type: () -> str
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2, default=str)

    @classmethod
    def from_dict(cls, data):
        # type: (Dict[str, Any]) -> BaselineMeasurement
        """
        Reconstruct from a serialized dictionary.

        Mirrors to_dict() exactly. timestamp_iso is ignored — timestamp
        (float) is the canonical field. Used when loading from JSON cache.

        Args:
            data: Dict produced by to_dict() or stored in JSON cache.

        Returns:
            BaselineMeasurement with all fields populated.
        """
        return cls(
            baseline_id=data["baseline_id"],
            timestamp=data["timestamp"],
            power_watts=data["power_watts"],
            duration_seconds=data["duration_seconds"],
            sample_count=data["sample_count"],
            std_dev_watts=data.get("std_dev_watts", {}),
            cpu_temperature_c=data.get("cpu_temperature_c"),
            method=data.get("method", "idle_measurement"),
            metadata=data.get("metadata", {}),
        )

    # ------------------------------------------------------------------
    # Derived metrics
    # ------------------------------------------------------------------

    def estimate_energy_uj(self, duration_seconds):
        # type: (float) -> Dict[str, int]
        """
        Estimate idle energy for a given duration.

        Args:
            duration_seconds: Duration to estimate for in seconds.

        Returns:
            Estimated idle energy in microjoules per canonical domain.
        """
        return {
            domain: int(power * duration_seconds * 1_000_000)
            for domain, power in self.power_watts.items()
        }

    @property
    def min_power_watts(self):
        # type: () -> Dict[str, float]
        """
        Lower-bound idle power per domain using mean - 2*std (2nd percentile).

        Math: mean - 2*std approximates the 2.5th percentile assuming normal
        distribution, giving a conservative low-bound that excludes most
        background noise while staying physically plausible.

        Uses canonical key names consistent with power_watts dict.
        """
        result = {}
        for domain, power in self.power_watts.items():
            std   = self.std_dev_watts.get(domain, 0.0)
            result[domain] = max(0.0, power - 2.0 * std)
        return result

    def min_energy_uj(self, duration_seconds):
        # type: (float) -> Dict[str, int]
        """
        Convert minimum observed baseline watts to µJ for a given duration.

        Args:
            duration_seconds: Duration to estimate for in seconds.

        Returns:
            Minimum idle energy in microjoules per canonical domain.
        """
        return {
            domain: int(power * duration_seconds * 1_000_000)
            for domain, power in self.min_power_watts.items()
        }
