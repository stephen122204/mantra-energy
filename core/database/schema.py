#!/usr/bin/env python3
"""
================================================================================
DATABASE SCHEMA – SQL definitions for all A‑LEMS tables
================================================================================

PURPOSE:
    Contains all CREATE TABLE, CREATE INDEX, and CREATE VIEW statements
    for the A‑LEMS database. This file is pure SQL – no Python logic.

WHY THIS EXISTS:
    - Separates schema definition from database logic
    - Makes schema changes easier to track
    - Can be reused by migration scripts
    - Keeps SQL in one place for review

TABLES:
    1. experiments
    2. hardware_config
    3. idle_baselines
    4. runs (main table, 70+ columns)
    5. orchestration_events
    6. orchestration_tax_summary
    7. energy_samples
    8. cpu_samples
    9. interrupt_samples
    10. ml_features (view)

AUTHOR: Deepak Panigrahy
================================================================================
"""

# ========================================================================
# Table 1: experiments
# ========================================================================
CREATE_EXPERIMENTS = """
CREATE TABLE IF NOT EXISTS experiments (
    exp_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    workflow_type TEXT CHECK(workflow_type IN ('linear','agentic','comparison')),
    model_name TEXT,
    model_id                  TEXT,
    execution_site            TEXT,
    transport                 TEXT,
    remote_energy_available   INTEGER DEFAULT 0,
    provider TEXT,
    task_name TEXT,
    country_code TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- ========== NEW COLUMNS START ==========
    group_id TEXT,                          -- Session ID (TD7)
    status TEXT DEFAULT 'pending',           -- pending/running/completed/partial/failed (TD8)
    started_at TIMESTAMP,                    -- When experiment started (TD8)
    completed_at TIMESTAMP,                  -- When experiment ended (TD8)
    error_message TEXT,                      -- Error if failed (TD8)
    runs_completed INTEGER DEFAULT 0,        -- Number of successful runs (TD8)
    runs_total INTEGER,
    optimization_enabled INTEGER DEFAULT 0,                                            -- Total runs planned (TD8)
    -- ========== NEW COLUMNS END ==========
    hw_id INTEGER REFERENCES hardware_config(hw_id),
    env_id INTEGER REFERENCES environment_config(env_id)    
);
"""
# ========================================================================
# Table 3: idle_baselines
# ========================================================================
CREATE_IDLE_BASELINES = """
CREATE TABLE IF NOT EXISTS idle_baselines (
    baseline_id TEXT PRIMARY KEY,
    timestamp REAL NOT NULL,
    package_power_watts REAL,
    core_power_watts REAL,
    uncore_power_watts REAL,
    dram_power_watts REAL,
    duration_seconds INTEGER,
    sample_count INTEGER,
    package_std REAL,
    core_std REAL,
    uncore_std REAL,
    dram_std REAL,
    governor TEXT,
    turbo TEXT,
    background_cpu REAL,
    process_count INTEGER,
    method TEXT
);
"""

# ========================================================================
# Table 4: runs (core table with 70+ columns)
# ========================================================================
CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    exp_id INTEGER NOT NULL,
    hw_id INTEGER,
    baseline_id TEXT,
    run_number INTEGER,
    workflow_type TEXT NOT NULL,

    -- Timing (all in nanoseconds)
    start_time_ns INTEGER,
    end_time_ns INTEGER,
    duration_ns INTEGER,

    -- Energy (all in microjoules)
    total_energy_uj INTEGER,
    dynamic_energy_uj INTEGER,
    baseline_energy_uj INTEGER,
    avg_power_watts REAL,
    pkg_energy_uj INTEGER,      -- Raw package energy
    core_energy_uj INTEGER,      -- Raw core energy
    uncore_energy_uj INTEGER,    -- Raw uncore energy
    dram_energy_uj INTEGER,      -- Raw DRAM energy
    -- Performance counters
    instructions BIGINT,
    cycles BIGINT,
    ipc REAL,
    cache_misses BIGINT,
    cache_references BIGINT,
    cache_miss_rate REAL,
    page_faults INTEGER,
    major_page_faults INTEGER,
    minor_page_faults INTEGER,

    -- Scheduler metrics
    context_switches_voluntary INTEGER,
    context_switches_involuntary INTEGER,
    total_context_switches INTEGER,
    thread_migrations INTEGER,
    run_queue_length REAL,
    kernel_time_ms REAL,
    user_time_ms REAL,

    -- Frequency & ring bus
    frequency_mhz REAL,
    ring_bus_freq_mhz REAL,

    -- CPU metrics (aggregated from samples)
    cpu_busy_mhz REAL,
    cpu_avg_mhz REAL,

    -- Thermal metrics
    package_temp_celsius REAL,
    baseline_temp_celsius REAL,
    start_temp_c REAL,
    max_temp_c REAL,
    min_temp_c REAL,
    thermal_delta_c REAL,
    thermal_during_experiment BOOLEAN,
    thermal_now_active BOOLEAN,
    thermal_since_boot BOOLEAN,
    experiment_valid BOOLEAN,

    -- C‑state residencies
    c2_time_seconds REAL,
    c3_time_seconds REAL,
    c6_time_seconds REAL,
    c7_time_seconds REAL,

    --swap metrics
    swap_total_mb REAL,
    swap_end_free_mb REAL,
    swap_start_used_mb REAL,
    swap_end_used_mb REAL,
    swap_start_cached_mb REAL,
    swap_end_cached_mb REAL,
    swap_end_percent REAL,

    -- MSR / wakeup
    wakeup_latency_us REAL,
    interrupt_rate REAL,
    thermal_throttle_flag INTEGER,

    -- Memory usage
    rss_memory_mb REAL,
    vms_memory_mb REAL,

    -- Token counts
    total_tokens INTEGER,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,

    -- Network latencies
    dns_latency_ms REAL,
    api_latency_ms REAL,
    compute_time_ms REAL,
    -- Network metrics (NEW)
    bytes_sent INTEGER,
    bytes_recv INTEGER,
    tcp_retransmits INTEGER,

    -- System state
    governor TEXT,
    turbo_enabled BOOLEAN,
    is_cold_start BOOLEAN,
    background_cpu_percent REAL,
    process_count INTEGER,

    -- Agentic‑specific metrics (NULL for linear runs)
    planning_time_ms REAL,
    execution_time_ms REAL,
    synthesis_time_ms REAL,
    phase_planning_ratio REAL,
    phase_execution_ratio REAL,
    phase_synthesis_ratio REAL,
    llm_calls INTEGER,
    tool_calls INTEGER,
    tools_used INTEGER,
    steps INTEGER,
    avg_step_time_ms REAL,
    orchestration_cpu_ms REAL,
    complexity_level INTEGER,
    complexity_score REAL,

    -- Sustainability metrics
    carbon_g REAL,
    water_ml REAL,
    methane_mg REAL,

    -- Derived efficiency metrics
    energy_per_instruction REAL,
    energy_per_cycle REAL,
    energy_per_token REAL,
    instructions_per_token REAL,
    interrupts_per_second REAL,

    -- Cryptographic run state hash
    run_state_hash TEXT,
    pid                     INTEGER,          -- PID of workload process
    cpu_fraction            REAL,             -- workload_ticks / total_ticks
    attributed_energy_uj    INTEGER,           -- cpu_fraction × dynamic_energy_uj 
    energy_measurement_mode TEXT,               -- MEASURED / INFERRED / LIMITED 
    planning_energy_uj      INTEGER,            -- Chunk 5: attributed phase energy
    execution_energy_uj     INTEGER,
    synthesis_energy_uj     INTEGER,  
    l1d_cache_misses_total  BIGINT,  -- Chunk 12: SUM from cpu_samples
    l2_cache_misses_total   BIGINT,
    l3_cache_hits_total     BIGINT,
    l3_cache_misses_total   BIGINT,
    disk_read_bytes_total   BIGINT,  -- Chunk 12: SUM from io_samples
    disk_write_bytes_total  BIGINT,
    voltage_vcore_avg       REAL,     -- Chunk 12: AVG from thermal_samples
    -- ── v9: Measurement Boundary (Duration Fix) ──────────────────────────────
    -- Separates task execution time from A-LEMS instrumentation overhead.
    -- Core principle: "A-LEMS measures execution energy, not instrumentation energy"
    --
    -- task_duration_ns: t1-t0 — executor time only — canonical energy denominator
    task_duration_ns              INTEGER,
    -- framework_overhead_ns: t2-t1 — stop_measurement + post-processing cost
    framework_overhead_ns         INTEGER,
    -- total_run_duration_ns: t2-t0 — full wall clock (= legacy duration_ns)
    total_run_duration_ns         INTEGER,
    -- duration_includes_overhead: 1=historical run, 0=corrected new run
    duration_includes_overhead    INTEGER DEFAULT 1,
    -- energy_sample_coverage_pct: sample_span/task_duration × 100
    -- gold ≥95%, acceptable 80-95%, poor <80%
    energy_sample_coverage_pct    REAL,
    -- avg_task_power_watts: pkg_energy / task_duration (correct power denominator)
    avg_task_power_watts          REAL,
    -- pre_task_energy_uj: RAPL delta during pre-task context reads (diagnostic only)
    -- NULL on non-RAPL platforms (macOS, ARM VM) — PAC compliant
    -- NOT part of attribution model — A-LEMS instrumentation overhead
    pre_task_energy_uj            INTEGER,
    -- pre_task_duration_ns: wall time from first pre-task read to run_start_perf
    pre_task_duration_ns          INTEGER,    

    FOREIGN KEY(exp_id) REFERENCES experiments(exp_id),
    FOREIGN KEY(hw_id) REFERENCES hardware_config(hw_id),
    FOREIGN KEY(baseline_id) REFERENCES idle_baselines(baseline_id)
);
"""

# ========================================================================
# Indexes for runs table
# ========================================================================
CREATE_RUNS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_runs_exp_id ON runs(exp_id);
CREATE INDEX IF NOT EXISTS idx_runs_hw_id ON runs(hw_id);
CREATE INDEX IF NOT EXISTS idx_runs_energy ON runs(total_energy_uj);
CREATE INDEX IF NOT EXISTS idx_runs_ipc ON runs(ipc);
CREATE INDEX IF NOT EXISTS idx_runs_interrupt ON runs(interrupt_rate);
CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_unique ON runs(exp_id, run_number, workflow_type);
"""

# ========================================================================
# Table 5: orchestration_events
# ========================================================================
CREATE_ORCHESTRATION_EVENTS = """
CREATE TABLE IF NOT EXISTS orchestration_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    step_index INTEGER,
    phase TEXT CHECK(phase IN ('planning','execution','waiting','synthesis')),
    event_type TEXT NOT NULL,
    start_time_ns INTEGER NOT NULL,
    end_time_ns INTEGER NOT NULL,
    duration_ns INTEGER NOT NULL,
    power_watts REAL,
    cpu_util_percent REAL,
    interrupt_rate REAL,
    event_energy_uj INTEGER,
    tax_contribution_uj INTEGER,
    tax_percent REAL,
    global_run_id TEXT,
    raw_energy_uj           INTEGER,            -- Chunk 5: MAX(pkg_end)-MIN(pkg_start)
    cpu_fraction_per_phase            REAL,               -- proc_ticks_delta / total_ticks_delta
    attributed_energy_uj    INTEGER,            -- cpu_fraction x raw_energy_uj
    attribution_method      TEXT,               -- cpu_counter_delta | fallback_run_level
    quality_score           REAL,               -- 0.0-1.0 based on sample count
    proc_ticks_min          INTEGER,
    proc_ticks_max          INTEGER,
    total_ticks_min         INTEGER,
    total_ticks_max         INTEGER,    

    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
"""

CREATE_EVENTS_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_events_run ON orchestration_events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_phase ON orchestration_events(phase);
"""

# ========================================================================
# Table 6: orchestration_tax_summary
# ========================================================================
CREATE_TAX_SUMMARY = """
CREATE TABLE IF NOT EXISTS orchestration_tax_summary (
    comparison_id INTEGER PRIMARY KEY AUTOINCREMENT,
    linear_run_id INTEGER NOT NULL,
    agentic_run_id INTEGER NOT NULL,
    linear_dynamic_uj INTEGER,
    agentic_dynamic_uj INTEGER,
    orchestration_tax_uj INTEGER,
    tax_percent REAL,
    linear_orchestration_uj INTEGER,    -- ← ADD THIS
    agentic_orchestration_uj INTEGER,   -- ← ADD THIS    
    FOREIGN KEY(linear_run_id) REFERENCES runs(run_id),
    FOREIGN KEY(agentic_run_id) REFERENCES runs(run_id)
);
"""

CREATE_TAX_INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_tax_pair ON orchestration_tax_summary(linear_run_id, agentic_run_id);
"""

# ========================================================================
# Table 7: energy_samples
# ========================================================================
CREATE_ENERGY_SAMPLES = """
CREATE TABLE IF NOT EXISTS energy_samples (
    sample_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL,
    timestamp_ns     INTEGER NOT NULL,
    -- Old delta columns — kept for backward compatibility
    pkg_energy_uj    INTEGER,
    core_energy_uj   INTEGER,
    uncore_energy_uj INTEGER,
    dram_energy_uj   INTEGER,
    -- Chunk 2: Raw start/end counter values per domain
    pkg_start_uj     INTEGER,   -- RAPL package counter at sample start
    pkg_end_uj       INTEGER,   -- RAPL package counter at sample end
    core_start_uj    INTEGER,   -- RAPL core counter at sample start
    core_end_uj      INTEGER,   -- RAPL core counter at sample end
    dram_start_uj    INTEGER,   -- RAPL DRAM counter at sample start
    dram_end_uj      INTEGER,   -- RAPL DRAM counter at sample end
    uncore_start_uj  INTEGER,   -- RAPL uncore counter at sample start
    uncore_end_uj    INTEGER,   -- RAPL uncore counter at sample end
    sample_start_ns  INTEGER,   -- epoch ns at sample start (explicit)
    sample_end_ns    INTEGER,   -- epoch ns at sample end (= timestamp_ns)
    interval_ns      INTEGER,   -- exact elapsed ns between start and end reads
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_energy_run_time ON energy_samples(run_id, timestamp_ns);
"""

# ========================================================================
# Table 8: cpu_samples
# ========================================================================
# ========================================================================
# Table 8: cpu_samples
# ========================================================================
CREATE_CPU_SAMPLES = """
CREATE TABLE IF NOT EXISTS cpu_samples (
    sample_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL,
    timestamp_ns     INTEGER NOT NULL,
    -- CPU Activity
    cpu_util_percent REAL,
    cpu_busy_mhz     REAL,
    cpu_avg_mhz      REAL,
    -- Core C-States
    c1_residency     REAL,
    c2_residency     REAL,
    c3_residency     REAL,
    c6_residency     REAL,
    c7_residency     REAL,
    -- Package C-States (deep sleep)
    pkg_c8_residency  REAL,
    pkg_c9_residency  REAL,
    pkg_c10_residency REAL,
    -- Power
    package_power    REAL,
    dram_power       REAL,
    -- GPU
    gpu_rc6          REAL,
    -- Temperature & efficiency
    package_temp     REAL,
    ipc              REAL,
    l1d_cache_misses     BIGINT,     -- Chunk 12: L1d cache misses from perf
    l2_cache_misses      BIGINT,     -- Chunk 12: L2 cache misses from perf
    l3_cache_hits        BIGINT,     -- Chunk 12: L3 cache hits from perf
    l3_cache_misses      BIGINT,      -- Chunk 12: L3 cache misses from perf    
    -- JSON overflow for additional turbostat columns
    extra_metrics_json TEXT,
    -- Chunk 2: Interval tracking
    sample_start_ns  INTEGER,          -- epoch ns at sample start (explicit)
    sample_end_ns    INTEGER,          -- epoch ns at sample end (= timestamp_ns)
    interval_ns      INTEGER,          -- elapsed ns for this turbostat sample
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_cpu_samples_run_id ON cpu_samples(run_id);
CREATE INDEX IF NOT EXISTS idx_cpu_samples_timestamp ON cpu_samples(run_id, timestamp_ns);
"""

# ========================================================================
# Table 9: interrupt_samples
# ========================================================================
CREATE_INTERRUPT_SAMPLES = """
CREATE TABLE IF NOT EXISTS interrupt_samples (
    sample_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id               INTEGER NOT NULL,
    timestamp_ns         INTEGER NOT NULL,
    -- Old rate column — kept for backward compatibility
    interrupts_per_sec   REAL,
    -- Chunk 2: Raw values + CPU ticks (Option B — same /proc/stat read)
    interrupts_raw       INTEGER,   -- raw interrupt count delta
    user_ticks_start     INTEGER,   -- /proc/stat user ticks at interval start
    user_ticks_end       INTEGER,   -- /proc/stat user ticks at interval end
    system_ticks_start   INTEGER,   -- /proc/stat system ticks at interval start
    system_ticks_end     INTEGER,   -- /proc/stat system ticks at interval end
    total_ticks_start    INTEGER,   -- /proc/stat sum(all fields) at interval
    total_ticks_end      INTEGER,   -- /proc/stat sum(all fields) at interval end
    proc_ticks_start     INTEGER,   -- /proc/[pid]/stat utime+stime at interval start
    proc_ticks_end       INTEGER    -- /proc/[pid]/stat utime+stime at interval end
    sample_start_ns      INTEGER,   -- epoch ns at sample start (explicit)
    sample_end_ns        INTEGER,   -- epoch ns at sample end (= timestamp_ns)
    interval_ns          INTEGER,   -- exact elapsed ns for this sample
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_interrupt_run_time ON interrupt_samples(run_id, timestamp_ns);
"""


# ========================================================================
# Table:10 thermal_samples - 1Hz thermal telemetry
# ========================================================================
THERMAL_SAMPLES_SCHEMA = """
CREATE TABLE IF NOT EXISTS thermal_samples (
    sample_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER NOT NULL,
    timestamp_ns   INTEGER NOT NULL,
    sample_time_s  REAL,
    cpu_temp       REAL,
    system_temp    REAL,
    wifi_temp      REAL,
    throttle_event INTEGER DEFAULT 0,
    voltage_vcore  REAL,             -- Chunk 12: Vcore voltage from hwmon sysfs
    fan_rpm        INTEGER,           -- Chunk 12: Fan RPM from hwmon sysfs    
    all_zones_json TEXT,
    sensor_count   INTEGER,
    -- Chunk 2: Interval tracking
    sample_start_ns      INTEGER,   -- epoch ns at sample start (explicit)
    sample_end_ns        INTEGER,   -- epoch ns at sample end (= timestamp_ns)
    interval_ns    INTEGER,            -- elapsed ns for this thermal sample
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_thermal_run_time ON thermal_samples(run_id, timestamp_ns);
"""
# ========================================================================
# View 11: ml_features (flattened for ML)
# ========================================================================
CREATE_ML_VIEW = """
CREATE VIEW IF NOT EXISTS ml_features AS
SELECT
    -- ========================================================================
    -- 1. Core identifiers (for joins)
    -- ========================================================================
    r.run_id,
    r.exp_id,
    e.group_id,
    r.run_number,
    r.workflow_type,
    
    -- ========================================================================
    -- 2. Experiment metadata (from experiments table)
    -- ========================================================================
    e.task_name,
    e.provider,
    e.model_name,
    e.country_code,
    e.optimization_enabled,
    
    -- ========================================================================
    -- 3. Hardware specs (from hardware_config)
    -- ========================================================================
    h.cpu_model,
    h.cpu_cores,
    h.cpu_threads,
    h.cpu_architecture,
    h.cpu_vendor,
    h.cpu_family,
    h.cpu_model_id,
    h.cpu_stepping,
    h.has_avx2,
    h.has_avx512,
    h.has_vmx,
    h.gpu_model,
    h.gpu_driver,
    h.gpu_count,
    h.ram_gb,
    h.system_type,
    h.system_manufacturer,
    h.system_product,
    h.virtualization_type,
    h.microcode_version,
    
    -- ========================================================================
    -- 4. Environment (from environment_config)
    -- ========================================================================
    env.python_version,
    env.git_commit,
    env.git_branch,
    env.git_dirty,
    env.numpy_version,
    env.torch_version,
    env.transformers_version,
    
    -- ========================================================================
    -- 5. Timing (from runs)
    -- ========================================================================
    r.start_time_ns,
    r.end_time_ns,
    r.duration_ns,
    r.duration_ns / 1e6 AS duration_ms,
    
    -- ========================================================================
    -- 6. Energy metrics (from runs)
    -- ========================================================================
    r.total_energy_uj,
    r.total_energy_uj / 1e6 AS total_energy_j,
    r.dynamic_energy_uj,
    r.dynamic_energy_uj / 1e6 AS dynamic_energy_j,
    r.baseline_energy_uj,
    r.baseline_energy_uj / 1e6 AS baseline_energy_j,
    r.avg_power_watts,
    r.pkg_energy_uj / 1e6 AS pkg_energy_j,
    r.core_energy_uj / 1e6 AS core_energy_j,
    r.uncore_energy_uj / 1e6 AS uncore_energy_j,
    r.dram_energy_uj / 1e6 AS dram_energy_j,
    
    -- ========================================================================
    -- 7. Performance counters (from runs)
    -- ========================================================================
    r.instructions,
    r.cycles,
    r.ipc,
    r.cache_misses,
    r.cache_references,
    r.cache_miss_rate,
    r.page_faults,
    r.major_page_faults,
    r.minor_page_faults,
    
    -- ========================================================================
    -- 8. Scheduler metrics (from runs)
    -- ========================================================================
    r.context_switches_voluntary,
    r.context_switches_involuntary,
    r.total_context_switches,
    r.thread_migrations,
    r.run_queue_length,
    r.kernel_time_ms,
    r.user_time_ms,
    
    -- ========================================================================
    -- 9. Frequency & bus (from runs)
    -- ========================================================================
    r.frequency_mhz,
    r.ring_bus_freq_mhz,
    r.cpu_busy_mhz,
    r.cpu_avg_mhz,
    
    -- ========================================================================
    -- 10. Thermal metrics (from runs)
    -- ========================================================================
    r.package_temp_celsius,
    r.baseline_temp_celsius,
    r.start_temp_c,
    r.max_temp_c,
    r.min_temp_c,
    r.thermal_delta_c,
    r.thermal_during_experiment,
    r.thermal_now_active,
    r.thermal_since_boot,
    r.experiment_valid,
    
    -- ========================================================================
    -- 11. C-state residencies (from runs)
    -- ========================================================================
    r.c2_time_seconds,
    r.c3_time_seconds,
    r.c6_time_seconds,
    r.c7_time_seconds,
    
    -- ========================================================================
    -- 12. Memory & swap (from runs)
    -- ========================================================================
    r.swap_total_mb,
    r.swap_end_free_mb,
    r.swap_start_used_mb,
    r.swap_end_used_mb,
    r.swap_start_cached_mb,
    r.swap_end_cached_mb,
    r.swap_end_percent,
    r.rss_memory_mb,
    r.vms_memory_mb,
    
    -- ========================================================================
    -- 13. MSR & wakeup (from runs)
    -- ========================================================================
    r.wakeup_latency_us,
    r.interrupt_rate,
    r.thermal_throttle_flag,
    
    -- ========================================================================
    -- 14. Token counts (from runs)
    -- ========================================================================
    r.total_tokens,
    r.prompt_tokens,
    r.completion_tokens,
    
    -- ========================================================================
    -- 15. Network latencies (from runs)
    -- ========================================================================
    r.dns_latency_ms,
    r.api_latency_ms,
    r.compute_time_ms,
    
    -- ========================================================================
    -- 16. Network metrics (NEW)
    -- ========================================================================
    r.bytes_sent,
    r.bytes_recv,
    r.tcp_retransmits,
    
    -- ========================================================================
    -- 17. System state (from runs)
    -- ========================================================================
    r.governor,
    r.turbo_enabled,
    r.is_cold_start,
    r.background_cpu_percent,
    r.process_count,
    
    -- ========================================================================
    -- 18. Agentic-specific metrics (from runs)
    -- ========================================================================
    r.planning_time_ms,
    r.execution_time_ms,
    r.synthesis_time_ms,
    r.phase_planning_ratio,
    r.phase_execution_ratio,
    r.phase_synthesis_ratio,
    r.llm_calls,
    r.tool_calls,
    r.tools_used,
    r.steps,
    r.avg_step_time_ms,
    r.complexity_level,
    r.complexity_score,
    
    -- ========================================================================
    -- 19. Sustainability metrics (from runs)
    -- ========================================================================
    r.carbon_g,
    r.water_ml,
    r.methane_mg,
    
    -- ========================================================================
    -- 20. Derived efficiency metrics (from runs)
    -- ========================================================================
    r.energy_per_instruction,
    r.energy_per_cycle,
    r.energy_per_token,
    r.instructions_per_token,
    r.interrupts_per_second,
    
    -- ========================================================================
    -- 21. Baseline data (from idle_baselines)
    -- ========================================================================
    ib.package_power_watts AS baseline_package_power,
    ib.core_power_watts AS baseline_core_power,
    ib.uncore_power_watts AS baseline_uncore_power,
    ib.dram_power_watts AS baseline_dram_power,
    ib.governor AS baseline_governor,
    ib.turbo AS baseline_turbo,
    ib.background_cpu AS baseline_background_cpu,
    ib.process_count AS baseline_process_count,
    
    -- ========================================================================
    -- 22. Tax summary (target variable)
    -- ========================================================================
    ots.orchestration_tax_uj / 1e6 AS orchestration_tax_j,
    ots.tax_percent,
    
    -- ========================================================================
    -- 23. Cryptographic run state hash
    -- ========================================================================
    r.run_state_hash
    
FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
LEFT JOIN hardware_config h ON r.hw_id = h.hw_id
LEFT JOIN environment_config env ON e.env_id = env.env_id
LEFT JOIN idle_baselines ib ON r.baseline_id = ib.baseline_id
LEFT JOIN orchestration_tax_summary ots ON r.run_id = ots.agentic_run_id;
"""
# ========================================================================
# View: orchestration_analysis - Derived metrics for tax calculation
# ========================================================================
CREATE_ORCHESTRATION_ANALYSIS = """
CREATE VIEW IF NOT EXISTS orchestration_analysis AS
SELECT 
    r.run_id,
    r.exp_id,
    r.workflow_type,
    r.run_number,
    
    -- Raw energies (Joules)
    r.pkg_energy_uj/1e6 as pkg_energy_j,
    r.core_energy_uj/1e6 as core_energy_j,
    r.uncore_energy_uj/1e6 as uncore_energy_j,
    r.dram_energy_uj/1e6 as dram_energy_j,
    
    -- Timing
    r.duration_ns/1e9 as duration_sec,
    
    -- Baseline values (idle energy during run)
    ib.package_power_watts * (r.duration_ns/1e9) as baseline_pkg_j,
    ib.core_power_watts * (r.duration_ns/1e9) as baseline_core_j,
    ib.uncore_power_watts * (r.duration_ns/1e9) as baseline_uncore_j,
    
    -- Derived metrics (YOUR FORMULAS!)
    (r.pkg_energy_uj/1e6) - (ib.package_power_watts * (r.duration_ns/1e9)) as workload_energy_j,
    (r.core_energy_uj/1e6) - (ib.core_power_watts * (r.duration_ns/1e9)) as reasoning_energy_j,
    (r.uncore_energy_uj/1e6) - (ib.uncore_power_watts * (r.duration_ns/1e9)) as orchestration_tax_j,
    
    -- Efficiency metrics
    ((r.core_energy_uj/1e6) - (ib.core_power_watts * (r.duration_ns/1e9))) / 
        (r.instructions/1e9) as joules_per_billion_instructions,
    r.instructions * 1.0 / r.cycles as ipc,
    r.cache_misses * 1.0 / r.cache_references as cache_miss_rate,
    
    -- Ratios (what proportion of energy went where?)
    CASE 
        WHEN (r.pkg_energy_uj/1e6) > 0 
        THEN (r.core_energy_uj/1e6) / (r.pkg_energy_uj/1e6) 
        ELSE 0 
    END as core_share,
    
    CASE 
        WHEN (r.pkg_energy_uj/1e6) > 0 
        THEN (r.uncore_energy_uj/1e6) / (r.pkg_energy_uj/1e6) 
        ELSE 0 
    END as uncore_share,
    
    -- Metadata
    e.provider,
    e.task_name,
    e.country_code

FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
JOIN idle_baselines ib ON r.baseline_id = ib.baseline_id
WHERE r.baseline_id IS NOT NULL;
"""

# ========================================================================
# Table: task_categories - Task to category mapping for analysis
# ========================================================================
TASK_CATEGORIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_categories (
    task_id TEXT PRIMARY KEY,
    category TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_categories_id ON task_categories(task_id);
"""
# Add new columns to hardware_config table
CREATE_HARDWARE_CONFIG = """
CREATE TABLE IF NOT EXISTS hardware_config (
    hw_id INTEGER PRIMARY KEY AUTOINCREMENT,
    hardware_hash TEXT UNIQUE,              
    hostname TEXT,
    cpu_model TEXT,
    cpu_cores INTEGER,
    cpu_threads INTEGER,
    cpu_architecture TEXT,                  
    cpu_vendor TEXT,                         
    cpu_family INTEGER,                      
    cpu_model_id INTEGER,                    
    cpu_stepping INTEGER,                    
    has_avx2 BOOLEAN,                        
    has_avx512 BOOLEAN,                      
    has_vmx BOOLEAN,                         
    gpu_model TEXT,                          
    gpu_driver TEXT,                          
    gpu_count INTEGER,                        
    gpu_power_available BOOLEAN,              
    ram_gb REAL,
    kernel_version TEXT,
    microcode_version TEXT,
    rapl_domains TEXT,
    rapl_has_dram BOOLEAN,                   
    rapl_has_uncore BOOLEAN,                  
    system_manufacturer TEXT,                 
    system_product TEXT,                      
    system_type TEXT,                         
    virtualization_type TEXT,                  
    detected_at TIMESTAMP,                    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# Add environment_config table (NEW)
CREATE_ENVIRONMENT_CONFIG = """
CREATE TABLE IF NOT EXISTS environment_config (
    env_id INTEGER PRIMARY KEY AUTOINCREMENT,
    env_hash TEXT UNIQUE,
    python_version TEXT,
    python_implementation TEXT,
    os_name TEXT,
    os_version TEXT,
    kernel_version TEXT,
    llm_framework TEXT,
    framework_version TEXT,
    git_commit TEXT,
    git_branch TEXT,
    git_dirty BOOLEAN,
    numpy_version TEXT,
    torch_version TEXT,
    transformers_version TEXT,
    container_runtime TEXT,
    container_image TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""
# ========================================================================
# Table: llm_interactions - Store prompts, responses, and per-call metrics
# ========================================================================
CREATE_LLM_INTERACTIONS = """
CREATE TABLE IF NOT EXISTS llm_interactions (
    interaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    step_index INTEGER,
    workflow_type TEXT,
    prompt TEXT,
    response TEXT,
    model_name TEXT,
    provider TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    
    -- Existing (keep)
    api_latency_ms REAL,
    compute_time_ms REAL,
    
    -- Renamed
    app_throughput_kbps REAL,
    
    -- NEW columns
    total_time_ms REAL,
    preprocess_ms REAL,
    non_local_ms REAL,
    local_compute_ms REAL,
    postprocess_ms REAL,
    cpu_percent_during_wait REAL,
    ttft_ms REAL,                        -- time to first token in ms (MEASURED)
    tpot_ms REAL,                        -- time per output token in ms (CALCULATED)
    token_throughput REAL,               -- tokens/sec during decode (CALCULATED)
    streaming_enabled INTEGER DEFAULT 0, -- 1 if streaming was used (SYSTEM)
    first_token_time_ns INTEGER,         -- epoch ns of first token arrival (MEASURED)
    last_token_time_ns INTEGER,          -- epoch ns of last token arrival (MEASURED)
    prefill_energy_uj INTEGER,           -- RAPL energy during prefill phase (CALCULATED)    
    bytes_sent_approx INTEGER,
    bytes_recv_approx INTEGER,
    tcp_retransmits INTEGER,
    error_message TEXT,
    status TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_llm_run ON llm_interactions(run_id);
CREATE INDEX IF NOT EXISTS idx_llm_workflow ON llm_interactions(workflow_type);
"""
# ========================================================================
# Table: IO_SAMPLES 
# ========================================================================
CREATE_IO_SAMPLES = """
CREATE TABLE IF NOT EXISTS io_samples (
    sample_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL,
    sample_start_ns  INTEGER NOT NULL,
    sample_end_ns    INTEGER NOT NULL,
    interval_ns      INTEGER NOT NULL,
    device           TEXT,
    disk_read_bytes  BIGINT,
    disk_write_bytes BIGINT,
    io_block_time_ms REAL,
    disk_latency_ms  REAL,
    minor_page_faults INTEGER,
    major_page_faults INTEGER,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
"""
CREATE_ENERGY_ATTRIBUTION = """
CREATE TABLE IF NOT EXISTS energy_attribution (
    run_id                          INTEGER PRIMARY KEY,
    pkg_energy_uj                   BIGINT,
    core_energy_uj                  BIGINT,
    dram_energy_uj                  BIGINT,
    uncore_energy_uj                BIGINT,
    background_energy_uj            BIGINT,
    interrupt_energy_uj             BIGINT,
    scheduler_energy_uj             BIGINT,
    network_wait_energy_uj          BIGINT,
    io_wait_energy_uj               BIGINT,
    disk_energy_uj                  BIGINT,
    memory_pressure_energy_uj       BIGINT,
    cache_dram_energy_uj            BIGINT,
    orchestration_energy_uj         BIGINT,
    planning_energy_uj              BIGINT,
    execution_energy_uj             BIGINT,
    synthesis_energy_uj             BIGINT,
    tool_energy_uj                  BIGINT,
    retry_energy_uj                 BIGINT,
    failed_tool_energy_uj           BIGINT,
    rejected_generation_energy_uj   BIGINT,
    llm_compute_energy_uj           BIGINT,
    prefill_energy_uj               BIGINT,
    decode_energy_uj                BIGINT,
    energy_per_completion_token_uj  REAL,
    energy_per_successful_step_uj   REAL,
    energy_per_accepted_answer_uj   REAL,
    energy_per_solved_task_uj       REAL,
    thermal_penalty_energy_uj       BIGINT,
    thermal_penalty_time_ms         REAL,
    unattributed_energy_uj          BIGINT,
    attribution_coverage_pct        REAL,
    attribution_model_version       TEXT DEFAULT 'v1',
    llm_wait_energy_uj              BIGINT DEFAULT 0,
    attribution_method              TEXT DEFAULT 'cpu_fraction_v1',
    ml_model_version                TEXT DEFAULT NULL,
    ttft_ms                         REAL DEFAULT NULL,
    tpot_ms                         REAL DEFAULT NULL,    
    created_at                      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at                      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_energy_attribution_run
    ON energy_attribution(run_id);
"""
 
# =============================================================================
# Chunk 6: Normalization Factors Table
# =============================================================================
 
CREATE_NORMALIZATION_FACTORS = """
CREATE TABLE IF NOT EXISTS normalization_factors (
    run_id                  INTEGER PRIMARY KEY,
    difficulty_score        REAL,
    difficulty_bucket       TEXT,
    task_category           TEXT,
    workload_type           TEXT,
    max_step_depth          INTEGER,
    branching_factor        REAL,
    input_tokens            INTEGER,
    output_tokens           INTEGER,
    context_window_size     INTEGER,
    total_work_units        REAL,
    successful_goals        INTEGER,
    attempted_goals         INTEGER,
    failed_attempts         INTEGER,
    retry_depth             INTEGER,
    total_retries           INTEGER,
    total_failures          INTEGER,
    total_tool_calls        INTEGER,
    failed_tool_calls       INTEGER,
    hallucination_count     INTEGER,
    hallucination_rate      REAL,
    rss_memory_gb           REAL,
    cache_miss_rate         REAL,
    io_wait_ratio           REAL,
    stall_time_ms           REAL,
    sla_violations          INTEGER,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_normalization_factors_run
    ON normalization_factors(run_id);
CREATE INDEX IF NOT EXISTS idx_normalization_factors_difficulty
    ON normalization_factors(difficulty_bucket, task_category);
"""
 
# =============================================================================
# Chunk 6: Normalisation Views
# =============================================================================
 
CREATE_NORMALIZATION_VIEWS = """
CREATE VIEW IF NOT EXISTS v_energy_normalized AS
SELECT
    a.run_id,
    r.workflow_type,
    r.complexity_level,
    a.pkg_energy_uj  / 1e6 AS total_energy_j,
    a.core_energy_uj / 1e6 AS compute_energy_j,
    a.dram_energy_uj / 1e6 AS memory_energy_j,
    (a.pkg_energy_uj - COALESCE(a.background_energy_uj, 0)) / 1e6 AS foreground_energy_j,
    a.pkg_energy_uj / NULLIF(l.total_tokens, 0) AS energy_per_token_uj,
    a.pkg_energy_uj / 1e6 / NULLIF(CAST(r.duration_ns AS REAL) / 1e9, 0) AS avg_power_watts,
    a.orchestration_energy_uj / NULLIF(CAST(a.pkg_energy_uj AS REAL), 0) AS orchestration_ratio,
    a.llm_compute_energy_uj / NULLIF(CAST(a.orchestration_energy_uj AS REAL), 0) AS compute_vs_overhead_ratio,
    a.unattributed_energy_uj / NULLIF(CAST(a.pkg_energy_uj AS REAL), 0) AS unattributed_ratio,
    a.attribution_coverage_pct,
    a.energy_per_completion_token_uj,
    a.energy_per_successful_step_uj,
    a.energy_per_accepted_answer_uj,
    a.energy_per_solved_task_uj,
    a.thermal_penalty_energy_uj / 1e6 AS thermal_penalty_j,
    a.thermal_penalty_time_ms,
    r.duration_ns / 1e6 AS duration_ms,
    l.total_tokens,
    l.completion_tokens
FROM energy_attribution a
JOIN runs r ON a.run_id = r.run_id
LEFT JOIN (
    SELECT run_id, SUM(total_tokens) AS total_tokens,
           SUM(completion_tokens) AS completion_tokens
    FROM llm_interactions GROUP BY run_id
) l ON a.run_id = l.run_id;
 
CREATE VIEW IF NOT EXISTS v_attribution_summary AS
SELECT
    a.run_id,
    r.workflow_type,
    a.pkg_energy_uj          / 1e6  AS total_j,
    a.core_energy_uj         / 1e6  AS compute_j,
    a.dram_energy_uj         / 1e6  AS memory_j,
    a.background_energy_uj   / 1e6  AS background_j,
    a.network_wait_energy_uj / 1e6  AS network_j,
    a.io_wait_energy_uj      / 1e6  AS io_j,
    a.orchestration_energy_uj/ 1e6  AS orchestration_j,
    a.planning_energy_uj     / 1e6  AS planning_j,
    a.execution_energy_uj    / 1e6  AS execution_j,
    a.synthesis_energy_uj    / 1e6  AS synthesis_j,
    a.llm_compute_energy_uj  / 1e6  AS llm_compute_j,
    a.thermal_penalty_energy_uj / 1e6 AS thermal_penalty_j,
    a.unattributed_energy_uj / 1e6  AS unattributed_j,
    ROUND(a.core_energy_uj          * 100.0 / NULLIF(a.pkg_energy_uj, 0), 2) AS compute_pct,
    ROUND(a.dram_energy_uj          * 100.0 / NULLIF(a.pkg_energy_uj, 0), 2) AS memory_pct,
    ROUND(a.background_energy_uj    * 100.0 / NULLIF(a.pkg_energy_uj, 0), 2) AS background_pct,
    ROUND(a.orchestration_energy_uj * 100.0 / NULLIF(a.pkg_energy_uj, 0), 2) AS orchestration_pct,
    ROUND(a.llm_compute_energy_uj   * 100.0 / NULLIF(a.pkg_energy_uj, 0), 2) AS application_pct,
    ROUND(a.unattributed_energy_uj  * 100.0 / NULLIF(a.pkg_energy_uj, 0), 2) AS unattributed_pct,
    a.attribution_coverage_pct,
    a.attribution_model_version
FROM energy_attribution a
JOIN runs r ON a.run_id = r.run_id;
"""


# ========================================================================
# View : ml_view - analytical view that flattens runs and llm_interactions for ML modeling
# ========================================================================
CREATE_RESEARCH_METRICS_VIEW = """
CREATE VIEW IF NOT EXISTS research_metrics_view AS
SELECT 
    r.run_id,
    r.exp_id,
    e.provider,
    r.workflow_type,
    r.duration_ns / 1e6 AS total_time_ms,
    r.compute_time_ms,
    r.orchestration_cpu_ms,
    r.bytes_sent AS total_bytes_sent,
    r.bytes_recv AS total_bytes_recv,
    
    COALESCE(i.total_wait_ms, 0) AS total_wait_ms,
    COALESCE(i.total_llm_compute_ms, 0) AS total_llm_compute_ms,
    
    CASE WHEN r.duration_ns > 0 THEN r.orchestration_cpu_ms * 1.0 / (r.duration_ns / 1e6) ELSE 0 END AS ooi_time,
    CASE WHEN r.compute_time_ms > 0 THEN r.orchestration_cpu_ms * 1.0 / r.compute_time_ms ELSE 0 END AS ooi_cpu,
    CASE WHEN r.duration_ns > 0 THEN COALESCE(i.total_llm_compute_ms, 0) * 1.0 / (r.duration_ns / 1e6) ELSE 0 END AS ucr,
    CASE WHEN r.duration_ns > 0 THEN COALESCE(i.total_wait_ms, 0) * 1.0 / (r.duration_ns / 1e6) ELSE 0 END AS network_ratio

FROM runs r
JOIN experiments e ON r.exp_id = e.exp_id
LEFT JOIN (
    SELECT 
        run_id, 
        SUM(non_local_ms) AS total_wait_ms,
        SUM(local_compute_ms) AS total_llm_compute_ms
    FROM llm_interactions
    GROUP BY run_id
) i ON r.run_id = i.run_id
WHERE (i.total_llm_compute_ms > 0 OR i.total_wait_ms > 0)
  AND (r.orchestration_cpu_ms <= r.compute_time_ms * 5);

"""

ENERGY_SAMPLES_WITH_POWER_VIEW = """
CREATE VIEW IF NOT EXISTS energy_samples_with_power AS
SELECT 
    e1.sample_id,
    e1.run_id,
    e1.timestamp_ns / 1e9 AS time_s,
    e1.pkg_energy_uj,
    e1.core_energy_uj,
    e1.uncore_energy_uj,
    e1.dram_energy_uj,
    -- Power (watts) = Δenergy (µJ) / Δtime (seconds) / 1e6
    (e1.pkg_energy_uj - e2.pkg_energy_uj) / ((e1.timestamp_ns - e2.timestamp_ns) / 1e9) / 1e6 AS pkg_power_watts,
    (e1.core_energy_uj - e2.core_energy_uj) / ((e1.timestamp_ns - e2.timestamp_ns) / 1e9) / 1e6 AS core_power_watts,
    (e1.uncore_energy_uj - e2.uncore_energy_uj) / ((e1.timestamp_ns - e2.timestamp_ns) / 1e9) / 1e6 AS uncore_power_watts,
    (e1.dram_energy_uj - e2.dram_energy_uj) / ((e1.timestamp_ns - e2.timestamp_ns) / 1e9) / 1e6 AS dram_power_watts
FROM energy_samples e1
LEFT JOIN energy_samples e2 ON e1.run_id = e2.run_id 
    AND e2.timestamp_ns = (
        SELECT MAX(timestamp_ns) 
        FROM energy_samples e3 
        WHERE e3.run_id = e1.run_id AND e3.timestamp_ns < e1.timestamp_ns
    )
WHERE e2.timestamp_ns IS NOT NULL
ORDER BY e1.run_id, e1.timestamp_ns;
"""

# ============================================================
# METHODOLOGY & PROVENANCE TABLES
# ============================================================

CREATE_MEASUREMENT_METHOD_REGISTRY = """
CREATE TABLE IF NOT EXISTS measurement_method_registry (
    id                    TEXT        PRIMARY KEY,
    name                  TEXT        NOT NULL,
    version               TEXT        DEFAULT '1.0',
    description           TEXT        NOT NULL,
    formula_latex         TEXT,
    code_snapshot         TEXT,
    code_language         TEXT        DEFAULT 'python',
    code_version          TEXT,
    parameters            TEXT,
    output_metric         TEXT,
    output_unit           TEXT,
    provenance            TEXT        DEFAULT 'MEASURED',
    layer                 TEXT,
    applicable_on         TEXT        DEFAULT '["any"]',
    fallback_method_id    TEXT,
    validated             INTEGER     DEFAULT 0,
    confidence            REAL        DEFAULT 1.0,  -- confidence score 0.0-1.0
    validated_by          TEXT,
    validated_date        TEXT,
    active                INTEGER     DEFAULT 1,
    deprecated_reason     TEXT,
    created_at            REAL        DEFAULT (unixepoch()),
    updated_at            REAL        DEFAULT (unixepoch())
);
"""

CREATE_METHOD_REFERENCES = """
CREATE TABLE IF NOT EXISTS method_references (
    id              INTEGER     PRIMARY KEY AUTOINCREMENT,
    method_id       TEXT        NOT NULL,
    ref_type        TEXT        NOT NULL,
    title           TEXT        NOT NULL,
    authors         TEXT,
    year            INTEGER,
    venue           TEXT,
    doi             TEXT,
    url             TEXT,
    relevance       TEXT,
    cited_text      TEXT,
    page_or_section TEXT,
    created_at      TEXT        DEFAULT (datetime('now'))
);
"""

CREATE_MEASUREMENT_METHODOLOGY = """
CREATE TABLE IF NOT EXISTS measurement_methodology (
    id                    INTEGER     PRIMARY KEY AUTOINCREMENT,
    run_id                INTEGER     NOT NULL,
    metric_id             TEXT        NOT NULL,
    method_id             TEXT,
    parameters_used       TEXT,
    value_raw             REAL,
    value_unit            TEXT,
    provenance            TEXT        NOT NULL,
    hw_available          INTEGER,
    confidence            REAL,
    primary_method_failed INTEGER     DEFAULT 0,
    failure_reason        TEXT,
    standard_ids          TEXT,
    captured_at           REAL        DEFAULT (unixepoch())
);
"""

CREATE_METRIC_DISPLAY_REGISTRY = """
CREATE TABLE IF NOT EXISTS metric_display_registry (
    id                    TEXT        PRIMARY KEY,
    label                 TEXT        NOT NULL,
    description           TEXT,
    category              TEXT,
    layer                 TEXT,
    layer_order           INTEGER,
    method_id             TEXT,
    unit_default          TEXT,
    unit_options          TEXT,
    unit_scales           TEXT,
    chart_type            TEXT        DEFAULT 'kpi',
    color_token           TEXT        DEFAULT 'accent.silicon',
    significance          TEXT        DEFAULT 'supporting',
    direction             TEXT        DEFAULT 'lower_is_better',
    display_precision     INTEGER     DEFAULT 2,
    warn_threshold        REAL,
    severe_threshold      REAL,
    threshold_unit        TEXT,
    visible_in            TEXT        DEFAULT '["workbench"]',
    default_visible       INTEGER     DEFAULT 1,
    leaderboard           INTEGER     DEFAULT 0,
    provenance_expected   TEXT        DEFAULT 'MEASURED',
    source_yaml           TEXT,
    goal_id               TEXT,
    active                INTEGER     DEFAULT 1,
    sort_order            INTEGER     DEFAULT 0,
    created_at            REAL        DEFAULT (unixepoch()),
    updated_at            REAL        DEFAULT (unixepoch())
);
"""

CREATE_QUERY_REGISTRY = """
CREATE TABLE IF NOT EXISTS query_registry (
    id                    TEXT        PRIMARY KEY,
    name                  TEXT        NOT NULL,
    description           TEXT,
    metric_type           TEXT        NOT NULL,
    sql_text              TEXT,
    sql_file              TEXT,
    dialect_aware         INTEGER     DEFAULT 0,
    returns               TEXT        DEFAULT 'rows',
    depends_on            TEXT,
    formula               TEXT,
    endpoint_path         TEXT,
    group_name            TEXT        DEFAULT 'analytics',
    parameters            TEXT        DEFAULT '{}',
    enrich_metrics        INTEGER     DEFAULT 0,
    cache_ttl_sec         INTEGER     DEFAULT 30,
    active                INTEGER     DEFAULT 1,
    created_at            TEXT        DEFAULT (datetime('now')),
    updated_at            TEXT        DEFAULT (datetime('now'))
);
"""

CREATE_STANDARDIZATION_REGISTRY = """
CREATE TABLE IF NOT EXISTS standardization_registry (
    id                    INTEGER     PRIMARY KEY AUTOINCREMENT,
    standard_id           TEXT        NOT NULL UNIQUE,
    category              TEXT,
    value                 REAL        NOT NULL,
    unit                  TEXT,
    source                TEXT,
    source_url            TEXT,
    valid_from            TEXT,
    valid_until           TEXT,
    version               INTEGER     DEFAULT 1,
    notes                 TEXT,
    created_at            TEXT        DEFAULT (datetime('now'))
);
"""

CREATE_EVAL_CRITERIA = """
CREATE TABLE IF NOT EXISTS eval_criteria (
    id                    INTEGER     PRIMARY KEY AUTOINCREMENT,
    goal_id               TEXT        NOT NULL UNIQUE,
    stat_test             TEXT,
    alpha                 REAL        DEFAULT 0.05,
    effect_size           TEXT,
    min_runs_per_group    INTEGER     DEFAULT 5,
    report_ci             INTEGER     DEFAULT 1,
    ci_level              REAL        DEFAULT 0.95,
    comparison_mode       TEXT        DEFAULT 'relative',
    created_at            TEXT        DEFAULT (datetime('now'))
);
"""

CREATE_COMPONENT_REGISTRY = """
CREATE TABLE IF NOT EXISTS component_registry (
    name                  TEXT        PRIMARY KEY,
    group_name            TEXT,
    description           TEXT,
    props_schema          TEXT,
    data_shape            TEXT        DEFAULT 'flat_row',
    has_3d_twin           TEXT,
    export_pdf            INTEGER     DEFAULT 0,
    export_png            INTEGER     DEFAULT 0,
    export_csv            INTEGER     DEFAULT 0,
    available_in          TEXT        DEFAULT '["workbench"]',
    active                INTEGER     DEFAULT 1
);
"""

CREATE_PAGE_CONFIGS = """
CREATE TABLE IF NOT EXISTS page_configs (
    id                    TEXT        PRIMARY KEY,
    title                 TEXT        NOT NULL,
    slug                  TEXT,
    icon                  TEXT,
    description           TEXT,
    audience              TEXT        DEFAULT '["workbench"]',
    published             INTEGER     DEFAULT 0,
    sort_order            INTEGER     DEFAULT 0,
    created_at            TEXT        DEFAULT (datetime('now')),
    updated_at            TEXT        DEFAULT (datetime('now'))
);
"""

CREATE_PAGE_SECTIONS = """
CREATE TABLE IF NOT EXISTS page_sections (
    id                    INTEGER     PRIMARY KEY AUTOINCREMENT,
    page_id               TEXT        NOT NULL,
    position              INTEGER     NOT NULL,
    component             TEXT        NOT NULL,
    title                 TEXT,
    cols                  INTEGER     DEFAULT 1,
    query_id              TEXT,
    props                 TEXT        DEFAULT '{}',
    visible_in            TEXT        DEFAULT '["workbench"]',
    active                INTEGER     DEFAULT 1
);
"""

CREATE_PAGE_METRIC_CONFIGS = """
CREATE TABLE IF NOT EXISTS page_metric_configs (
    id                    INTEGER     PRIMARY KEY AUTOINCREMENT,
    section_id            INTEGER     NOT NULL,
    metric_id             TEXT        NOT NULL,
    position              INTEGER     NOT NULL,
    label_override        TEXT,
    color_override        TEXT,
    unit_override         TEXT,
    thesis                INTEGER     DEFAULT 0,
    decimals              INTEGER     DEFAULT 2,
    active                INTEGER     DEFAULT 1
);
"""

CREATE_AUDIT_LOG = """
CREATE TABLE IF NOT EXISTS audit_log (
    id                    INTEGER     PRIMARY KEY AUTOINCREMENT,
    run_id                INTEGER,
    event_type            TEXT,
    event_detail          TEXT,
    metric_id             TEXT,
    value_before          TEXT,
    value_after           TEXT,
    hw_context            TEXT,
    logged_at             TEXT        DEFAULT (datetime('now'))
);
"""


CREATE_PAGE_TEMPLATES = """
CREATE TABLE IF NOT EXISTS page_templates (
    id                    TEXT        PRIMARY KEY,
    name                  TEXT        NOT NULL,
    description           TEXT,
    config                TEXT,
    created_at            TEXT        DEFAULT (datetime('now')),
    updated_at            TEXT        DEFAULT (datetime('now'))
);
"""

