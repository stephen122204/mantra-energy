-- v74_gpu_dynamic_method_provenance.sql
-- Adds provenance for the run-local adaptive GPU dynamic energy method.
--
-- gpu_dynamic_method: 'RUN_LOCAL_IDLE' when idle power was estimated from
-- this run's own idle-classified GPU samples (the primary, preferred
-- method), or 'EXTERNAL_IDLE_BASELINE' when the run had zero idle samples
-- to build a local reference from and fell back to the separately
-- measured calibration baseline instead (secondary method, documented
-- fallback, not silent).
--
-- gpu_idle_power_w_used: the actual idle power value, in watts, that was
-- subtracted for this run, whichever method produced it. Makes every run
-- fully auditable: which method, and the literal number behind it, not
-- just a label.

ALTER TABLE runs ADD COLUMN gpu_dynamic_method   TEXT;
ALTER TABLE runs ADD COLUMN gpu_idle_power_w_used REAL;

INSERT INTO schema_version (version, applied_at, description)
VALUES (74, datetime('now'),
    'gpu_dynamic_method + gpu_idle_power_w_used: provenance for run-local adaptive GPU baseline, RUN_LOCAL_IDLE primary, EXTERNAL_IDLE_BASELINE documented fallback');
