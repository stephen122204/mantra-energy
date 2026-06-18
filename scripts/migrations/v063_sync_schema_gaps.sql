-- =============================================================================
-- MIGRATION v063: Sync schema gaps between UBUNTU2505 and GN100
-- =============================================================================
-- Problem:
--   Columns added via manual migrations on UBUNTU2505 were never in schema.py.
--   GN100 fresh checkout missed them. This migration adds the 6 missing columns.
--
-- Missing columns discovered by PRAGMA table_info diff on 2026-06-18:
--   runs:             global_run_id, sync_status, sync_samples_status
--   goal_attempt:     retry_of_attempt_id, failure_type
--   llm_interactions: global_run_id
--
-- After this migration, schema.py CREATE TABLE statements must also be updated
-- to include these columns so future fresh checkouts never have this gap again.
--
-- SC-5: no existing columns dropped or renamed.
-- MSC-4: this file contains ALTER TABLE only (schema/ category).
-- =============================================================================

-- runs table: 3 missing columns
ALTER TABLE runs ADD COLUMN global_run_id          TEXT;
ALTER TABLE runs ADD COLUMN sync_status            INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN sync_samples_status    INTEGER NOT NULL DEFAULT 0;

-- goal_attempt table: 2 missing columns
ALTER TABLE goal_attempt ADD COLUMN retry_of_attempt_id  INTEGER;
ALTER TABLE goal_attempt ADD COLUMN failure_type         TEXT;

-- llm_interactions table: 1 missing column
ALTER TABLE llm_interactions ADD COLUMN global_run_id    TEXT;

-- SC-7: schema_version bump
INSERT OR IGNORE INTO schema_version (version, applied_at, description)
VALUES (63, datetime('now'),
    'sync schema gaps: global_run_id, sync_status, sync_samples_status, retry_of_attempt_id, failure_type');
