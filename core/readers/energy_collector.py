"""
core/readers/energy_collector.py

EnergyCollector — generic energy collection loop for any hardware platform.

Replaces BOTH _sampling_loop in energy_engine.py AND SPBMSampler in
spbm_energy_reader.py. One implementation, all platforms, forever.

Design: ports and adapters.
    Port:    EnergyReaderABC (hardware reading interface)
    Schema:  MeasurementSchema (declarative platform capabilities)
    Sample:  EnergySample (canonical in-memory measurement)
    Adapter: PersistenceAdapter (storage interface)

CRITICAL: This class MUST NOT contain any platform-specific branching.
If you find yourself writing 'if source == "RAPL"' in this class, STOP.
That logic belongs in the reader (get_measurement_schema) or in an adapter.

The only semantic branch allowed is domain_type (ENERGY_COUNTER vs POWER_RAIL)
which is a physical measurement type, not a platform identity.

PAC-2 compliant: sampling thread errors logged and continued, never crash.
NFR DC-1: 30% inline comment coverage maintained throughout.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional, TYPE_CHECKING

from core.readers.energy_sample import EnergySample
from core.readers.measurement_schema import (
    DomainDescriptor,
    MeasurementSchema,
    ENERGY_COUNTER,
    POWER_RAIL,
)
from core.readers.persistence_adapter import PersistenceAdapter

if TYPE_CHECKING:
    from core.readers.interfaces import EnergyReaderABC

logger = logging.getLogger(__name__)


class EnergyCollector:
    """
    Generic energy collection loop for any hardware platform.

    Reads energy counters at the rate specified by MeasurementSchema.sampling_hz.
    Computes deltas per tick with counter wraparound correction.
    Emits EnergySample objects to all registered PersistenceAdapters.

    Usage:
        collector = EnergyCollector(reader, adapters, run_id, source_id)
        collector.start()
        # ... experiment runs ...
        collector.stop()
    """

    def __init__(
        self,
        reader,                              # EnergyReaderABC implementation
        adapters: List[PersistenceAdapter],  # registered persistence adapters
        run_id: int,                         # active run — set before start()
        source_id: int,                      # energy_sources.source_id for this reader
    ):
        self._reader = reader
        self._adapters = adapters
        self._run_id = run_id
        self._source_id = source_id

        # Cache schema from reader — called once, never again
        self._schema: MeasurementSchema = reader.get_measurement_schema()

        # Build native_key -> DomainDescriptor lookup for fast per-tick access
        self._domain_map: Dict[str, DomainDescriptor] = {
            d.native_key: d for d in self._schema.domains
        }

        # Wraparound ceiling: 2^counter_width_bits µJ
        self._wrap_max: int = (1 << self._schema.counter_width_bits)

        # Sampling state
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._prev: Optional[Dict[str, Optional[int]]] = None  # previous tick readings

        logger.debug(
            "EnergyCollector init: source=%s domains=%d hz=%d wrap_bits=%d",
            self._schema.source,
            len(self._schema.domains),
            self._schema.sampling_hz,
            self._schema.counter_width_bits,
        )

    def start(self) -> None:
        """
        Read initial counter values and start background sampling thread.
        Initial read establishes the baseline for first delta computation.
        """
        if not self._schema.domains:
            # Empty schema (DummyReader etc) — no-op, nothing to collect
            logger.debug(
                "EnergyCollector.start: empty schema for %s — no-op",
                self._schema.source,
            )
            return

        # Baseline read before thread starts — prevents first-tick spike
        self._prev = self._reader.read_energy()
        self._running = True

        interval_s = 1.0 / self._schema.sampling_hz  # seconds between ticks

        self._thread = threading.Thread(
            target=self._loop,
            args=(interval_s,),
            daemon=True,
            name=f"EnergyCollector-{self._schema.source}",
        )
        self._thread.start()
        logger.info(
            "EnergyCollector started: source=%s hz=%d",
            self._schema.source, self._schema.sampling_hz,
        )

    def stop(self) -> None:
        """
        Stop background sampling, join thread, flush all adapters.
        Flush must happen AFTER thread joins to avoid concurrent writes.
        """
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        # Flush all adapters — both return buffered sample lists, no DB writes
        # Route by is_legacy flag — avoids circular import of writer classes
        self._flushed_v2_samples: List = []
        self._flushed_legacy_samples: List = []
        for adapter in self._adapters:
            try:
                result = adapter.flush()
                if isinstance(result, list):
                    if getattr(adapter, "is_legacy", False):
                        self._flushed_legacy_samples.extend(result)
                    else:
                        self._flushed_v2_samples.extend(result)
            except Exception as e:
                logger.warning("EnergyCollector: adapter flush failed: %s", e)

        logger.info(
            "EnergyCollector stopped: source=%s", self._schema.source
        )

    def _loop(self, interval_s: float) -> None:
        """
        Core sampling loop. Platform-agnostic. Iterates schema domains only.

        This method MUST contain zero platform-specific branching.
        All platform differences are expressed through MeasurementSchema.
        """
        next_tick = time.monotonic() + interval_s

        while self._running:
            # Sleep until next scheduled tick
            now = time.monotonic()
            sleep_s = next_tick - now
            if sleep_s > 0:
                time.sleep(sleep_s)
            next_tick += interval_s

            try:
                tick_start_ns = time.time_ns()
                curr = self._reader.read_energy()  # native key dict
                tick_end_ns = time.time_ns()
                # interval_ns = time since last tick, not read() duration
                # read() takes ~0.3ms but scheduled interval is 1/hz seconds
                interval_ns = int(interval_s * 1_000_000_000)

                # Build canonical domain dict from this tick
                domains: Dict[str, int] = {}

                for native_key, descriptor in self._domain_map.items():
                    c = curr.get(native_key)      # current counter value
                    p = self._prev.get(native_key) if self._prev else None

                    if descriptor.domain_type == ENERGY_COUNTER:
                        # Cumulative counter: compute delta with wraparound correction
                        if c is not None and p is not None:
                            delta = c - p
                            if delta < 0:
                                # Counter wrapped around: add wrap ceiling
                                delta += self._wrap_max
                            domains[descriptor.canonical_name] = delta
                        # If either is None: domain unavailable this tick, skip silently
                        # Never substitute zero — absent means not measured

                    elif descriptor.domain_type == POWER_RAIL:
                        # Instantaneous reading: store raw value, no delta
                        if c is not None:
                            domains[descriptor.canonical_name] = c

                # Emit canonical sample to all registered adapters
                if domains:
                    sample = EnergySample(
                        timestamp_ns=tick_end_ns,
                        interval_ns=interval_ns,
                        source=self._schema.source,
                        run_id=self._run_id,
                        domains=domains,
                        raw_start=dict(self._prev) if self._prev else {},
                        raw_end=dict(curr) if curr else {},
                    )
                    for adapter in self._adapters:
                        adapter.write(sample)   # PAC-2: adapter.write never raises

                self._prev = curr   # advance baseline for next delta

            except Exception as e:
                # PAC-2: never crash the sampling thread
                logger.error("EnergyCollector._loop error: %s", e)
                time.sleep(0.01)    # brief pause to avoid tight error loop

    @property
    def schema(self) -> MeasurementSchema:
        """Expose schema for inspection by energy_engine diagnostics."""
        return self._schema
