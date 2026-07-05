-- Migration 015: CPU Fraction Attribution columns
-- Chunk 3 — adds PID capture and energy attribution columns to runs table
--
-- Rules:
--   - Backward compat: ALTER ADD only, never DROP/RENAME
--   - schema.py must be updated in sync with this file
--   - All three columns registered in provenance.py (pid=SYSTEM, others=CALCULATED)
ALTER TABLE runs ADD COLUMN pid INTEGER;
ALTER TABLE runs ADD COLUMN cpu_fraction REAL;
ALTER TABLE runs ADD COLUMN attributed_energy_uj INTEGER;
