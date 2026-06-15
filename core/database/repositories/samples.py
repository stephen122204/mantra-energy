#!/usr/bin/env python3
"""
================================================================================
SAMPLES REPOSITORY — Insert methods for all sample tables
================================================================================

Chunk 2 final: All insert methods store explicit sample_start_ns,
sample_end_ns, and interval_ns alongside backward-compat old columns.

Design principle (raw layer):
    Store everything explicitly at write time.
    Never compute at read time for large dataset ETL performance.
    timestamp_ns = sample_end_ns (kept for backward compat).

Tables:
    energy_samples    — 100Hz RAPL counter start/end per domain
    cpu_samples       — turbostat telemetry + interval
    interrupt_samples — /proc/stat interrupts + CPU ticks + interval
    thermal_samples   — 1Hz sensor readings + interval

Author: Deepak Panigrahy
================================================================================
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SamplesRepository:
    """
    Repository for all high-frequency sample table inserts.

    All methods accept list of dicts — callers do not manage column order.
    No transaction management — caller (experiment_runner.py) manages transactions.
    All new fields use dict.get() with no default — None stored if not provided,
    ensuring backward compat with old-format sample dicts.
    """

    def __init__(self, db):
        """
        Initialise with database connection wrapper.

        Args:
            db: Database adapter with .conn attribute (sqlite3 connection).
        """
        self.db = db

    # =========================================================================
    # ENERGY SAMPLES — 100Hz RAPL
    # =========================================================================

    def insert_energy_samples(
        self, run_id: int, samples: List[Dict[str, Any]]
    ) -> None:
        """
        Insert high-frequency RAPL energy samples.

        Stores raw counter values at sample start and end, plus explicit
        timestamps and computed delta fields for backward compatibility.

        Sample dict keys:
            timestamp_ns      — end timestamp in epoch ns (backward compat)
            sample_start_ns   — explicit start timestamp in epoch ns (new)
            sample_end_ns     — explicit end timestamp in epoch ns (new)
            interval_ns       — elapsed ns between start and end reads (new)
            pkg_start_uj      — RAPL package counter at start (new)
            pkg_end_uj        — RAPL package counter at end (new)
            core_start_uj     — RAPL core counter at start (new)
            core_end_uj       — RAPL core counter at end (new)
            dram_start_uj     — RAPL DRAM counter at start (new)
            dram_end_uj       — RAPL DRAM counter at end (new)
            uncore_start_uj   — RAPL uncore counter at start (new)
            uncore_end_uj     — RAPL uncore counter at end (new)
            pkg_energy_uj     — package delta (old, kept for compat)
            core_energy_uj    — core delta (old, kept for compat)
            uncore_energy_uj  — uncore delta (old, kept for compat)
            dram_energy_uj    — DRAM delta (old, kept for compat)

        Args:
            run_id:  Foreign key to runs table.
            samples: List of sample dicts from _sampling_loop.
        """
        if not samples:
            return

        query = """
            INSERT INTO energy_samples (
                run_id,
                timestamp_ns,
                sample_start_ns,
                sample_end_ns,
                interval_ns,
                pkg_start_uj,    pkg_end_uj,
                core_start_uj,   core_end_uj,
                dram_start_uj,   dram_end_uj,
                uncore_start_uj, uncore_end_uj,
                pkg_energy_uj,   core_energy_uj,
                uncore_energy_uj, dram_energy_uj,
                gpu_start_uj,    gpu_end_uj,
                gpu_energy_uj
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        for s in samples:
            self.db.conn.execute(
                query,
                (
                    run_id,
                    s.get("timestamp_ns"),       # backward compat = sample_end_ns
                    s.get("sample_start_ns"),     # explicit start
                    s.get("sample_end_ns"),       # explicit end
                    s.get("interval_ns"),         # end - start (stored explicitly)
                    s.get("pkg_start_uj"),
                    s.get("pkg_end_uj"),
                    s.get("core_start_uj"),
                    s.get("core_end_uj"),
                    s.get("dram_start_uj"),
                    s.get("dram_end_uj"),
                    s.get("uncore_start_uj"),
                    s.get("uncore_end_uj"),
                    s.get("pkg_energy_uj"),       # old delta — backward compat
                    s.get("core_energy_uj"),
                    s.get("uncore_energy_uj"),
                    s.get("dram_energy_uj"),
                    s.get("gpu_start_uj"),         # MSR 0x641 at sample start
                    s.get("gpu_end_uj"),            # MSR 0x641 at sample end
                    s.get("gpu_energy_uj"),         # delta * 61.0352 µJ
                ),
            )

    # =========================================================================
    # GPU SAMPLES — per-sample energy from GPUCollector (Chunk 15-A)
    # =========================================================================
    def insert_gpu_samples(self, run_id: int, samples) -> None:
        """
        Bulk INSERT gpu_samples for a completed run.
        samples: List[GpuSample] from GPUCollector.stop().
        Mirrors insert_energy_samples pattern exactly.
        GPUCollector is instantiated fresh per run so no dedup guard needed.
 
        Args:
            run_id:  Foreign key to runs table.
            samples: List of GpuSample objects from GPUCollector.stop().
        """
        if not samples:
            return
        query = """
            INSERT INTO gpu_samples (
                run_id,
                gpu_index,
                sample_start_ns,
                sample_end_ns,
                interval_ns,
                energy_start_uj,
                energy_end_uj,
                energy_uj,
                power_mw,
                util_gpu_pct,
                util_mem_pct,
                sm_clock_mhz,
                mem_clock_mhz,
                mem_used_mb,
                temperature_c,
                source
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """
        rows = [
            (
                run_id,
                s.gpu_index,
                s.sample_start_ns,
                s.sample_end_ns,
                s.interval_ns,
                s.energy_start_uj,
                s.energy_end_uj,
                s.energy_uj,
                s.power_mw,
                s.util_gpu_pct,
                s.util_mem_pct,
                s.sm_clock_mhz,
                s.mem_clock_mhz,
                s.mem_used_mb,
                s.temperature_c,
                s.source,
            )
            for s in samples
        ]
        self.db.conn.executemany(query, rows)
        logger.debug("insert_gpu_samples: %d rows for run_id=%d", len(rows), run_id)
        
    def insert_energy_samples_v2(self, run_id, samples):
        # type: (int, list) -> None
        """
        Insert normalized energy samples for new-schema platforms.
        Each sample carries source_id and a domains dict.
        Returns list of (local sample_id, EnergySampleV2) for domain insert.
        Called for GN100 (SPBM+DCGM), Apple (IOKit), AMD, TAMU, future.
        Legacy RAPL path uses insert_energy_samples() unchanged.
        """
        if not samples:
            return
        for s in samples:
            cur = self.db.conn.execute("""
                INSERT INTO energy_samples_v2
                    (run_id, source_id, timestamp_ns, interval_ns)
                VALUES (?, ?, ?, ?)
            """, (run_id, s.source_id, s.timestamp_ns, s.interval_ns))
            sample_id = cur.lastrowid
            # Insert one domain row per measured domain — absent domains not stored
            domain_rows = [
                (sample_id, run_id, domain_id, s.source_id, energy_uj)
                for domain_id, energy_uj in s.domains.items()
                if energy_uj is not None
            ]
            if domain_rows:
                self.db.conn.executemany("""
                    INSERT INTO energy_sample_domains
                        (sample_id, run_id, domain_id, source_id, energy_uj)
                    VALUES (?, ?, ?, ?, ?)
                """, domain_rows)
        logger.debug(
            "insert_energy_samples_v2: %d samples run_id=%d", len(samples), run_id
        )
 
    def insert_energy_derived_metrics(self, run_id, metrics):
        # type: (int, list) -> None
        """
        Insert ETL-computed derived metrics.
        metrics: list of dicts with keys:
            sample_id (nullable), metric_name, value_uj,
            derivation_formula, source_ids_used
        Never called during measurement — ETL only.
        """
        if not metrics:
            return
        rows = [(
            run_id,
            m.get('sample_id'),
            m['metric_name'],
            m.get('value_uj'),
            m['derivation_formula'],
            m['source_ids_used'],
        ) for m in metrics]
        self.db.conn.executemany("""
            INSERT INTO energy_derived_metrics
                (run_id, sample_id, metric_name, value_uj,
                 derivation_formula, source_ids_used)
            VALUES (?, ?, ?, ?, ?, ?)
        """, rows)
        logger.debug(
            "insert_energy_derived_metrics: %d rows run_id=%d", len(rows), run_id
        )
 
    def insert_device_telemetry(self, run_id, samples):
        # type: (int, list) -> None
        """
        Insert instantaneous device telemetry (power, temp, util, clock).
        Replaces gpu_samples for new platforms going forward.
        Legacy gpu_samples path unchanged.
        energy_uj nullable — NULL for SMI_INTEG (integrated at ETL).
        """
        if not samples:
            return
        rows = [(
            run_id,
            s.source_id,
            s.timestamp_ns,
            s.interval_ns,
            s.device_type,
            s.power_mw,
            s.energy_uj,
            s.util_pct,
            s.temp_c,
            s.clock_mhz,
            s.dc_input_mw,
            s.mem_util_pct,
        ) for s in samples]
        self.db.conn.executemany("""
            INSERT INTO device_telemetry (
                run_id, source_id, timestamp_ns, interval_ns,
                device_type, power_mw, energy_uj, util_pct,
                temp_c, clock_mhz, dc_input_mw, mem_util_pct
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        logger.debug(
            "insert_device_telemetry: %d rows run_id=%d", len(rows), run_id
        )
 
    def insert_platform_domain_relationships(self, hw_id, hardware_hash, rows):
        # type: (int, str, list) -> None
        """
        Seed platform topology for this machine.
        Called once per machine at first experiment run.
        Idempotent via INSERT OR IGNORE.
        rows: list of dicts with source_id, domain_id, parent_domain_id,
              contributes_to_parent.
        """
        if not rows:
            return
        data = [(
            hw_id,
            hardware_hash,
            r['source_id'],
            r['domain_id'],
            r.get('parent_domain_id'),
            r.get('contributes_to_parent', 1),
        ) for r in rows]
        self.db.conn.executemany("""
            INSERT OR IGNORE INTO platform_domain_relationships
                (hw_id, hardware_hash, source_id, domain_id,
                 parent_domain_id, contributes_to_parent)
            VALUES (?, ?, ?, ?, ?, ?)
        """, data)
        logger.debug(
            "insert_platform_domain_relationships: %d rows hw_id=%d",
            len(data), hw_id
        )
    # =========================================================================
    # CPU SAMPLES — turbostat telemetry
    # =========================================================================

    def insert_cpu_samples(
        self, run_id: int, samples: List[Dict[str, Any]]
    ) -> None:
        """
        Insert CPU telemetry samples from turbostat.

        Chunk 2: Adds sample_start_ns, sample_end_ns, interval_ns.
        All existing turbostat columns unchanged.

        Args:
            run_id:  Foreign key to runs table.
            samples: List of sample dicts from turbostat reader.
        """
        if not samples:
            return

        for s in samples:
            self.db.conn.execute(
                """
                INSERT INTO cpu_samples (
                    run_id, timestamp_ns,
                    sample_start_ns, sample_end_ns, interval_ns,
                    cpu_util_percent, cpu_busy_mhz, cpu_avg_mhz,
                    c1_residency, c2_residency, c3_residency,
                    c6_residency, c7_residency,
                    pkg_c8_residency, pkg_c9_residency, pkg_c10_residency,
                    package_power, dram_power,
                    gpu_rc6,
                    package_temp, ipc,
                    extra_metrics_json,
                    l1d_cache_misses, l2_cache_misses,l3_cache_hits, l3_cache_misses
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ? )
                """,
                (
                    run_id,
                    s.get("timestamp_ns"),
                    s.get("sample_start_ns"),
                    s.get("sample_end_ns"),
                    s.get("interval_ns"),
                    s.get("cpu_util_percent"),
                    s.get("cpu_busy_mhz"),
                    s.get("cpu_avg_mhz"),
                    s.get("c1_residency"),
                    s.get("c2_residency"),
                    s.get("c3_residency"),
                    s.get("c6_residency"),
                    s.get("c7_residency"),
                    s.get("pkg_c8_residency"),
                    s.get("pkg_c9_residency"),
                    s.get("pkg_c10_residency"),
                    s.get("package_power"),
                    s.get("dram_power"),
                    s.get("gpu_rc6"),
                    s.get("package_temp"),
                    s.get("ipc"),
                    s.get("extra_metrics_json"),
                    s.get("l1d_cache_misses"),
                    s.get("l2_cache_misses"),
                    s.get("l3_cache_hits"),
                    s.get("l3_cache_misses"),                    
                ),
            )
    # =========================================================================
    # IO SAMPLES — /proc/stat interrupts + CPU ticks
    # =========================================================================
    def insert_io_samples(self, run_id: int, samples: list) -> None:
        """Insert disk I/O samples from DiskReader."""
        if not samples:
            return
        query = """
            INSERT INTO io_samples (
                run_id, sample_start_ns, sample_end_ns, interval_ns,
                device, disk_read_bytes, disk_write_bytes,
                io_block_time_ms, disk_latency_ms,
                minor_page_faults, major_page_faults
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        for s in samples:
            self.db.conn.execute(query, (
                run_id,
                s.get("sample_start_ns"),
                s.get("sample_end_ns"),
                s.get("interval_ns"),
                s.get("device"),
                s.get("disk_read_bytes"),
                s.get("disk_write_bytes"),
                s.get("io_block_time_ms"),
                s.get("disk_latency_ms"),
                s.get("minor_page_faults"),
                s.get("major_page_faults"),
            ))

    # =========================================================================
    # INTERRUPT SAMPLES — /proc/stat interrupts + CPU ticks
    # =========================================================================

    def insert_interrupt_samples(
        self, run_id: int, samples: List[Dict[str, Any]]
    ) -> None:
        """
        Insert interrupt and CPU tick samples from /proc/stat.

        Chunk 2 (Option B): CPU tick columns stored here because
        scheduler_monitor reads /proc/stat for both interrupts and ticks
        in the same atomic call. Chunk 3 (ProcReader) will promote ticks
        to a dedicated proc_samples table.

        Sample dict keys:
            timestamp_ns        — end timestamp epoch ns (backward compat)
            sample_start_ns     — explicit start timestamp (new)
            sample_end_ns       — explicit end timestamp (new)
            interval_ns         — elapsed ns (new)
            interrupts_per_sec  — rate (old, kept for compat)
            interrupts_raw      — raw count delta (new)
            user_ticks_start    — /proc/stat user ticks at start (new)
            user_ticks_end      — /proc/stat user ticks at end (new)
            system_ticks_start  — /proc/stat system ticks at start (new)
            system_ticks_end    — /proc/stat system ticks at end (new)

        Args:
            run_id:  Foreign key to runs table.
            samples: List of sample dicts from scheduler_monitor.
        """
        if not samples:
            return

        query = """
            INSERT INTO interrupt_samples (
                run_id, timestamp_ns,
                sample_start_ns,    sample_end_ns,
                interval_ns,
                interrupts_per_sec,
                interrupts_raw,
                user_ticks_start,   user_ticks_end,
                system_ticks_start, system_ticks_end,
                total_ticks_start,  total_ticks_end,
                proc_ticks_start,   proc_ticks_end
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        for s in samples:
            self.db.conn.execute(
                query,
                (
                    run_id,
                    s.get("timestamp_ns"),          # backward compat
                    s.get("sample_start_ns"),
                    s.get("sample_end_ns"),
                    s.get("interval_ns"),
                    s.get("interrupts_per_sec"),     # old rate — backward compat
                    s.get("interrupts_raw"),
                    s.get("user_ticks_start"),
                    s.get("user_ticks_end"),
                    s.get("system_ticks_start"),
                    s.get("system_ticks_end"),
                    s.get("total_ticks_start"),
                    s.get("total_ticks_start"),
                    s.get("proc_ticks_start"),
                    s.get("proc_ticks_end"),
                ),
            )

    # =========================================================================
    # THERMAL SAMPLES — 1Hz sensor readings
    # =========================================================================

    def insert_thermal_samples(
        self, run_id: int, samples: List[Dict[str, Any]]
    ) -> None:
        """
        Insert 1Hz thermal telemetry samples.

        Chunk 2: Adds sample_start_ns, sample_end_ns, interval_ns.
        Fixes all_zones → all_zones_json (JSON serialisation at insert time).

        Args:
            run_id:  Foreign key to runs table.
            samples: List of sample dicts from _thermal_sampling_loop.
        """
        if not samples:
            return

        query = """
            INSERT INTO thermal_samples (
                run_id, timestamp_ns,
                sample_start_ns, sample_end_ns, interval_ns,
                sample_time_s,
                cpu_temp, system_temp, wifi_temp,
                throttle_event,
                all_zones_json,
                sensor_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        for s in samples:
            # Serialise all_zones dict to JSON at insert time
            # harness.py stores as 'all_zones' dict — convert here
            all_zones = s.get("all_zones_json") or s.get("all_zones")
            if isinstance(all_zones, dict):
                all_zones = json.dumps(all_zones)   # dict → JSON string

            self.db.conn.execute(
                query,
                (
                    run_id,
                    s.get("timestamp_ns"),
                    s.get("sample_start_ns"),
                    s.get("sample_end_ns"),
                    s.get("interval_ns"),
                    s.get("sample_time_s"),
                    s.get("cpu_temp"),
                    s.get("system_temp"),
                    s.get("wifi_temp"),
                    s.get("throttle_event", 0),
                    all_zones,
                    s.get("sensor_count"),
                ),
            )
