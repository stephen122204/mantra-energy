-- v51_energy_samples_v2.sql
-- One row per measurement event from any backend.
-- Narrow by design — hot path during experiments.
-- global_run_id NULL at insert time, populated at sync by sync_client.
-- cp to: scripts/migrations/v51_energy_samples_v2.sql

CREATE TABLE IF NOT EXISTS energy_samples_v2 (
    sample_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES runs(run_id),
    global_run_id TEXT,
    source_id     INTEGER NOT NULL REFERENCES energy_sources(source_id),
    timestamp_ns  BIGINT  NOT NULL,
    interval_ns   BIGINT  NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_esv2_run
    ON energy_samples_v2(run_id);
CREATE INDEX IF NOT EXISTS idx_esv2_run_source
    ON energy_samples_v2(run_id, source_id);
CREATE INDEX IF NOT EXISTS idx_esv2_time
    ON energy_samples_v2(run_id, timestamp_ns);

PRAGMA foreign_key_check;
PRAGMA integrity_check;

INSERT INTO schema_version (version, applied_at, description)
VALUES (51, datetime('now'), 'Unified energy schema: energy_samples_v2 table');
