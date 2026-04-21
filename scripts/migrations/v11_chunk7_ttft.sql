-- =============================================================================
-- Migration v11: Chunk 7 — Add TTFT/TPOT streaming metrics to runs table
-- =============================================================================
-- Purpose:
--   Provision ttft_ms and tpot_ms columns for Chunk 4 streaming adapter work.
--   Columns are NULL for all existing runs (non-streaming) and NULL for
--   non-streaming calls going forward. Chunk 4 will populate via ETL.
--
-- MPC compliance:
--   provenance.py entries added: ttft_ms, tpot_ms
--   seed_methodology.py entries added: ttft_measurement_v1, tpot_measurement_v1
--   yaml refs: config/methodology_refs/ttft_measurement_v1.yaml
--
-- SC rule: schema.py must be updated to match after this migration runs.
-- =============================================================================

ALTER TABLE runs ADD COLUMN ttft_ms REAL DEFAULT NULL;
ALTER TABLE runs ADD COLUMN tpot_ms REAL DEFAULT NULL;

-- Verify columns added
SELECT 'v11 migration complete' AS status,
       COUNT(*) AS total_runs,
       SUM(CASE WHEN ttft_ms IS NULL THEN 1 ELSE 0 END) AS ttft_null_count
FROM runs;
