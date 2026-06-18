-- =============================================================================
-- MIGRATION v064: Comprehensive schema sync — GN100 to UBUNTU2505 baseline
-- =============================================================================
-- Generated: 2026-06-18
-- Method: PRAGMA table_info diff across all tables on both machines
-- Covers: 13 missing columns across 9 tables
--
-- This migration makes GN100 schema identical to UBUNTU2505.
-- After this migration, schema.py must also be updated so fresh
-- checkouts never require this delta again (MSC-1).
--
-- Also includes v063 columns (already applied manually on GN100
-- but included here with OR IGNORE pattern for idempotency on
-- machines where v063 was not yet applied).
--
-- MSC-4: ALTER TABLE only — no INSERT/UPDATE/DELETE in this file.
-- SC-5:  No existing columns dropped or renamed.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- v063 columns (idempotent — already applied on GN100 via direct ALTER)
-- These will silently succeed on machines where v063 was already applied
-- because SQLite returns "duplicate column name" which we cannot suppress.
-- On fresh machines this file applies cleanly.
-- NOTE: Run v063 first if not yet applied, then this file.
-- -----------------------------------------------------------------------------

-- -----------------------------------------------------------------------------
-- runs table (v063 — if not already applied)
-- ALTER TABLE runs ADD COLUMN global_run_id          TEXT;
-- ALTER TABLE runs ADD COLUMN sync_status            INTEGER NOT NULL DEFAULT 0;
-- ALTER TABLE runs ADD COLUMN sync_samples_status    INTEGER NOT NULL DEFAULT 0;

-- goal_attempt table (v063)
-- ALTER TABLE goal_attempt ADD COLUMN retry_of_attempt_id  INTEGER;
-- ALTER TABLE goal_attempt ADD COLUMN failure_type         TEXT;

-- llm_interactions table (v063)
-- ALTER TABLE llm_interactions ADD COLUMN global_run_id    TEXT;
-- -----------------------------------------------------------------------------

-- -----------------------------------------------------------------------------
-- v064: 13 new columns across 9 tables
-- -----------------------------------------------------------------------------

-- 1. cpu_samples: global_run_id for cross-machine correlation
ALTER TABLE cpu_samples ADD COLUMN global_run_id TEXT;

-- 2. energy_samples: global_run_id for cross-machine correlation
ALTER TABLE energy_samples ADD COLUMN global_run_id TEXT;

-- 3. experiments: global_exp_id for cross-machine experiment tracking
ALTER TABLE experiments ADD COLUMN global_exp_id TEXT;

-- 4. goal_execution: GPU energy attribution columns
--    gpu_total_energy_uj: total GPU energy for this goal across all attempts
--    gpu_pct_of_pkg: GPU energy as percentage of total package energy
ALTER TABLE goal_execution ADD COLUMN gpu_total_energy_uj INTEGER;
ALTER TABLE goal_execution ADD COLUMN gpu_pct_of_pkg      REAL;

-- 5. hallucination_events: real wasted energy after baseline correction
--    wasted_energy_uj_real: dynamic (baseline-corrected) wasted energy
ALTER TABLE hallucination_events ADD COLUMN wasted_energy_uj_real INTEGER;

-- 6. hardware_config: agent and sync tracking columns
--    last_seen:     timestamp of last heartbeat from this machine
--    agent_status:  'active'|'inactive'|'unreachable' for multi-machine mgmt
--    agent_version: version of the A-LEMS agent on this machine
--    server_hw_id:  hw_id on the central server (for future sync)
ALTER TABLE hardware_config ADD COLUMN last_seen      TIMESTAMP;
ALTER TABLE hardware_config ADD COLUMN agent_status   TEXT;
ALTER TABLE hardware_config ADD COLUMN agent_version  TEXT;
ALTER TABLE hardware_config ADD COLUMN server_hw_id   INTEGER;

-- 7. interrupt_samples: global_run_id
ALTER TABLE interrupt_samples ADD COLUMN global_run_id TEXT;

-- 8. thermal_samples: global_run_id
ALTER TABLE thermal_samples ADD COLUMN global_run_id TEXT;

-- 9. orchestration_tax_summary: global_run_id
ALTER TABLE orchestration_tax_summary ADD COLUMN global_run_id TEXT;

-- -----------------------------------------------------------------------------
-- SC-7: schema_version bump
-- -----------------------------------------------------------------------------
INSERT OR IGNORE INTO schema_version (version, applied_at, description)
VALUES (64, datetime('now'),
    'comprehensive schema sync: 13 missing columns across 9 tables (global_run_id, gpu attribution, agent tracking)');
