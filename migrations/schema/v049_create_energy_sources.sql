-- v049_create_energy_sources.sql
-- Creates energy_sources lookup table.
-- One row per measurement interface (RAPL, SPBM, DCGM, NVML etc).
-- Adding a new platform's row is a seed migration, not a schema change.
-- See migrations/seed/s001_energy_sources.sql for the initial rows.

CREATE TABLE IF NOT EXISTS energy_sources (
    source_id    INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL UNIQUE,
    description  TEXT,
    confidence   REAL    NOT NULL DEFAULT 1.0,
    provenance   TEXT    NOT NULL DEFAULT 'MEASURED',
    layer        TEXT    NOT NULL DEFAULT 'silicon'
);
