#!/usr/bin/env python3
"""
================================================================================
METHODOLOGY REPOSITORY — Provenance & Method Registry DB Operations
================================================================================

Purpose:
    All DB reads and writes for the three methodology tables:
        measurement_method_registry  — static method definitions (seeded once)
        method_references            — paper/standard citations per method
        measurement_methodology      — runtime provenance per metric per run

    Follows the same repository pattern as samples.py and thermal.py.
    DatabaseManager is the only caller — never use this class directly.

Tables owned by this repository:
    measurement_method_registry
    method_references
    measurement_methodology

Author: Deepak Panigrahy
================================================================================
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MethodologyRepository:
    """
    Repository for all methodology provenance operations.

    Injected with a database adapter at construction — no connection
    management here, that belongs to the adapter layer.

    Usage (via DatabaseManager only):
        db.methodology.insert_method_registry(...)
        db.methodology.flush_provenance_buffer(run_id, buffer)
    """

    def __init__(self, db) -> None:
        """
        Initialise with a database adapter.

        Args:
            db: DatabaseInterface adapter (SQLiteAdapter or compatible).
        """
        self.db = db

    # =========================================================================
    # measurement_method_registry — static seed-time operations
    # =========================================================================

    def upsert_method_registry(self, method: Dict[str, Any]) -> None:
        """
        Insert or replace one row in measurement_method_registry.

        Called by seed_methodology.py at deploy time.
        Uses INSERT OR REPLACE so re-seeding is always safe (idempotent).

        Args:
            method: Dict with keys matching registry columns.
                    Required: id, name, provenance, layer
                    Optional: all other columns (default to NULL / schema default)
        """
        # Build params tuple in column order — explicit is safer than **kwargs
        params = (
            method["id"],
            method.get("name", ""),
            method.get("version", "1.0"),
            method.get("description", ""),
            method.get("formula_latex", ""),
            method.get("code_snapshot", ""),
            method.get("code_language", "python"),
            method.get("code_version", ""),
            method.get("parameters", "{}"),
            method.get("output_metric", ""),
            method.get("output_unit", ""),
            method.get("provenance", "MEASURED"),
            method.get("layer", "silicon"),
            method.get("applicable_on", '["any"]'),
            method.get("fallback_method_id"),
            method.get("validated", 0),
            method.get("validated_by"),
            method.get("validated_date"),
            method.get("active", 1),
            method.get("deprecated_reason"),
            method.get("confidence", 1.0),
        )

        self.db.execute("""
            INSERT OR REPLACE INTO measurement_method_registry (
                id, name, version, description, formula_latex,
                code_snapshot, code_language, code_version,
                parameters, output_metric, output_unit,
                provenance, layer, applicable_on, fallback_method_id,
                validated, validated_by, validated_date,
                active, deprecated_reason,confidence,
                updated_at
            ) VALUES (
                ?,?,?,?,?,
                ?,?,?,
                ?,?,?,
                ?,?,?,?,
                ?,?,?,
                ?,?,?,
                unixepoch()
            )
        """, params)

        logger.debug("Upserted method registry: %s", method["id"])

    def get_method_registry(self, method_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a single method registry row by ID.

        Args:
            method_id: Registry primary key e.g. 'rapl_msr_pkg_energy'

        Returns:
            Dict of row values, or None if not found.
        """
        rows = self.db.execute(
            "SELECT * FROM measurement_method_registry WHERE id = ?",
            (method_id,)
        )
        return rows[0] if rows else None

    def list_method_registry(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """
        Return all method registry rows.

        Args:
            active_only: If True, exclude deprecated/inactive methods.

        Returns:
            List of dicts, one per registered method.
        """
        # Filter by active flag when requested — guard clause style
        where = "WHERE active = 1" if active_only else ""
        return self.db.execute(
            f"SELECT * FROM measurement_method_registry {where} ORDER BY layer, id"
        )

    # =========================================================================
    # method_references — citation rows per method
    # =========================================================================

    def insert_references(self, method_id: str, references: List[Dict]) -> None:
        """
        Insert citation rows for one method.

        Clears existing references for the method before inserting so that
        re-seeding always produces a clean, consistent state.

        Args:
            method_id: FK to measurement_method_registry.id
            references: List of reference dicts from METHOD_REFERENCES attribute.
        """
        # Remove stale references before re-inserting (idempotent re-seed)
        self.db.execute(
            "DELETE FROM method_references WHERE method_id = ?",
            (method_id,)
        )

        for ref in references:
            self.db.execute("""
                INSERT INTO method_references (
                    method_id, ref_type, title, authors, year,
                    venue, doi, url, relevance, cited_text, page_or_section
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                method_id,
                ref.get("ref_type", "paper"),
                ref.get("title", ""),
                ref.get("authors"),
                ref.get("year"),
                ref.get("venue"),
                ref.get("doi"),
                ref.get("url"),
                ref.get("relevance"),
                ref.get("cited_text"),
                ref.get("page_or_section"),
            ))

        logger.debug("Inserted %d references for method: %s", len(references), method_id)

    def get_references(self, method_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all citation rows for one method.

        Args:
            method_id: FK to measurement_method_registry.id

        Returns:
            List of reference dicts ordered by year descending.
        """
        return self.db.execute(
            "SELECT * FROM method_references WHERE method_id = ? ORDER BY year DESC",
            (method_id,)
        )

    # =========================================================================
    # measurement_methodology — runtime provenance per metric per run
    # =========================================================================

    def insert_provenance(self, entry: Dict[str, Any]) -> None:
        """
        Insert one provenance record for a metric within a run.

        Called by flush_provenance_buffer() after run_id is known.
        One row per metric per run.

        Args:
            entry: Provenance dict with keys:
                run_id, metric_id, method_id, value_raw, value_unit,
                provenance, hw_available, confidence,
                primary_method_failed, failure_reason, parameters_used
        """
        self.db.execute("""
            INSERT INTO measurement_methodology (
                run_id, metric_id, method_id,
                parameters_used, value_raw, value_unit,
                provenance, hw_available, confidence,
                primary_method_failed, failure_reason,
                captured_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,unixepoch())
        """, (
            entry["run_id"],
            entry["metric_id"],
            entry.get("method_id"),
            # Serialise parameters dict to JSON string for storage
            json.dumps(entry.get("parameters_used", {})),
            entry.get("value_raw"),
            entry.get("value_unit", "µJ"),
            entry.get("provenance", "MEASURED"),
            entry.get("hw_available", 1),
            entry.get("confidence", 1.0),
            entry.get("primary_method_failed", 0),
            entry.get("failure_reason"),
        ))

    def flush_provenance_buffer(
        self, run_id: int, buffer: List[Dict[str, Any]]
    ) -> None:
        """
        Flush all pending provenance entries from buffer into DB.

        Called by experiment_runner once run_id is known.
        Injects run_id into each buffered entry before insert.

        Args:
            run_id:  The DB run ID just created by insert_run()
            buffer:  List of pending capture dicts (without run_id)
        """
        # Guard — nothing to flush
        if not buffer:
            return

        for entry in buffer:
            # Inject run_id — was unknown when entry was captured
            entry["run_id"] = run_id
            self.insert_provenance(entry)

        logger.debug(
            "Flushed %d provenance entries for run_id=%d",
            len(buffer), run_id
        )

    def get_provenance_for_run(self, run_id: int) -> List[Dict[str, Any]]:
        """
        Retrieve full provenance chain for one run.

        Joins methodology rows with registry for human-readable output.
        Used by report engine and audit queries.

        Args:
            run_id: DB run ID to query.

        Returns:
            List of dicts with both runtime values and method definitions.
        """
        return self.db.execute("""
            SELECT
                mm.run_id,
                mm.metric_id,
                mm.method_id,
                mm.value_raw,
                mm.value_unit,
                mm.provenance,
                mm.confidence,
                mm.parameters_used,
                mm.primary_method_failed,
                mm.failure_reason,
                mm.captured_at,
                mmr.name        AS method_name,
                mmr.description AS method_description,
                mmr.formula_latex,
                mmr.layer
            FROM measurement_methodology mm
            LEFT JOIN measurement_method_registry mmr
                ON mm.method_id = mmr.id
            WHERE mm.run_id = ?
            ORDER BY mm.captured_at
        """, (run_id,))
