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
from typing import Dict, Optional

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
        db_manager,                          # ALEMSDatabase manager instance
        source_id: int,                      # energy_sources.source_id for this reader
        domain_id_cache: Dict[str, int],     # canonical_name -> domain_id
    ):
        self._db = db_manager
        self._source_id = source_id          # stored per write — identifies measurement interface
        self._domain_id_cache = domain_id_cache
        self._lock = threading.Lock()        # serialize writes from background thread
        self._write_count = 0                # diagnostic counter

    def write(self, sample: EnergySample) -> None:
        """
        Insert sample header + one row per domain into normalized tables.
        PAC-2: logs warning and returns on any error, never raises.
        """
        try:
            with self._lock:
                # Insert sample header — returns new sample_id
                sample_id = self._insert_header(sample)
                if sample_id is None:
                    return  # header insert failed, skip domain rows

                # Insert one domain row per measured domain
                for canonical_name, delta_uj in sample.domains.items():
                    domain_id = self._domain_id_cache.get(canonical_name)
                    if domain_id is None:
                        # Domain not in registry — log once, skip silently
                        logger.warning(
                            "NormalizedWriter: unknown canonical domain '%s' — "
                            "add to energy_domains table",
                            canonical_name,
                        )
                        continue
                    self._insert_domain_row(
                        sample_id, domain_id, delta_uj, sample.run_id
                    )

                self._write_count += 1

        except Exception as e:
            # PAC-2: never crash the sampling thread
            logger.warning("NormalizedWriter.write failed: %s", e)

    def _insert_header(self, sample: EnergySample) -> Optional[int]:
        """Insert energy_samples_v2 header row, return sample_id."""
        try:
            conn = self._db.conn
            cur = conn.execute(
                """INSERT INTO energy_samples_v2
                   (run_id, source_id, timestamp_ns, interval_ns)
                   VALUES (?, ?, ?, ?)""",
                (
                    sample.run_id,
                    self._source_id,
                    sample.timestamp_ns,
                    sample.interval_ns,
                ),
            )
            return cur.lastrowid
        except Exception as e:
            logger.warning("NormalizedWriter._insert_header failed: %s", e)
            return None

    def _insert_domain_row(
        self,
        sample_id: int,
        domain_id: int,
        energy_uj: int,
        run_id: int,
    ) -> None:
        """Insert one energy_sample_domains row for this domain."""
        try:
            self._db.conn.execute(
                """INSERT INTO energy_sample_domains
                   (sample_id, domain_id, source_id, energy_uj, run_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (sample_id, domain_id, self._source_id, energy_uj, run_id),
            )
        except Exception as e:
            logger.warning("NormalizedWriter._insert_domain_row failed: %s", e)

    def flush(self) -> None:
        """Commit pending writes. Called on EnergyCollector.stop()."""
        try:
            self._db.conn.commit()
            logger.debug(
                "NormalizedWriter.flush: committed %d samples", self._write_count
            )
        except Exception as e:
            logger.warning("NormalizedWriter.flush failed: %s", e)
