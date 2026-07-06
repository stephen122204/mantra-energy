-- s005_analysis_domain_config.sql
-- Nine-domain analysis taxonomy. Universal, all platforms.
-- Coverage is the foundational domain (is_foundation=1), independent
-- of llm_perf and orchestration domains.
-- Source of truth: GN100 live DB, 2026-07-05.
-- See SPEC_SEED_DATA_COMPLETE.md for classification rules.

INSERT OR IGNORE INTO analysis_domain_config
    (domain_name, is_foundation, description, column_count) VALUES
('coverage',       1, 'Sampling completeness. Foundation domain: taints analyses dependent on sampled data.',                         5),
('energy',         0, 'CPU-side energy measurement, power, timing, SPBM telemetry, environmental impact.',                           32),
('gpu_energy',     0, 'GPU energy measurement via DCGM and SPBM GPU rail.',                                                          9),
('cpu_perf',       0, 'CPU microarchitecture: frequency, IPC, cache, voltage.',                                                      17),
('thermal',        0, 'Thermal state, temperatures, throttle events.',                                                                10),
('llm_perf',       0, 'LLM interaction performance: tokens, latency. Independent of RAPL/SPBM sampling.',                            8),
('orchestration',  0, 'Agent orchestration: steps, tools, agent CPU time. Independent of RAPL/SPBM sampling.',                       4),
('timing',         0, 'Phase timing, ratios, step timing.',                                                                           10),
('system',         0, 'OS scheduling, memory, swap, network, disk I/O.',                                                             33),
('identity',       0, 'Run metadata and config flags. Never outlier-detected.',                                                       24);
