#!/usr/bin/env python3
"""
================================================================================
EVENTS REPOSITORY – Handles orchestration events insertion
================================================================================

PURPOSE:
    Contains logic for inserting orchestration events (phase-level attribution)
    into the database.

WHY THIS EXISTS:
    - Separates event insertion from other database operations
    - Makes it easy to modify event schema independently
    - Part of splitting the god object manager.py

AUTHOR: Deepak Panigrahy
================================================================================
"""

from typing import Any, Dict, List

from ..base import DatabaseInterface


class EventsRepository:
    """
    Repository for orchestration events.

    Handles insertion of phase-level events for agentic runs.
    """

    def __init__(self, db: DatabaseInterface):
        """
        Initialize with database adapter.

        Args:
            db: DatabaseInterface instance
        """
        self.db = db

    def insert_events(self, run_id: int, events: List[Dict[str, Any]]) -> None:
        """
        Insert orchestration events for a run.

        Args:
            run_id: Foreign key to runs table
            events: List of event dictionaries
        """
        if not events:
            return

        query = """
            INSERT INTO orchestration_events
            (run_id, step_index, phase, event_type, start_time_ns, end_time_ns,
             duration_ns, power_watts, cpu_util_percent, interrupt_rate,
             event_energy_uj, tax_contribution_uj, tax_percent,
             tool_name, io_bytes_read, io_bytes_written,
             input_payload_hash, output_payload_hash,
             tool_success, tool_result_rows,
             tool_cpu_time_ns, tool_memory_delta_kb)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        # No transaction wrapper - caller manages transactions
        for ev in events:
            meta = ev.get("metadata", {})
            self.db.conn.execute(
                query,
                (
                    run_id,
                    ev.get("step_index"),
                    ev.get("phase"),
                    ev.get("event_type"),
                    ev.get("start_time_ns"),
                    ev.get("end_time_ns"),
                    ev.get("duration_ns"),
                    ev.get("power_watts"),
                    ev.get("cpu_util_percent"),
                    ev.get("interrupt_rate"),
                    ev.get("event_energy_uj"),
                    ev.get("tax_contribution_uj"),
                    ev.get("tax_percent"),
                    meta.get("tool_name"),
                    meta.get("io_bytes_read"),
                    meta.get("io_bytes_written"),
                    meta.get("input_payload_hash"),
                    meta.get("output_payload_hash"),
                    (None if meta.get("success") is None else int(meta.get("success"))),
                    meta.get("result_rows"),
                    meta.get("cpu_time_ns"),
                    meta.get("memory_delta_kb"),
                ),
            )
