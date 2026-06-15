-- v53_energy_derived_metrics.sql
-- ETL-computed quantities only. Never raw measurements.
-- sample_id nullable: NULL = run-level aggregate, NOT NULL = per-sample.
-- derivation_formula is citeable in paper (e.g. 'SPBM_GPU - DCGM_GPU').
-- source_ids_used comma-separated source_ids that fed this derivation.
-- run_id and global_run_id denormalized for sync_client fetch.
-- cp to: scripts/migrations/v53_energy_derived_metrics.sql

CREATE TABLE IF NOT EXISTS energy_derived_metrics (
    metric_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id             INTEGER NOT NULL REFERENCES runs(run_id),
    global_run_id      TEXT,
    sample_id          INTEGER REFERENCES energy_samples_v2(sample_id),
    metric_name        TEXT    NOT NULL,
    value_uj           REAL,
    derivation_formula TEXT    NOT NULL,
    source_ids_used    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_edm_run
    ON energy_derived_metrics(run_id);
CREATE INDEX IF NOT EXISTS idx_edm_metric
    ON energy_derived_metrics(run_id, metric_name);
CREATE INDEX IF NOT EXISTS idx_edm_sample
    ON energy_derived_metrics(sample_id)
    WHERE sample_id IS NOT NULL;

PRAGMA foreign_key_check;
PRAGMA integrity_check;

INSERT INTO schema_version (version, applied_at, description)
VALUES (53, datetime('now'), 'Unified energy schema: energy_derived_metrics table');
