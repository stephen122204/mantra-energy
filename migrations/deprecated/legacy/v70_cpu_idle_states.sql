-- Migration v70: cpu_idle_states — cross-platform normalized idle state residency
-- Approved spec: SPEC_CPU_IDLE_STATES.md v1.0 (2026-06-18)
--
-- Rationale: x86 c2/c7 columns in runs table cannot represent ARM LPI states.
-- This table stores platform-native state names with depth_rank for cross-platform
-- comparison without claiming hardware equivalence (e.g. LPI-0 ≠ C2).
--
-- Existing c2_time_seconds ... c7_time_seconds on runs are KEPT (SC-5: never DROP).
-- New experiments write to this table; legacy x86 data retains its original columns.

CREATE TABLE IF NOT EXISTS cpu_idle_states (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES runs(id),
    -- Free-form platform string: intel_x86_64 | amd_x86_64 | grace_aarch64 |
    -- apple_arm64 | ampere_aarch64. No CHECK — SQLite cannot ALTER CHECK later.
    -- Application layer validates via platform detection system.
    platform            TEXT NOT NULL,
    -- Exact hardware state name as reported: C2, C3, C6, C7, LPI-0, LPI-1 etc.
    -- No mapping or abstraction — paper shows exact vendor names.
    state_name          TEXT NOT NULL,
    -- Ordinal idle depth: 0=shallowest, higher=deeper.
    -- Query via ORDER BY depth_rank DESC, not WHERE depth_rank = MAX() — avoids
    -- contiguity assumption (states may not be consecutive integers on all CPUs).
    depth_rank          INTEGER NOT NULL,
    residency_seconds   REAL NOT NULL,
    -- CHECK constrained because delta/cumulative/percentage is a CLOSED set.
    -- ARM cpuidle sysfs = cumulative. turbostat = delta. Making this explicit
    -- prevents ETL from treating cumulative values as per-interval deltas.
    residency_type      TEXT NOT NULL CHECK(residency_type IN (
                            'delta', 'cumulative', 'percentage')),
    -- How was residency measured: turbostat | cpuidle_sysfs | msr | perf | iokit
    -- Essential for paper reproducibility — reviewers trace each value to source.
    measurement_source  TEXT NOT NULL,
    -- Prevents duplicates. Includes measurement_source because turbostat and MSR
    -- can both report C6 on same run during validation experiments.
    UNIQUE(run_id, measurement_source, state_name)
);

-- Index for ETL aggregation queries (ALEOE training signal, run-level features)
CREATE INDEX IF NOT EXISTS idx_cpu_idle_states_run_id
    ON cpu_idle_states(run_id);

-- Index for cross-platform comparison queries (platform + depth side by side)
CREATE INDEX IF NOT EXISTS idx_cpu_idle_states_platform_depth
    ON cpu_idle_states(platform, depth_rank);

-- Record migration in schema_version (SC-7)
INSERT INTO schema_version (version, description, applied_at)
VALUES (70, 'cpu_idle_states: cross-platform normalized idle state residency', datetime('now'));
