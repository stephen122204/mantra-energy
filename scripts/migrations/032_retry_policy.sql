-- Migration 032: Retry Policy and Tool Failure Wiring
-- Adds retry_policy table, task_retry_override table.
-- Adds retry tracking columns to goal_attempt.
-- Schema revision: 032

-- ── retry_policy ──────────────────────────────────────────────────────────────
-- Template policies loaded at seed time. Experiments reference by policy_name.
CREATE TABLE IF NOT EXISTS retry_policy (
    policy_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_name            TEXT NOT NULL UNIQUE,
    max_retries            INTEGER NOT NULL DEFAULT 1,
    retry_on_timeout       INTEGER NOT NULL DEFAULT 1,
    retry_on_tool_error    INTEGER NOT NULL DEFAULT 1,
    retry_on_api_error     INTEGER NOT NULL DEFAULT 1,
    retry_on_wrong_answer  INTEGER NOT NULL DEFAULT 0,
    backoff_seconds        REAL NOT NULL DEFAULT 0.0,
    created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_retry_policy_name
    ON retry_policy(policy_name);

-- ── task_retry_override ───────────────────────────────────────────────────────
-- Per-category overrides. Takes precedence over template policy max_retries.
-- Allows task categories with known flakiness to retry more aggressively.
CREATE TABLE IF NOT EXISTS task_retry_override (
    task_category   TEXT PRIMARY KEY,
    max_retries     INTEGER NOT NULL,
    policy_name     TEXT NOT NULL,
    FOREIGN KEY (policy_name) REFERENCES retry_policy(policy_name)
);

-- ── goal_attempt retry columns ────────────────────────────────────────────────
-- Added here rather than migration 027 — retry concept did not exist at that time.
ALTER TABLE goal_attempt ADD COLUMN retry_of_attempt_id INTEGER;
ALTER TABLE goal_attempt ADD COLUMN failure_type TEXT;
ALTER TABLE goal_attempt ADD COLUMN is_retry INTEGER NOT NULL DEFAULT 0;

-- Composite index supports "show all retries for a goal" query efficiently
CREATE INDEX IF NOT EXISTS idx_goal_attempt_retry
    ON goal_attempt(goal_id, is_retry);

-- Supports walking retry chains: attempt → retry_of → original
CREATE INDEX IF NOT EXISTS idx_goal_attempt_retry_of
    ON goal_attempt(retry_of_attempt_id);

-- ── Seed default policies ─────────────────────────────────────────────────────
-- Four canonical policies cover all paper experiment types.
-- aggressive includes wrong_answer retry — needed for quality_sweep experiments.
INSERT OR IGNORE INTO retry_policy
    (policy_name, max_retries, retry_on_timeout, retry_on_tool_error,
     retry_on_api_error, retry_on_wrong_answer, backoff_seconds)
VALUES
    ('no_retry',     0, 0, 0, 0, 0, 0.0),
    ('default',      1, 1, 1, 1, 0, 0.0),
    ('aggressive',   3, 1, 1, 1, 1, 2.0),
    ('conservative', 1, 1, 0, 1, 0, 5.0);
