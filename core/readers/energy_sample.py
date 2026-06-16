"""
core/readers/energy_sample.py

EnergySample — canonical in-memory measurement object.

This is the boundary between hardware collection and persistence.
No DB concepts (row IDs, table names) leak in.
No hardware concepts (native keys, counter formats) survive past the collector.

Every PersistenceAdapter receives the same frozen EnergySample instance.
Immutable (frozen=True) to guarantee no adapter mutates shared state.

NFR DC-1: 30% inline comment coverage maintained.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class EnergySample:
    """
    Platform-agnostic energy measurement produced by EnergyCollector.

    domains contains canonical_name -> delta_uj for every domain
    that was successfully measured on this tick. Domains that returned
    None from the reader are absent from this dict — not zero, absent.
    Callers must use .get() with a default.

    source matches energy_sources.name in the DB for methodology tracing.
    run_id is set by EnergyCollector from the active run context.
    timestamp_ns is monotonic nanoseconds at the END of the sampling interval.
    interval_ns is the duration of the sampling interval for this tick.
    """

    timestamp_ns: int                        # monotonic ns at end of interval
    interval_ns:  int                        # duration of this sampling interval
    source:       str                        # energy_sources.name e.g. "RAPL", "SPBM"
    run_id:       int                        # active run this sample belongs to
    domains:      Dict[str, int] = field(    # canonical_name -> delta µJ
        default_factory=dict
    )

    def get_domain(self, canonical_name: str, default: int = 0) -> int:
        """Safe domain lookup — returns default if domain absent or None."""
        # absent means not measured on this platform, not zero
        return self.domains.get(canonical_name, default)

    def has_domain(self, canonical_name: str) -> bool:
        """True if this domain was measured on this tick."""
        return canonical_name in self.domains

    @property
    def total_uj(self) -> int:
        """Sum of all measured domain deltas. Useful for sanity checks."""
        # Note: do not use for attribution — domains may overlap (parent+child)
        return sum(self.domains.values())
