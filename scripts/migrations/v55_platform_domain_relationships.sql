-- v55_platform_domain_relationships.sql
-- Platform topology: which domains contribute to which root on each machine.
-- contributes_to_parent is PER PLATFORM, not per domain.
-- GPU contributes_to_parent=1 on GN100 (unified memory, inside pkg).
-- GPU contributes_to_parent=0 on Alex RTX (PCIe discrete, outside pkg).
-- hardware_hash is stable machine identity from hardware_config.
-- Seeded automatically by detect_hardware.py on first run per machine.
-- Never edited manually.
-- cp to: scripts/migrations/v55_platform_domain_relationships.sql

CREATE TABLE IF NOT EXISTS platform_domain_relationships (
    hw_id                 INTEGER NOT NULL REFERENCES hardware_config(hw_id),
    hardware_hash         TEXT    NOT NULL,
    source_id             INTEGER NOT NULL REFERENCES energy_sources(source_id),
    domain_id             INTEGER NOT NULL REFERENCES energy_domains(domain_id),
    parent_domain_id      INTEGER REFERENCES energy_domains(domain_id),
    contributes_to_parent BOOLEAN NOT NULL DEFAULT 1,
    PRIMARY KEY (hw_id, source_id, domain_id)
);

CREATE INDEX IF NOT EXISTS idx_pdr_hash
    ON platform_domain_relationships(hardware_hash, source_id, domain_id);

PRAGMA foreign_key_check;
PRAGMA integrity_check;

INSERT INTO schema_version (version, applied_at, description)
VALUES (55, datetime('now'), 'Unified energy schema: platform_domain_relationships table');
