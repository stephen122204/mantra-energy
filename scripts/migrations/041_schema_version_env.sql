-- Migration 041: Add schema_version to environment_config table
-- Enables Henv to fingerprint DB schema alongside git commit
-- Required for reproducibility protocol (Paper 1, §5)
-- Compliance: SC-1, SC-2, SC-3, MPC-1

-- Step 1: DDL change
ALTER TABLE environment_config ADD COLUMN schema_version INTEGER DEFAULT 8;

-- Step 2: Backfill all existing environment records
-- All canonical runs collected under schema version 8
UPDATE environment_config SET schema_version = 8;

-- Step 3: Record this migration
INSERT INTO schema_version (version, applied_at, description)
VALUES (28, datetime('now'), 'Add schema_version to environment_config table');

