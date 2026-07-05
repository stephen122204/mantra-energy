-- Migration 029: tool_failure_events
-- Chunk 8.4 | Schema Revision: 029
-- Also fixes hallucination_events.wasted_energy_uj INTEGER → REAL (platform energy consistency rule)
--
-- SQLite does not support ALTER COLUMN TYPE.
-- Fix strategy: add wasted_energy_uj_real REAL alongside INTEGER column.
-- ETL writes to wasted_energy_uj_real. Views read wasted_energy_uj_real.
-- INTEGER column retained for backward compatibility (SC-5).

PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────
-- FIX: hallucination_events.wasted_energy_uj precision
-- Platform rule: all wasted_energy_uj columns must be REAL
-- Original column was created as INTEGER in migration 028
-- ─────────────────────────────────────────────
ALTER TABLE hallucination_events
    ADD COLUMN wasted_energy_uj_real REAL;

-- ─────────────────────────────────────────────
-- TABLE: tool_failure_events
-- One row per failed tool call within one attempt.
-- wasted_energy_uj: energy consumed by this failed call.
--   = orchestration_events.event_energy_uj if orchestration_event_id is set
--   = INFERRED from attempt energy fraction otherwise
-- Populated by energy_attribution_etl.py (extended in 8.4).
-- failure_phase: where in orchestration pipeline the failure occurred.
--   Enables future papers to answer: "where in pipeline is energy wasted?"
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tool_failure_events (
    failure_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id              INTEGER NOT NULL,
    goal_id                 INTEGER NOT NULL,

    -- Link to the specific orchestration event that failed (nullable)
    orchestration_event_id  INTEGER,

    tool_name               TEXT NOT NULL,
    failure_type            TEXT NOT NULL
                            CHECK(failure_type IN (
                                'timeout','api_error','malformed_input',
                                'malformed_output','rate_limit',
                                'auth_error','not_found','other'
                            )),
    -- Where in the orchestration pipeline the failure occurred
    failure_phase           TEXT
                            CHECK(failure_phase IS NULL OR failure_phase IN (
                                'selection','execution','parsing','post_processing'
                            )),
    error_message           TEXT,

    -- Recovery tracking
    retry_attempted         INTEGER NOT NULL DEFAULT 0,
    retry_success           INTEGER NOT NULL DEFAULT 0,
    recovery_strategy       TEXT
                            CHECK(recovery_strategy IS NULL OR recovery_strategy IN (
                                'immediate_retry','backoff_retry',
                                'fallback_tool','skip','abort'
                            )),

    -- Energy wasted on this failed call — REAL for platform consistency
    -- NULL at insert, populated by energy_attribution_etl.py
    wasted_energy_uj        REAL,

    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (attempt_id)             REFERENCES goal_attempt(attempt_id),
    FOREIGN KEY (goal_id)                REFERENCES goal_execution(goal_id),
    FOREIGN KEY (orchestration_event_id) REFERENCES orchestration_events(event_id)
);

CREATE INDEX IF NOT EXISTS idx_tool_fail_attempt
    ON tool_failure_events(attempt_id);
CREATE INDEX IF NOT EXISTS idx_tool_fail_goal
    ON tool_failure_events(goal_id);
CREATE INDEX IF NOT EXISTS idx_tool_fail_tool
    ON tool_failure_events(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_fail_type
    ON tool_failure_events(failure_type);
CREATE INDEX IF NOT EXISTS idx_tool_fail_phase
    ON tool_failure_events(failure_phase);
CREATE INDEX IF NOT EXISTS idx_tool_fail_orch_event
    ON tool_failure_events(orchestration_event_id);
CREATE INDEX IF NOT EXISTS idx_tool_fail_attempt_type
    ON tool_failure_events(attempt_id, failure_type);
