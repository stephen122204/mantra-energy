-- Migration 026: Experiment Metadata
-- Adds experiment_type, experiment_goal, experiment_notes to experiments table
-- Valid experiment_type values must match VALID_EXPERIMENT_TYPES in schema.py
-- Schema revision: 026

ALTER TABLE experiments ADD COLUMN experiment_type TEXT NOT NULL DEFAULT 'normal';
ALTER TABLE experiments ADD COLUMN experiment_goal TEXT;
ALTER TABLE experiments ADD COLUMN experiment_notes TEXT;

CREATE TRIGGER IF NOT EXISTS trg_exp_type_insert
BEFORE INSERT ON experiments
BEGIN
    SELECT CASE
        WHEN NEW.experiment_type IS NULL OR NEW.experiment_type NOT IN (
            'normal','overhead_study','retry_study','failure_injection',
            'quality_sweep','calibration','ablation','pilot','debug'
        )
        THEN RAISE(ABORT, 'Invalid experiment_type value')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_exp_type_update
BEFORE UPDATE OF experiment_type ON experiments
BEGIN
    SELECT CASE
        WHEN NEW.experiment_type IS NULL OR NEW.experiment_type NOT IN (
            'normal','overhead_study','retry_study','failure_injection',
            'quality_sweep','calibration','ablation','pilot','debug'
        )
        THEN RAISE(ABORT, 'Invalid experiment_type value')
    END;
END;
