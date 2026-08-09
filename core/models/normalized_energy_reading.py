"""
core/models/normalized_energy_reading.py

Canonical energy snapshot from any platform reader.

Provides a single immutable data shape that every energy reader maps its
platform-specific keys into. Downstream code never inspects raw dicts;
it consumes typed attributes from this dataclass.

PAC-1: frozen=True enforces immutability after construction.
PAC-3: None means domain not available on this platform (never 0).
PAC-4: NormalizedEnergyReading.zero() provides safe degradation.
DC-1: 30% inline comment coverage maintained throughout.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class NormalizedEnergyReading:
    """Canonical energy snapshot from any platform reader.

    All energy values in microjoules. None = domain not available
    on this platform (PAC-3: never use 0 for absent domains).

    Attributes:
        pkg_uj:  Total package/SoC energy envelope. Always present
                 when reader METHOD_PROVENANCE is MEASURED.
        cpu_uj:  CPU cores energy. Subset of pkg on RAPL (core domain),
                 same as pkg on Apple (unified rail), P-cores on GN100.
        gpu_uj:  Integrated GPU energy from reader's own domain.
                 None on RAPL (GPU handled by gpu_collector separately).
        dram_uj: DRAM energy. RAPL only. None on ARM/Apple/GN100.
        ts_ns:   Monotonic timestamp (nanoseconds) when reading was taken.
                 Used for delta-t calculations and rate derivation.
    """

    # --- Energy domains (all microjoules, None if unavailable) ---
    pkg_uj:  Optional[int]   # Package / SoC envelope
    cpu_uj:  Optional[int]   # CPU cores subset
    gpu_uj:  Optional[int]   # Integrated GPU domain (reader-level)
    dram_uj: Optional[int]   # DRAM domain (RAPL only)

    # --- Timing ---
    ts_ns:   int             # time.monotonic_ns() at read instant

    @classmethod
    def zero(cls) -> NormalizedEnergyReading:
        """Safe zero reading for LIMITED/DUMMY readers (PAC-4).

        Returns all energy fields as None (not 0) to correctly signal
        that no measurement hardware is available on this platform.
        """
        return cls(
            pkg_uj=None,
            cpu_uj=None,
            gpu_uj=None,
            dram_uj=None,
            ts_ns=time.monotonic_ns(),
        )

    def delta(self, earlier: NormalizedEnergyReading) -> NormalizedEnergyReading:
        """Compute energy consumed between two readings.

        Returns a new NormalizedEnergyReading where each field is
        (self.field - earlier.field) clamped to max(0, ...).
        If either side is None, result is None for that domain.
        Timestamp is self.ts_ns (the later reading).

        Args:
            earlier: The earlier snapshot (start of measurement window).

        Returns:
            New NormalizedEnergyReading with delta values.
        """
        def _diff(a: Optional[int], b: Optional[int]) -> Optional[int]:
            # Both must be present to compute a meaningful delta
            if a is None or b is None:
                return None
            return max(0, a - b)  # Clamp negative (counter wrap) to 0

        return NormalizedEnergyReading(
            pkg_uj=_diff(self.pkg_uj, earlier.pkg_uj),
            cpu_uj=_diff(self.cpu_uj, earlier.cpu_uj),
            gpu_uj=_diff(self.gpu_uj, earlier.gpu_uj),
            dram_uj=_diff(self.dram_uj, earlier.dram_uj),
            ts_ns=self.ts_ns,  # Keep the later timestamp
        )

    def to_dict(self) -> dict:
        """Serialize to dict for JSON/DB storage.

        Omits None fields to keep stored payloads compact.
        Always includes ts_ns.
        """
        d = {"ts_ns": self.ts_ns}
        if self.pkg_uj is not None:
            d["pkg_uj"] = self.pkg_uj
        if self.cpu_uj is not None:
            d["cpu_uj"] = self.cpu_uj
        if self.gpu_uj is not None:
            d["gpu_uj"] = self.gpu_uj
        if self.dram_uj is not None:
            d["dram_uj"] = self.dram_uj
        return d

    @classmethod
    def from_dict(cls, d: dict) -> NormalizedEnergyReading:
        """Reconstruct from dict (inverse of to_dict).

        Missing keys map to None. ts_ns is required.

        Args:
            d: Dict produced by to_dict().

        Returns:
            NormalizedEnergyReading with fields populated from dict.
        """
        return cls(
            pkg_uj=d.get("pkg_uj"),
            cpu_uj=d.get("cpu_uj"),
            gpu_uj=d.get("gpu_uj"),
            dram_uj=d.get("dram_uj"),
            ts_ns=d["ts_ns"],  # Required field, KeyError if absent
        )
