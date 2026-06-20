-- Migration v71: fix cpu_idle_states FK — was REFERENCES runs(id), should be runs(run_id)
--
-- Bug found during live testing on UBUNTU2505 (2026-06-20): v70 migration created
-- cpu_idle_states.run_id with "REFERENCES runs(id)" but the runs table's actual
-- primary key column is run_id, not id. SQLite enforced this once a real INSERT
-- was attempted, raising "foreign key mismatch" and silently failing every write
-- (caught by the repository's broad except Exception handler).
--
-- SQLite cannot ALTER a foreign key constraint in place — table must be rebuilt.
-- Table was empty (0 rows ever successfully inserted due to this bug) so this is
-- a safe drop+recreate, not a data migration.

DROP TABLE IF EXISTS cpu_idle_states;

CREATE TABLE cpu_idle_states (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES runs(run_id),
    platform            TEXT NOT NULL,
    state_name          TEXT NOT NULL,
    depth_rank          INTEGER NOT NULL,
    residency_seconds   REAL NOT NULL,
    residency_type      TEXT NOT NULL CHECK(residency_type IN (
                            'delta', 'cumulative', 'percentage')),
    measurement_source  TEXT NOT NULL,
    UNIQUE(run_id, measurement_source, state_name)
);

CREATE INDEX IF NOT EXISTS idx_cpu_idle_states_run_id
    ON cpu_idle_states(run_id);

CREATE INDEX IF NOT EXISTS idx_cpu_idle_states_platform_depth
    ON cpu_idle_states(platform, depth_rank);

INSERT INTO schema_version (version, description, applied_at)
VALUES (71, 'cpu_idle_states: fix FK to reference runs(run_id) not runs(id) — bug found in live testing', datetime('now'));
