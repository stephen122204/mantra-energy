-- Migration 025: Create run_quality table
-- Stores per-run quality judgments computed by quality_scorer_v1.
-- No changes to runs table — separate table keyed by run_id.

CREATE TABLE IF NOT EXISTS run_quality (
    run_id              INTEGER PRIMARY KEY,
    experiment_valid    INTEGER NOT NULL,       -- 1=valid, 0=invalid (hard failure)
    quality_score       REAL    NOT NULL,       -- [0.0, 1.0] soft quality score
    rejection_reason    TEXT,                   -- JSON blob: hard_failures, soft_issues, metrics
    quality_version     INTEGER NOT NULL,       -- scorer VERSION constant for reproducibility
    computed_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_run_quality_run_id ON run_quality(run_id);
CREATE INDEX IF NOT EXISTS idx_run_quality_valid  ON run_quality(experiment_valid);
