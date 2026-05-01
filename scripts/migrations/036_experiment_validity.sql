-- Migration 036: Add experiment validity columns to experiments table
-- Enables paper queries to filter out development artifacts via AND e.is_valid = 1

ALTER TABLE experiments ADD COLUMN is_valid INTEGER NOT NULL DEFAULT 1;
ALTER TABLE experiments ADD COLUMN invalidation_reason TEXT;
ALTER TABLE experiments ADD COLUMN invalidated_at TIMESTAMP;

-- Mark all experiments before today as development artifacts
UPDATE experiments
SET is_valid = 0,
    invalidation_reason = 'pre-fix development artifact — wiring incomplete',
    invalidated_at = CURRENT_TIMESTAMP
WHERE DATE(created_at) < DATE('now');

PRAGMA integrity_check;
