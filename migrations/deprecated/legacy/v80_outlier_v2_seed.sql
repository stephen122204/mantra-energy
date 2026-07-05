-- =============================================================================
-- Migration v80: Purpose-Conditional Outlier Validity (seed data)
-- =============================================================================
-- Companion to v80_outlier_v2_schema.sql. Must run after that file.
-- v80_outlier_v2_views.py must run after this file (view generation reads
-- the tables seeded here).
--
-- MSC-4 compliance: this file is data only (INSERT, UPDATE). No CREATE,
-- no ALTER.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Domain definitions. coverage is the sole foundation domain: it taints
-- energy, gpu_energy, cpu_perf, thermal, timing, and system, because
-- those six domains' values come from the same RAPL/SPBM sampling
-- infrastructure that energy_sample_coverage_pct and
-- spbm_sample_coverage_pct measure the completeness of. llm_perf and
-- orchestration are NOT tainted, because LLM client instrumentation and
-- the orchestration framework are independent measurement paths.
-- -----------------------------------------------------------------------------
INSERT INTO analysis_domain_config (domain_name, is_foundation, description, column_count) VALUES
    ('coverage',      1, 'Sampling completeness. Foundation domain: taints analyses dependent on sampled data.', 5),
    ('energy',        0, 'CPU-side energy measurement, power, timing, SPBM telemetry, environmental impact.', 32),
    ('gpu_energy',    0, 'GPU energy measurement via DCGM and SPBM GPU rail.', 9),
    ('cpu_perf',      0, 'CPU microarchitecture: frequency, IPC, cache, voltage.', 17),
    ('thermal',       0, 'Thermal state, temperatures, throttle events.', 10),
    ('llm_perf',      0, 'LLM interaction performance: tokens, latency. Independent of RAPL/SPBM sampling.', 8),
    ('orchestration', 0, 'Agent orchestration: steps, tools, agent CPU time. Independent of RAPL/SPBM sampling.', 4),
    ('timing',        0, 'Phase timing, ratios, step timing.', 10),
    ('system',        0, 'OS scheduling, memory, swap, network, disk I/O.', 33),
    ('identity',      0, 'Run metadata and config flags. Never outlier-detected.', 24);

-- -----------------------------------------------------------------------------
-- COVERAGE domain (foundation, 5 columns)
-- -----------------------------------------------------------------------------
INSERT INTO metric_analysis_domains (metric_name, domain_name) VALUES
    ('energy_sample_coverage_pct', 'coverage'),
    ('phase_sample_coverage_pct',  'coverage'),
    ('spbm_sample_coverage_pct',   'coverage'),
    ('spbm_samples_expected',      'coverage'),
    ('spbm_samples_observed',      'coverage');

-- -----------------------------------------------------------------------------
-- ENERGY domain (32 columns)
-- -----------------------------------------------------------------------------
INSERT INTO metric_analysis_domains (metric_name, domain_name) VALUES
    ('total_energy_uj',                'energy'),
    ('dynamic_energy_uj',              'energy'),
    ('baseline_energy_uj',             'energy'),
    ('attributed_energy_uj',           'energy'),
    ('framework_overhead_energy_uj',   'energy'),
    ('pkg_energy_uj',                  'energy'),
    ('core_energy_uj',                 'energy'),
    ('uncore_energy_uj',               'energy'),
    ('dram_energy_uj',                 'energy'),
    ('planning_energy_uj',             'energy'),
    ('execution_energy_uj',            'energy'),
    ('synthesis_energy_uj',            'energy'),
    ('inter_phase_energy_uj',          'energy'),
    ('pre_task_energy_uj',             'energy'),
    ('post_task_energy_uj',            'energy'),
    ('rapl_before_pretask_uj',         'energy'),
    ('rapl_after_task_uj',             'energy'),
    ('avg_power_watts',                'energy'),
    ('avg_task_power_watts',           'energy'),
    ('energy_per_token',               'energy'),
    ('carbon_g',                       'energy'),
    ('methane_mg',                     'energy'),
    ('water_ml',                       'energy'),
    ('spbm_conversion_efficiency',     'energy'),
    ('spbm_conversion_loss_uj',        'energy'),
    ('spbm_power_sampling_freq_hz',    'energy'),
    ('duration_ns',                    'energy'),
    ('task_duration_ns',               'energy'),
    ('total_run_duration_ns',          'energy'),
    ('framework_overhead_ns',          'energy'),
    ('pre_task_duration_ns',           'energy'),
    ('post_task_duration_ns',          'energy'),
    ('energy_per_cycle',               'energy'),
    ('energy_per_instruction',         'energy');

-- -----------------------------------------------------------------------------
-- GPU_ENERGY domain (9 columns)
-- -----------------------------------------------------------------------------
INSERT INTO metric_analysis_domains (metric_name, domain_name) VALUES
    ('gpu_total_energy_uj',        'gpu_energy'),
    ('gpu_baseline_energy_uj',     'gpu_energy'),
    ('gpu_dynamic_energy_uj',      'gpu_energy'),
    ('gpu_pct_of_pkg',             'gpu_energy'),
    ('gpu_count',                  'gpu_energy'),
    ('gpu_idle_power_w_used',      'gpu_energy'),
    ('gpu_spbm_total_uj',          'gpu_energy'),
    ('gpu_spbm_dynamic_uj',        'gpu_energy'),
    ('gpu_residual_dynamic_uj',    'gpu_energy');

-- -----------------------------------------------------------------------------
-- CPU_PERF domain (17 columns, includes both cross-domain energy
-- columns that also live in the energy domain above)
-- -----------------------------------------------------------------------------
INSERT INTO metric_analysis_domains (metric_name, domain_name) VALUES
    ('cpu_avg_mhz',                'cpu_perf'),
    ('cpu_busy_mhz',               'cpu_perf'),
    ('frequency_mhz',              'cpu_perf'),
    ('ring_bus_freq_mhz',          'cpu_perf'),
    ('ipc',                        'cpu_perf'),
    ('instructions',               'cpu_perf'),
    ('cycles',                     'cpu_perf'),
    ('cache_references',           'cpu_perf'),
    ('cache_misses',               'cpu_perf'),
    ('cache_miss_rate',            'cpu_perf'),
    ('l1d_cache_misses_total',     'cpu_perf'),
    ('l2_cache_misses_total',      'cpu_perf'),
    ('l3_cache_hits_total',        'cpu_perf'),
    ('l3_cache_misses_total',      'cpu_perf'),
    ('voltage_vcore_avg',          'cpu_perf'),
    ('energy_per_cycle',           'cpu_perf'),
    ('energy_per_instruction',     'cpu_perf'),
    ('instructions_per_token',     'cpu_perf');

-- -----------------------------------------------------------------------------
-- THERMAL domain (10 columns)
-- -----------------------------------------------------------------------------
INSERT INTO metric_analysis_domains (metric_name, domain_name) VALUES
    ('package_temp_celsius',       'thermal'),
    ('baseline_temp_celsius',      'thermal'),
    ('start_temp_c',               'thermal'),
    ('max_temp_c',                 'thermal'),
    ('min_temp_c',                 'thermal'),
    ('thermal_delta_c',            'thermal'),
    ('thermal_during_experiment',  'thermal'),
    ('thermal_now_active',         'thermal'),
    ('thermal_since_boot',         'thermal'),
    ('thermal_throttle_flag',      'thermal');

-- -----------------------------------------------------------------------------
-- LLM_PERF domain (8 columns, NOT tainted by coverage)
-- -----------------------------------------------------------------------------
INSERT INTO metric_analysis_domains (metric_name, domain_name) VALUES
    ('total_tokens',               'llm_perf'),
    ('prompt_tokens',              'llm_perf'),
    ('completion_tokens',          'llm_perf'),
    ('llm_calls',                  'llm_perf'),
    ('ttft_ms',                    'llm_perf'),
    ('tpot_ms',                    'llm_perf'),
    ('api_latency_ms',             'llm_perf'),
    ('instructions_per_token',     'llm_perf');

-- -----------------------------------------------------------------------------
-- ORCHESTRATION domain (4 columns, NOT tainted by coverage)
-- -----------------------------------------------------------------------------
INSERT INTO metric_analysis_domains (metric_name, domain_name) VALUES
    ('steps',                      'orchestration'),
    ('tool_calls',                 'orchestration'),
    ('tools_used',                 'orchestration'),
    ('orchestration_cpu_ms',       'orchestration');

-- -----------------------------------------------------------------------------
-- TIMING domain (10 columns, also includes duration_ns cross-listed
-- under energy above)
-- -----------------------------------------------------------------------------
INSERT INTO metric_analysis_domains (metric_name, domain_name) VALUES
    ('planning_time_ms',           'timing'),
    ('execution_time_ms',          'timing'),
    ('synthesis_time_ms',          'timing'),
    ('avg_step_time_ms',           'timing'),
    ('compute_time_ms',            'timing'),
    ('user_time_ms',               'timing'),
    ('kernel_time_ms',             'timing'),
    ('phase_execution_ratio',      'timing'),
    ('phase_planning_ratio',       'timing'),
    ('phase_synthesis_ratio',      'timing'),
    ('duration_ns',                'timing');

-- -----------------------------------------------------------------------------
-- SYSTEM domain (33 columns)
-- -----------------------------------------------------------------------------
INSERT INTO metric_analysis_domains (metric_name, domain_name) VALUES
    ('cpu_fraction',                       'system'),
    ('background_cpu_percent',             'system'),
    ('context_switches_voluntary',         'system'),
    ('context_switches_involuntary',       'system'),
    ('total_context_switches',             'system'),
    ('thread_migrations',                  'system'),
    ('process_count',                      'system'),
    ('run_queue_length',                   'system'),
    ('wakeup_latency_us',                  'system'),
    ('interrupt_rate',                     'system'),
    ('interrupts_per_second',              'system'),
    ('c2_time_seconds',                    'system'),
    ('c3_time_seconds',                    'system'),
    ('c6_time_seconds',                    'system'),
    ('c7_time_seconds',                    'system'),
    ('rss_memory_mb',                      'system'),
    ('vms_memory_mb',                      'system'),
    ('major_page_faults',                  'system'),
    ('minor_page_faults',                  'system'),
    ('page_faults',                        'system'),
    ('swap_start_used_mb',                 'system'),
    ('swap_start_cached_mb',               'system'),
    ('swap_end_used_mb',                   'system'),
    ('swap_end_cached_mb',                 'system'),
    ('swap_end_free_mb',                   'system'),
    ('swap_end_percent',                   'system'),
    ('swap_total_mb',                      'system'),
    ('bytes_sent',                         'system'),
    ('bytes_recv',                         'system'),
    ('tcp_retransmits',                    'system'),
    ('dns_latency_ms',                     'system'),
    ('disk_read_bytes_total',              'system'),
    ('disk_write_bytes_total',             'system');

-- -----------------------------------------------------------------------------
-- View-to-domain dependency config. Six domain-scoped view families,
-- each producing two views (clean + measured) in v80_outlier_v2_views.py.
-- include_foundation=1 means coverage outliers propagate; =0 means they
-- do not (llm_perf, orchestration are independent of RAPL/SPBM sampling).
-- -----------------------------------------------------------------------------
INSERT INTO analysis_view_config (view_name, domain_name, include_foundation) VALUES
    ('energy',         'energy',     1),
    ('energy',         'gpu_energy', 1),
    ('energy',         'thermal',    1),
    ('cpu',            'cpu_perf',   1),
    ('thermal',         'thermal',   1),
    ('llm',              'llm_perf', 0),
    ('orchestration',     'orchestration', 0),
    ('system',             'system', 1);

-- -----------------------------------------------------------------------------
-- outlier_class for existing outlier_detection_config rows. Coverage
-- floor rules (DR-04, DR-05) and DR-01/DR-02 stay at the DEFAULT
-- data_quality_failure. Thermal throttle (DR-03) and short duration
-- (DR-06) are real events, not measurement errors, so they are
-- statistical_anomaly. mad_zscore and iqr_fence are always
-- statistical_anomaly by definition (they detect unusual-but-plausible
-- values, never measurement failure).
-- -----------------------------------------------------------------------------
UPDATE outlier_detection_config
    SET outlier_class = 'statistical_anomaly'
    WHERE method = 'domain_rule'
      AND metric_name = 'thermal_throttle_flag';

UPDATE outlier_detection_config
    SET outlier_class = 'statistical_anomaly'
    WHERE method = 'domain_rule'
      AND metric_name = 'duration_ns';

UPDATE outlier_detection_config
    SET outlier_class = 'statistical_anomaly'
    WHERE method IN ('mad_zscore', 'iqr_fence');

-- DR-01 (attributed_energy_uj min value) and DR-02 (overhead ratio
-- conservation bound) stay at DEFAULT data_quality_failure, no UPDATE
-- needed for those rows.

-- -----------------------------------------------------------------------------
-- The 22 existing run_outliers rows (all coverage domain_rule
-- violations from the v1 detection run) need no explicit UPDATE. The
-- ALTER TABLE ... DEFAULT 'data_quality_failure' in
-- v80_outlier_v2_schema.sql already set them correctly: coverage gaps
-- are measurement failures, not statistical anomalies.
-- -----------------------------------------------------------------------------
