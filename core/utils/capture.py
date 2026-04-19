#!/usr/bin/env python3
"""
================================================================================
CAPTURE — Two-Phase Provenance Capture Helper
================================================================================

Purpose:
    Records formula, inputs, source, and confidence for any metric at runtime.
    Penetrates every layer of the stack — readers, analyzer, harness, LLM callers.

Two-Phase Design:
    Phase 1 — capture_pending():
        Called deep in readers where run_id is not yet known.
        Appends a pending entry to a buffer (list) owned by the caller.
        No DB write happens here.

    Phase 2 — flush_provenance():
        Called by experiment_runner once insert_run() returns a real run_id.
        Injects run_id into every buffered entry and writes to DB via manager.

Why Two Phases:
    Readers (RAPLReader, EnergyEstimator etc.) are instantiated before
    any experiment run exists in the DB. They have no run_id. Attempting
    to write provenance at read time would require passing run_id through
    EnergyEngine → ReaderFactory → every reader call — coupling that
    violates the architecture rules.

    The buffer pattern keeps readers clean and DB writes centralised.

Usage:
    # Phase 1 — inside a reader or analyzer (no run_id yet)
    from core.utils.capture import capture_pending

    capture_pending(
        buffer       = self._provenance_buffer,   # list on the engine/harness
        metric_id    = "pkg_energy_uj",
        method_id    = self.get_method_id(),
        value_raw    = pkg_uj,
        provenance   = "MEASURED",
        confidence   = self.get_confidence(),
        parameters   = {"domain": "package-0", "msr": "0x611"},
        value_unit   = "µJ",
    )

    # Phase 2 — inside experiment_runner after insert_run()
    from core.utils.capture import flush_provenance

    run_id = db.insert_run(exp_id, hw_id, result)
    flush_provenance(db, run_id, engine._provenance_buffer)

Author: Deepak Panigrahy
================================================================================
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def capture_pending(
    buffer: List[Dict[str, Any]],
    metric_id: str,
    method_id: str,
    value_raw: Optional[float],
    provenance: str,
    confidence: float,
    parameters: Optional[Dict[str, Any]] = None,
    value_unit: str = "µJ",
    hw_available: int = 1,
    primary_method_failed: int = 0,
    failure_reason: Optional[str] = None,
) -> None:
    """
    Stage a provenance entry in the caller's buffer (Phase 1).

    No DB write occurs here. Entry is held until flush_provenance()
    is called with a real run_id by experiment_runner.

    Args:
        buffer:                List owned by EnergyEngine or harness.
                               Entries accumulate until flush.
        metric_id:             e.g. 'pkg_energy_uj', 'ipc', 'ttft_ms'
        method_id:             FK to measurement_method_registry.id
        value_raw:             Numeric value at time of capture.
        provenance:            'MEASURED' | 'CALCULATED' | 'INFERRED'
        confidence:            0.0 (stub) → 1.0 (real hardware)
        parameters:            Actual runtime parameters used for this capture.
        value_unit:            Unit string for display e.g. 'µJ', 'ms', 'ratio'
        hw_available:          1 if hardware was accessible, 0 if fell back.
        primary_method_failed: 1 if primary reader failed and fallback was used.
        failure_reason:        Error message if primary_method_failed == 1.
    """
    entry = {
        # run_id intentionally absent — injected at flush time
        "metric_id":             metric_id,
        "method_id":             method_id,
        "value_raw":             value_raw,
        "value_unit":            value_unit,
        "provenance":            provenance,
        "confidence":            confidence,
        "parameters_used":       parameters or {},
        "hw_available":          hw_available,
        "primary_method_failed": primary_method_failed,
        "failure_reason":        failure_reason,
    }

    buffer.append(entry)

    logger.debug(
        "capture_pending: metric=%s method=%s value=%s confidence=%.2f",
        metric_id, method_id, value_raw, confidence,
    )


def flush_provenance(
    db,
    run_id: int,
    buffer: List[Dict[str, Any]],
) -> None:
    """
    Flush all pending provenance entries to DB (Phase 2).

    Called by experiment_runner immediately after insert_run() returns
    a real run_id. Delegates to MethodologyRepository.

    Clears the buffer after flushing so it can be reused for the next run.

    Args:
        db:      DatabaseManager instance with methodology repository wired.
        run_id:  The DB run ID just created by insert_run().
        buffer:  List of pending capture dicts from Phase 1.
    """
    # Guard — nothing to flush, skip DB call entirely
    if not buffer:
        logger.debug("flush_provenance: empty buffer for run_id=%d, skipping", run_id)
        return

    # Delegate to repository — it injects run_id and writes rows
    db.methodology.flush_provenance_buffer(run_id, buffer)

    logger.info(
        "flush_provenance: wrote %d provenance entries for run_id=%d",
        len(buffer), run_id,
    )

    # Clear buffer so engine/harness is clean for next run
    buffer.clear()
