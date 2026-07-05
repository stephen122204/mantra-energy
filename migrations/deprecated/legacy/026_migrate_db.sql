-- ============================================================
-- A-LEMS Framework Overhead Energy — DB Migration
-- Run once: sqlite3 data/experiments.db < 01_migrate_db.sql
-- ============================================================

ALTER TABLE runs ADD COLUMN rapl_before_pretask_uj    INTEGER;
ALTER TABLE runs ADD COLUMN rapl_after_task_uj         INTEGER;
ALTER TABLE runs ADD COLUMN post_task_duration_ns      INTEGER;
ALTER TABLE runs ADD COLUMN post_task_energy_uj        INTEGER;
ALTER TABLE runs ADD COLUMN framework_overhead_energy_uj INTEGER;
