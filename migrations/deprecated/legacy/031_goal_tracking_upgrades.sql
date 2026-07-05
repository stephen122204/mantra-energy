-- Migration 031: Goal Tracking Runtime Upgrades
-- Adds task_id, status, timestamps to goal_execution and goal_attempt.
-- Adds etl_queue table for decoupled ETL execution tracking.
-- Schema revision: 031
-- Run: sqlite3 data/experiments.db < scripts/migrations/031_goal_tracking_upgrades.sql

-- ── goal_execution upgrades ───────────────────────────────────────────────────
-- task_id links to task_categories for per-category analysis
ALTER TABLE goal_execution ADD COLUMN task_id TEXT;

-- status tracks lifecycle: pending → running → solved|failed|partial
ALTER TABLE goal_execution ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'
    CHECK(status IN ('pending','running','solved','failed','partial'));

ALTER TABLE goal_execution ADD COLUMN started_at  TIMESTAMP;
ALTER TABLE goal_execution ADD COLUMN finished_at TIMESTAMP;
-- updated_at supports change detection without full table scan
ALTER TABLE goal_execution ADD COLUMN updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_goal_exec_task_id
    ON goal_execution(task_id);
CREATE INDEX IF NOT EXISTS idx_goal_exec_status
    ON goal_execution(status);

-- ── goal_attempt upgrades ─────────────────────────────────────────────────────
-- status is more granular than outcome — records terminal hardware state
ALTER TABLE goal_attempt ADD COLUMN status TEXT NOT NULL DEFAULT 'running'
    CHECK(status IN ('running','success','failed','cancelled','timeout','crashed'));

-- started_at defaults now so existing rows get a sentinel value
ALTER TABLE goal_attempt ADD COLUMN started_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE goal_attempt ADD COLUMN finished_at TIMESTAMP;
ALTER TABLE goal_attempt ADD COLUMN updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_goal_attempt_status
    ON goal_attempt(status);

-- ── etl_queue ─────────────────────────────────────────────────────────────────
-- Decouples ETL execution from run completion — runner enqueues, ETL runner processes
CREATE TABLE IF NOT EXISTS etl_queue (
    queue_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type   TEXT NOT NULL
                  CHECK(entity_type IN ('goal_execution','run')),
    entity_id     INTEGER NOT NULL,
    etl_name      TEXT NOT NULL,
    -- pending → processing → done|failed
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK(status IN ('pending','processing','done','failed')),
    error_message TEXT,           -- NULL on success, populated on failure
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at  TIMESTAMP       -- NULL until ETL runner picks up the row
);

-- Composite index: ETL runner queries by status + etl_name to find pending work
CREATE INDEX IF NOT EXISTS idx_etl_queue_status
    ON etl_queue(status, etl_name);

-- Entity lookup: find all queue entries for a specific goal or run
CREATE INDEX IF NOT EXISTS idx_etl_queue_entity
    ON etl_queue(entity_type, entity_id);

-- workflow_type missing from live DB — added via ALTER TABLE
ALTER TABLE goal_execution ADD COLUMN workflow_type TEXT NOT NULL DEFAULT 'linear';

-- first_run_id made nullable — run_id unknown at goal start time
-- FK removed — cannot enforce FK on nullable column reliably in SQLite
