-- ============================================================
-- MIGRATION v9: Task Duration vs Framework Overhead Separation
-- ============================================================
-- PURPOSE:
--   Separates the full run wall-clock into four explicit windows:
--
-- COMPLETE TIME/ENERGY MODEL:
--
--   ┌─────────────────────────────────────────────────────────┐
--   │ Window         │ Time              │ Energy              │
--   ├─────────────────────────────────────────────────────────┤
--   │ pre_task       │ pre_task_dur_ns   │ pre_task_energy_uj  │
--   │ (intr/temp/    │ (rapl_before →    │ (rapl_before →      │
--   │  governor etc) │  run_start_perf)  │  rapl_start)        │
--   ├─────────────────────────────────────────────────────────┤
--   │ task           │ task_duration_ns  │ pkg_energy_uj       │
--   │ (executor)     │ (t0 → t1)         │ (rapl_start →       │
--   │                │                   │  rapl_end)          │
--   ├─────────────────────────────────────────────────────────┤
--   │ framework      │ framework_ovhd_ns │ NOT measured yet    │
--   │ (post-process) │ (t1 → t2)         │ (future: v2)        │
--   └─────────────────────────────────────────────────────────┘
--
-- TIMESTAMPS:
--   t_pre  = before _read_interrupts() (new RAPL capture point)
--   t0     = run_start_perf (before start_measurement)
--   t1     = task_end_perf  (after executor.execute returns)
--   t2     = run_end_perf   (after all post-processing)
--
-- KEY DESIGN DECISION:
--   pkg_energy_uj = E_task only (rapl_start → rapl_end)
--   pre_task_energy_uj = diagnostic only, NOT in attribution model
--   Paper claim: "A-LEMS measures execution energy, not instrumentation energy"
--
-- PLATFORM COMPLIANCE (PAC):
--   Uses time.perf_counter() and rapl.read_energy()
--   rapl.read_energy() returns None on macOS/ARM/fallback platforms
--   pre_task_energy_uj = NULL on non-RAPL platforms — graceful degradation
--
-- Doc: docs-src/mkdocs/source/research/14-measurement-boundary-methodology.md
-- ============================================================

-- ── Task execution window ────────────────────────────────────
-- task_duration_ns: t1-t0 = executor time only (canonical energy denominator)
ALTER TABLE runs ADD COLUMN task_duration_ns INTEGER;

-- framework_overhead_ns: t2-t1 = stop_measurement + post-processing cost
ALTER TABLE runs ADD COLUMN framework_overhead_ns INTEGER;

-- total_run_duration_ns: t2-t0 = task + framework (= legacy duration_ns)
ALTER TABLE runs ADD COLUMN total_run_duration_ns INTEGER;

-- duration_includes_overhead: 1=historical run, 0=corrected new run
ALTER TABLE runs ADD COLUMN duration_includes_overhead INTEGER DEFAULT 1;

-- ── Measurement coverage ─────────────────────────────────────
-- energy_sample_coverage_pct: sample_span/task_duration × 100
-- gold ≥95%, acceptable 80-95%, poor <80%
ALTER TABLE runs ADD COLUMN energy_sample_coverage_pct REAL;

-- ── Corrected power ──────────────────────────────────────────
-- avg_task_power_watts: pkg_energy / task_duration (correct denominator)
-- Replaces legacy avg_power_watts which used inflated total duration
ALTER TABLE runs ADD COLUMN avg_task_power_watts REAL;

-- ── Pre-task instrumentation window (diagnostic) ─────────────
-- pre_task_energy_uj: RAPL delta during pre-task context reads
--   = rapl.read_energy()["package-0"] at t_pre
--     minus rapl_start["package-0"] inside start_measurement()
-- Diagnostic only — NOT part of attribution model.
-- NULL on non-RAPL platforms (macOS, ARM VM, fallback).
ALTER TABLE runs ADD COLUMN pre_task_energy_uj INTEGER;

-- pre_task_duration_ns: wall time from first pre-task read to run_start_perf
--   = (run_start_perf - pre_task_start_perf) × 1e9
ALTER TABLE runs ADD COLUMN pre_task_duration_ns INTEGER;
