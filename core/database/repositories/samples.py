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
from typing import Any, Dict, List, Optional


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
                uncore_energy_uj, dram_energy_uj
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
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
