"""
core/readers/legacy_writer.py

LegacyWriter — transitional persistence adapter for backward compatibility.

Maps canonical EnergySample domains to legacy energy_samples table columns
(pkg_energy_uj, core_energy_uj, uncore_energy_uj, dram_energy_uj).

Only activated for RAPL platforms during transition period.
Remove this adapter when all downstream consumers use v_energy view exclusively.

PAC-2: write() never raises.
NFR DC-1: 30% inline comment coverage maintained.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Dict, List

from core.readers.energy_sample import EnergySample
from core.readers.persistence_adapter import PersistenceAdapter

logger = logging.getLogger(__name__)

# Static mapping: canonical domain name -> legacy energy_samples column
# Only domains that have legacy columns are listed here.
# Domains absent from this map (CPU_P, CPU_E, GPU_APPLE etc) are silently
# skipped — they exist only in the normalized path. This is correct.
CANONICAL_TO_LEGACY: Dict[str, str] = {
    "PACKAGE": "pkg_energy_uj",
    "CORE":    "core_energy_uj",
    "UNCORE":  "uncore_energy_uj",
    "DRAM":    "dram_energy_uj",
}


class LegacyWriter(PersistenceAdapter):
    """
    Accumulates EnergySample domain deltas and writes to legacy energy_samples table.

    Buffer approach: accumulate per-tick samples in memory, batch insert
    on flush() to reduce per-tick DB overhead at 100 Hz.

    run_id is set at construction — one LegacyWriter per run.
    Thread safety: lock protects the accumulated buffer.
    """

    def __init__(self, db_manager, run_id: int):
        self._db = db_manager
        self._run_id = run_id                # fixed for the lifetime of this writer
        self._lock = threading.Lock()
        self._buffer: List[Dict] = []        # accumulated sample dicts, flushed in batch

    def write(self, sample: EnergySample) -> None:
        """
        Build legacy sample dict from EnergySample and buffer it.
        PAC-2: logs warning and returns on any error, never raises.
        """
        try:
            row = {
                "timestamp_ns":    sample.timestamp_ns,
                "sample_start_ns": sample.timestamp_ns - sample.interval_ns,
                "sample_end_ns":   sample.timestamp_ns,
                "interval_ns":     sample.interval_ns,
            }

            # Map canonical domains to legacy column names
            # Domains not in CANONICAL_TO_LEGACY are silently skipped
            for canonical_name, legacy_col in CANONICAL_TO_LEGACY.items():
                row[legacy_col] = sample.domains.get(canonical_name, 0)

            # Also populate start/end raw fields for backward compat ETL
            row["pkg_start_uj"]    = 0   # not available from delta-only EnergySample
            row["pkg_end_uj"]      = 0   # legacy ETL uses delta fields, not start/end
            row["core_start_uj"]   = 0
            row["core_end_uj"]     = 0
            row["dram_start_uj"]   = 0
            row["dram_end_uj"]     = 0
            row["uncore_start_uj"] = 0
            row["uncore_end_uj"]   = 0

            with self._lock:
                self._buffer.append(row)

        except Exception as e:
            logger.warning("LegacyWriter.write failed: %s", e)

    def flush(self) -> None:
        """
        Batch insert buffered samples into legacy energy_samples table.
        Called on EnergyCollector.stop() after sampling thread joins.
        """
        with self._lock:
            if not self._buffer:
                return
            try:
                # Use existing insert_energy_samples repository method
                self._db.insert_energy_samples(self._run_id, self._buffer)
                logger.debug(
                    "LegacyWriter.flush: inserted %d rows for run %d",
                    len(self._buffer), self._run_id,
                )
                self._buffer.clear()
            except Exception as e:
                logger.warning("LegacyWriter.flush failed: %s", e)
