"""
core/readers/normalized_writer.py

NormalizedWriter — primary persistence adapter for all platforms.

Writes to normalized schema (v49-v60):
    energy_samples_v2     — sample header (run_id, timestamp_ns, source_id)
    energy_sample_domains — per-domain delta values

This is the long-term persistence path. LegacyWriter is transitional.
PAC-2: write() never raises — logs and continues on any error.
NFR DC-1: 30% inline comment coverage maintained.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional

from core.readers.energy_sample import EnergySample
from core.readers.persistence_adapter import PersistenceAdapter

logger = logging.getLogger(__name__)


class NormalizedWriter(PersistenceAdapter):
    """
    Writes EnergySample to energy_samples_v2 + energy_sample_domains.

    domain_id_cache maps canonical_name -> energy_domains.domain_id.
    Pre-resolved at startup from DB — no per-tick DB reads for lookup.
    source_id must match energy_sources.source_id for this reader.

    Thread safety: single lock per writer instance.
    """

    def __init__(
        self,
        source_id: int,                      # energy_sources.source_id for this reader
        domain_id_cache: Dict[str, int],     # canonical_name -> domain_id, pre-resolved
    ):
        self._source_id = source_id
        self._domain_id_cache = domain_id_cache   # used at flush to convert keys
        self.is_legacy = False               # router flag for EnergyCollector
        self._lock = threading.Lock()
        self._write_count = 0
        self._buffer: List[EnergySample] = []     # flushed after insert_run() assigns run_id

    def write(self, sample: EnergySample) -> None:
        """
        Insert sample header + one row per domain into normalized tables.
        PAC-2: logs warning and returns on any error, never raises.
        """
        try:
            with self._lock:
                # Buffer sample — run_id not available until insert_run()
                # Flushed via energy_engine.last_v2_samples after run_id assigned
                self._buffer.append(sample)
        except Exception as e:
            logger.warning("NormalizedWriter.write failed: %s", e)

    

    def flush(self) -> List:
        """
        Convert buffered EnergySamples to objects insert_energy_samples_v2() expects.
        Returns list of SimpleNamespace(source_id, timestamp_ns, interval_ns, domains)
        where domains keys are integer domain_ids not canonical names.
        Called by EnergyCollector.stop() — no DB access here.
        """
        from types import SimpleNamespace
        with self._lock:
            result = []
            for sample in self._buffer:
                # Convert canonical_name -> domain_id using pre-resolved cache
                domains = {}
                for canonical_name, delta_uj in sample.domains.items():
                    domain_id = self._domain_id_cache.get(canonical_name)
                    if domain_id is not None:
                        domains[domain_id] = delta_uj
                    else:
                        logger.warning(
                            "NormalizedWriter: unknown domain '%s' — "
                            "add to energy_domains table", canonical_name,
                        )
                if domains:
                    result.append(SimpleNamespace(
                        source_id=self._source_id,
                        timestamp_ns=sample.timestamp_ns,
                        interval_ns=sample.interval_ns,
                        domains=domains,
                    ))
            self._buffer.clear()
            logger.debug("NormalizedWriter.flush: %d samples ready", len(result))
            return result
