ALTER TABLE runs ADD COLUMN planning_energy_uj INTEGER;
ALTER TABLE runs ADD COLUMN execution_energy_uj INTEGER;
ALTER TABLE runs ADD COLUMN synthesis_energy_uj INTEGER;

ALTER TABLE orchestration_events ADD COLUMN raw_energy_uj INTEGER;
ALTER TABLE orchestration_events ADD COLUMN cpu_fraction_per_phase REAL;
ALTER TABLE orchestration_events ADD COLUMN attributed_energy_uj INTEGER;
ALTER TABLE orchestration_events ADD COLUMN attribution_method TEXT;
ALTER TABLE orchestration_events ADD COLUMN quality_score REAL;
ALTER TABLE orchestration_events ADD COLUMN proc_ticks_min INTEGER;
ALTER TABLE orchestration_events ADD COLUMN proc_ticks_max INTEGER;
ALTER TABLE orchestration_events ADD COLUMN total_ticks_min INTEGER;
ALTER TABLE orchestration_events ADD COLUMN total_ticks_max INTEGER;

ALTER TABLE interrupt_samples ADD COLUMN proc_ticks_start INTEGER;
ALTER TABLE interrupt_samples ADD COLUMN proc_ticks_end INTEGER;

CREATE INDEX IF NOT EXISTS idx_orch_phase_attribution
    ON orchestration_events(run_id, phase, start_time_ns);
