-- v17: GPU attribution columns on runs, energy_attribution, run_quality
-- Chunk 15-A GPU energy support
-- Only adds columns NOT already present from v13/v14/v15
-- NEVER drops or renames existing columns (SC-5 compliance)
--
-- Existing from v13: gpu_total_energy_uj, gpu_baseline_energy_uj,
--                    gpu_dynamic_energy_uj, gpu_pct_of_pkg on runs
-- gpu_dynamic_energy_uj IS the canonical attributed GPU energy (B decision)
--
-- cp to: scripts/migrations/v17_gpu_attribution_columns.sql
-- Run:   sqlite3 data/experiments.db < scripts/migrations/v17_gpu_attribution_columns.sql

-- runs: attribution method and GPU count
-- gpu_attribution_method populated by gpu_attribution_etl.py (15-C)
-- gpu_count populated by chunk15_detect_gpu.py at run time
ALTER TABLE runs ADD COLUMN gpu_attribution_method TEXT;
ALTER TABLE runs ADD COLUMN gpu_count INTEGER DEFAULT 0;

-- energy_attribution: GPU AXIS 2A — functional projection
-- gpu_dynamic_energy_uj = gpu_llm_compute + gpu_orchestration (D7 invariant, exact)
-- Populated by gpu_attribution_etl.py (15-C). NULL at insert time (SC-4 compliant).
ALTER TABLE energy_attribution ADD COLUMN gpu_llm_compute_energy_uj   BIGINT;
ALTER TABLE energy_attribution ADD COLUMN gpu_orchestration_energy_uj  BIGINT;

-- energy_attribution: GPU AXIS 2B — workflow phase projection
-- gpu_dynamic = planning + execution + synthesis + inter (D8 invariant, exact)
-- Populated by gpu_attribution_etl.py (15-C). NULL at insert time.
ALTER TABLE energy_attribution ADD COLUMN gpu_phase_planning_uj    BIGINT;
ALTER TABLE energy_attribution ADD COLUMN gpu_phase_execution_uj   BIGINT;
ALTER TABLE energy_attribution ADD COLUMN gpu_phase_synthesis_uj   BIGINT;
ALTER TABLE energy_attribution ADD COLUMN gpu_phase_inter_uj       BIGINT;

-- run_quality: GPU validity dimension
-- Mirrors existing experiment_valid / rejection_reason pattern
ALTER TABLE run_quality ADD COLUMN gpu_valid INTEGER DEFAULT 1;
ALTER TABLE run_quality ADD COLUMN gpu_rejection_reason TEXT;
-- Valid values for gpu_rejection_reason:
--   'counter_unavailable'         — driver does not expose energy counters
--   'sample_coverage_below_95pct' — gpu_samples cover < 95% of run duration
--   'temperature_throttle_detected' — GPU thermal throttling mid-run
--   'clock_change_mid_run'        — DVFS event invalidates energy comparison

-- Integrity checks
PRAGMA foreign_key_check;
PRAGMA integrity_check;

INSERT INTO schema_version (version, applied_at, description)
VALUES (48, datetime('now'),
  'Chunk 15-A: gpu_attribution_method + gpu_count on runs; GPU AXIS 2A/2B on energy_attribution; gpu_valid on run_quality');
