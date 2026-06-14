-- Migration 042: task_quality_config table
-- Maps task_category -> judge method, threshold, dual_judge flag.
-- Category-level config — works for EpG, mEpG, qEpG tasks uniformly.
-- Seeded by scripts/seed_quality_config.py (run by 8.5-C agent).
-- Schema revision: 042

CREATE TABLE IF NOT EXISTS task_quality_config (
    config_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    task_category   TEXT NOT NULL UNIQUE,
    metric_type     TEXT NOT NULL CHECK(metric_type IN ('binary','scalar','pairwise','testsuite')),
    judge_method    TEXT NOT NULL CHECK(judge_method IN ('exact_match','semantic_similarity','llm_judge','unit_test')),
    threshold       REAL NOT NULL DEFAULT 0.80,
    dual_judge      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_category) REFERENCES task_categories(task_id)
);

CREATE INDEX IF NOT EXISTS idx_tqc_category ON task_quality_config(task_category);
CREATE INDEX IF NOT EXISTS idx_tqc_method   ON task_quality_config(judge_method);

INSERT INTO schema_version (version, applied_at, description)
VALUES (42, datetime('now'), 'task_quality_config table');
