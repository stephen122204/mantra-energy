#!/usr/bin/env python3
"""
================================================================================
BASELINE MEASUREMENT – Layer 2: Idle Reference
================================================================================

This class represents system idle power measurements.
Stored separately from raw measurements, never applied directly.

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
    Layer 2 – System idle baseline. NEVER applied to raw data.

    This represents the energy the system would consume if completely idle.
    Used only for derived calculations, never to modify raw measurements.

    Attributes:
        baseline_id: Unique identifier
        timestamp: When baseline was measured
        power_watts: Idle power per domain (Watts)
        duration_seconds: How long we measured
        sample_count: Number of samples taken
        std_dev_watts: Standard deviation per domain
        cpu_temperature_c: Temperature during measurement
        method: How baseline was obtained
        metadata: Additional context
    """

    baseline_id: str
    timestamp: float

    # Power in Watts (Joules per second)
    power_watts: Dict[str, float]

    # Measurement metadata
    duration_seconds: float
    sample_count: int
    std_dev_watts: Dict[str, float] = field(default_factory=dict)

    # Conditions during measurement
    cpu_temperature_c: Optional[float] = None

    # How it was measured
    method: str = "idle_measurement"

    # Additional context
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate baseline values."""
        for domain, power in self.power_watts.items():
            if power < 0:
                raise ValueError(f"Power cannot be negative for {domain}: {power}")

    def estimate_energy_uj(self, duration_seconds: float) -> Dict[str, int]:
        """
        Estimate idle energy for a given duration.

        Args:
            duration_seconds: Duration to estimate for

        Returns:
            Estimated idle energy in microjoules per domain
        """
        estimate = {}
        for domain, power in self.power_watts.items():
            energy_j = power * duration_seconds
            estimate[domain] = int(energy_j * 1_000_000)
        return estimate

    @property
    def package_power_w(self) -> float:
        """Get package idle power."""
        return self.power_watts.get("package-0", 0.0)

    @property
    def core_power_w(self) -> float:
        """Get core idle power."""
        return self.power_watts.get("core", 0.0)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "baseline_id": self.baseline_id,
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(self.timestamp).isoformat(),
            "power_watts": self.power_watts,
            "duration_seconds": self.duration_seconds,
            "sample_count": self.sample_count,
            "std_dev_watts": self.std_dev_watts,
            "cpu_temperature_c": self.cpu_temperature_c,
            "method": self.method,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(self.to_dict(), indent=2, default=str)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaselineMeasurement":
        """
        Reconstruct BaselineMeasurement from a serialized dictionary.

        Mirrors to_dict() exactly. Used when loading baseline from JSON cache.
        timestamp_iso is ignored — timestamp (float) is the canonical field.

        Args:
            data: Dictionary produced by to_dict() or stored in JSON cache.

        Returns:
            BaselineMeasurement instance with all fields populated.
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
    @property
    def min_power_watts(self) -> Dict[str, float]:
        """
        Estimate a lower-bound idle power for realistic baseline.

        Math: mean - 2*std_dev ≈ 2nd percentile (assuming normal distribution)
        - 68% of values fall within mean ± 1σ
        - 95% of values fall within mean ± 2σ
        - 2.5% of values are below mean - 2σ
        - So mean - 2σ represents ~2.5th percentile (conservative low bound)

        For non-normal distributions, this still gives a robust lower estimate
        that eliminates most background noise while staying physically possible.
        """
        pkg = self.power_watts.get("package-0", 0)
        core = self.power_watts.get("core", 0)
        pkg_std = self.std_dev_watts.get("package-0", 0)
        core_std = self.std_dev_watts.get("core", 0)

        # Use mean - 2*std (2nd percentile) as minimum baseline
        # This ensures baseline is lower than most actual measurements
        # while not being unrealistically low (like 0)
        min_pkg = max(0, pkg - 2 * pkg_std)
        min_core = max(0, core - 2 * core_std)

        # Uncore derived from package - core
        # This assumes uncore power is the remainder after core
        min_uncore = max(0, min_pkg - min_core)
        # GPU baseline: use mean - 2*std same as pkg/core
        gpu = self.power_watts.get("gpu", 0)
        gpu_std = self.std_dev_watts.get("gpu", 0)
        min_gpu = max(0, gpu - 2 * gpu_std)
        return {"package-0": min_pkg, "core": min_core, "uncore": min_uncore, "gpu": min_gpu}

    def min_energy_uj(self, duration_seconds: float) -> Dict[str, int]:
        """Convert minimum observed baseline watts into µJ for duration."""
        pw = self.min_power_watts
        return {
            "package-0": int(pw["package-0"] * duration_seconds * 1_000_000),
            "core":      int(pw["core"]      * duration_seconds * 1_000_000),
            "uncore":    int(pw["uncore"]    * duration_seconds * 1_000_000),
            # GPU baseline from MSR 0x641 idle rate — zero if not measured
            "gpu":       int(pw.get("gpu", 0) * duration_seconds * 1_000_000),
        }
