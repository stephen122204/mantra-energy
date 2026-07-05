-- v050_create_energy_domains.sql
-- Creates energy_domains hierarchy with multiple roots.
-- PACKAGE, UNIFIED, NETWORK, ACCELERATOR, STORAGE are independent roots.
-- contributes_to_parent lives on platform_domain_relationships (v055).
-- See migrations/seed/s002_energy_domains.sql for the initial rows.

CREATE TABLE IF NOT EXISTS energy_domains (
    domain_id             INTEGER PRIMARY KEY,
    name                  TEXT    NOT NULL UNIQUE,
    description           TEXT,
    parent_domain_id      INTEGER REFERENCES energy_domains(domain_id),
    is_leaf               BOOLEAN NOT NULL DEFAULT 1,
    is_cumulative         BOOLEAN NOT NULL DEFAULT 1,
    unit                  TEXT    NOT NULL DEFAULT 'uj'
);
