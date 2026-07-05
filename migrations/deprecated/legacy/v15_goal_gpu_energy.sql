-- v15_goal_gpu_energy.sql
-- Add GPU PP1 energy columns to goal_execution and goal_attempt
-- GPU energy flows: runs.gpu_dynamic_energy_uj → goal_attempt → goal_execution
-- NULL on non-Tiger-Lake platforms. ETL populated after run completes.

ALTER TABLE goal_execution ADD COLUMN gpu_total_energy_uj   INTEGER;
-- SUM(gpu_dynamic_energy_uj) across all attempts for this goal

ALTER TABLE goal_execution ADD COLUMN gpu_pct_of_pkg        REAL;
-- gpu_total_energy_uj / total_energy_uj * 100 — GPU share of goal energy

ALTER TABLE goal_attempt   ADD COLUMN gpu_energy_uj         INTEGER;
-- gpu_dynamic_energy_uj from runs for this attempt — NULL on non-Tiger-Lake

INSERT INTO schema_version (version, applied_at, description)
VALUES (46, datetime('now'), 'goal_execution + goal_attempt: GPU PP1 energy columns');
