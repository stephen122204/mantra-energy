"""
core/readers/persistence_adapter.py

PersistenceAdapter — abstract interface for writing EnergySample to storage.

Each adapter maps the canonical EnergySample to its target format.
Adapters MUST NOT call reader methods or access hardware state.
Adapters receive only the EnergySample — no platform context leaks in.

PAC-2 compliant: write() must never raise. Callers do not wrap in try/except.
NFR DC-1: 30% inline comment coverage maintained.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.readers.energy_sample import EnergySample


class PersistenceAdapter(ABC):
    """
    Interface for writing EnergySample objects to a storage backend.

    Implementations: NormalizedWriter, LegacyWriter, CSVWriter (future).
    Each adapter is responsible for its own thread safety.
    write() is called from the EnergyCollector background thread.
    flush() is called on collector stop — commit any buffered state.
    """

    @abstractmethod
    def write(self, sample: EnergySample) -> None:
        """
        Persist a single energy sample.
        MUST be thread safe — called from background sampling thread.
        MUST NOT raise — log and continue on any error (PAC-2).
        """
        ...

    @abstractmethod
    def flush(self) -> None:
        """
        Flush any buffered writes.
        Called on EnergyCollector.stop() after sampling thread joins.
        """
        ...
