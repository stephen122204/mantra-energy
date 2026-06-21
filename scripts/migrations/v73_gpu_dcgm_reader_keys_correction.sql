-- v73_gpu_dcgm_reader_keys_correction.sql
-- v62 set GPU.reader_keys = 'gpu,gpu_dcgm', anticipating gpu_dcgm would map
-- into the same GPU domain. v72 gave gpu_dcgm its own domain instead, to
-- keep GPU's broad SPBM rail separate for the NVLink-C2C paper. This
-- corrects the now-stale documentation so a reviewer querying reader_keys
-- straight from the database sees the truth, not the original plan.
-- BASELINE_DOMAIN_MAP in code remains the runtime authority, unchanged —
-- this is metadata correction only, never read at runtime.

UPDATE energy_domains
SET reader_keys = 'gpu', legacy_column = 'gpu_power_watts'
WHERE name = 'GPU';

UPDATE energy_domains
SET reader_keys = 'gpu_dcgm', legacy_column = NULL
WHERE name = 'GPU_DCGM';

INSERT INTO schema_version (version, applied_at, description)
VALUES (73, datetime('now'), 'Correct GPU/GPU_DCGM reader_keys documentation after v72 split them into separate domains');
