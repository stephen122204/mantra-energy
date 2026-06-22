-- v75_gpu_dual_channel.sql
-- SPEC_GPU_DUAL_CHANNEL implementation
-- Adds SPBM broad-rail GPU energy alongside existing DCGM compute-only energy.
-- Source of truth for gpu_spbm_total_uj: SUM(energy_sample_domains.energy_uj)
-- WHERE run_id = ? AND domain_id = 7 (GPU/SPBM domain, confirmed real and
-- populated via core/readers/spbm_energy_reader.py _delta('gpu') deltas).
--
-- Verified prerequisites (2026-06-21, GN100):
--   - energy_domains MAX(domain_id) = 24, no collision with this migration
--   - domain_id 7 (GPU) confirmed populated for real runs (run_id=90: 231040000 uj)
--   - domain_id 24 (GPU_DCGM) confirmed NOT populated in energy_sample_domains
--     (DCGM total comes from in-memory GPUCollector sum, different path —
--     this migration does not change that path)
--   - idle_baseline_domains confirmed real, domain_id 7 has real power_watts
--     baseline rows (~5.3-5.6W range, matches MASTER_SPEC_CHUNK16 docs)

ALTER TABLE runs ADD COLUMN gpu_spbm_total_uj      INTEGER DEFAULT NULL;
ALTER TABLE runs ADD COLUMN gpu_spbm_dynamic_uj     INTEGER DEFAULT NULL;
ALTER TABLE runs ADD COLUMN gpu_residual_dynamic_uj INTEGER DEFAULT NULL;

INSERT INTO schema_version (version, applied_at, description)
VALUES (
    75,
    datetime('now'),
    'gpu_spbm_total_uj + gpu_spbm_dynamic_uj + gpu_residual_dynamic_uj: SPBM broad-rail GPU energy alongside DCGM compute-only energy. Residual = SPBM dynamic minus DCGM dynamic, not clamped to zero, negative is a valid diagnostic signal per spec.'
);
