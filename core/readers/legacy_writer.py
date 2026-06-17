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

    def __init__(self):
        # No DB connection — buffered, returned at flush(), inserted by experiment_runner
        self.is_legacy = True                # router flag for EnergyCollector
        self._lock = threading.Lock()
        self._buffer: List[Dict] = []        # accumulated sample dicts

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
            # Raw counter values from EnergyCollector tick — needed by ETL
            # for pre_task_energy_uj, framework_overhead_energy_uj attribution
            row["pkg_start_uj"]    = sample.raw_start.get("package-0")
            row["pkg_end_uj"]      = sample.raw_end.get("package-0")
            row["core_start_uj"]   = sample.raw_start.get("core")
            row["core_end_uj"]     = sample.raw_end.get("core")
            row["dram_start_uj"]   = sample.raw_start.get("dram")
            row["dram_end_uj"]     = sample.raw_end.get("dram")
            row["uncore_start_uj"] = sample.raw_start.get("uncore")
            row["uncore_end_uj"]   = sample.raw_end.get("uncore")

            with self._lock:
                self._buffer.append(row)

        except Exception as e:
            logger.warning("LegacyWriter.write failed: %s", e)

    def flush(self) -> List[Dict]:
        """
        Return buffered legacy rows for insert_energy_samples() in experiment_runner.
        No DB access here — follows gpu_collector pattern.
        """
        with self._lock:
            result = list(self._buffer)
            self._buffer.clear()
            logger.debug("LegacyWriter.flush: returning %d rows", len(result))
            return result
