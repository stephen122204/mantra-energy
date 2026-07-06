-- s006_analysis_view_config.sql
-- View-to-domain mappings for v_runs_clean_* and v_runs_measured_* views.
-- include_foundation=1 means the view also checks coverage domain validity.
-- Universal, all platforms.
-- Source of truth: GN100 live DB, 2026-07-05.
-- See SPEC_SEED_DATA_COMPLETE.md for classification rules.

INSERT OR IGNORE INTO analysis_view_config
    (view_name, domain_name, include_foundation) VALUES
('energy',        'energy',        1),
('energy',        'gpu_energy',    1),
('energy',        'thermal',       1),
('cpu',           'cpu_perf',      1),
('thermal',       'thermal',       1),
('llm',           'llm_perf',      0),
('orchestration', 'orchestration', 0),
('system',        'system',        1);
