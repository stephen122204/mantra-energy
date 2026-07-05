-- Migration v77: Network energy attribution table
-- SPEC_03: Cross-platform network wait energy attribution
-- Stores per-run network wait energy with strategy provenance
--
-- Verify current version before applying:
--   sqlite3 $DB "SELECT MAX(version) FROM schema_version;"
-- Expected: 76

CREATE TABLE IF NOT EXISTS network_energy_attribution (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL,
    strategy_used    TEXT    NOT NULL,   -- method_id of the strategy selected
    energy_uj        INTEGER,            -- NULL if unmeasurable (MIC-3 compliant)
    confidence       REAL    NOT NULL,   -- strategy confidence [0.0, 1.0]
    measurement_type TEXT    NOT NULL,   -- MEASURED | INFERRED | LIMITED
    non_local_ms     REAL,               -- total blocking time across all windows
    window_count     INTEGER NOT NULL DEFAULT 0, -- number of LLM blocking windows
    coverage_fraction REAL,              -- fraction of windows with energy data
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_nea_run_id
    ON network_energy_attribution(run_id);

INSERT INTO schema_version (version, applied_at, description)
VALUES (77, datetime('now'), 'SPEC_03 network energy attribution table');
