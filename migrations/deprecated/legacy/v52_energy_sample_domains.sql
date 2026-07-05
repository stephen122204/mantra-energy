-- v52_energy_sample_domains.sql
-- Raw domain energy values per sample. MEASURED only, never derived.
-- Two sources on same domain = two rows (e.g. GN100 GPU: SPBM + DCGM).
-- run_id denormalized for sync_client fetch efficiency.
-- global_run_id populated at sync time by sync_client.
-- cp to: scripts/migrations/v52_energy_sample_domains.sql

CREATE TABLE IF NOT EXISTS energy_sample_domains (
    sample_id     INTEGER NOT NULL REFERENCES energy_samples_v2(sample_id),
    run_id        INTEGER NOT NULL,
    global_run_id TEXT,
    domain_id     INTEGER NOT NULL REFERENCES energy_domains(domain_id),
    source_id     INTEGER NOT NULL REFERENCES energy_sources(source_id),
    energy_uj     REAL    NOT NULL,
    PRIMARY KEY (sample_id, domain_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_esd_run
    ON energy_sample_domains(run_id);
CREATE INDEX IF NOT EXISTS idx_esd_domain
    ON energy_sample_domains(domain_id, run_id);
CREATE INDEX IF NOT EXISTS idx_esd_source_domain
    ON energy_sample_domains(source_id, domain_id);

PRAGMA foreign_key_check;
PRAGMA integrity_check;

INSERT INTO schema_version (version, applied_at, description)
VALUES (52, datetime('now'), 'Unified energy schema: energy_sample_domains table');
