-- =============================================================================
-- insert_metrics.sql
-- Populates metric_display_registry with all A-LEMS metrics.
-- Derived from: gui/report_engine/goals/*.yaml + research knowledge.
--
-- Run AFTER 010_config_tables.sql and migrate_yaml_to_db.py.
-- Safe to re-run: INSERT OR REPLACE.
--
-- formula_latex: KaTeX syntax — shown in DrillDownPanel on metric click
-- method_id: links to measurement_method_registry (populate via Directus)
-- goal_id: which research goal this metric belongs to
-- significance: thesis_core = highlighted in UI, supporting = normal
-- =============================================================================

-- ── SILICON LAYER — RAPL direct measurements ──────────────────────────────────
INSERT OR REPLACE INTO metric_display_registry
  (id,label,description,category,layer,layer_order,unit_default,chart_type,
   color_token,formula_latex,significance,direction,display_precision,
   provenance_expected,source_description,goal_id,active,sort_order,visible_in)
VALUES
('pkg_energy_j','Package Energy','Total CPU package energy from RAPL sensors',
 'energy','silicon',1,'J','kpi',
 'accent.silicon','E_{pkg} = \sum_{i} RAPL_{pkg,i}',
 'thesis_core','lower_is_better',3,
 'MEASURED','Intel RAPL MSR_PKG_ENERGY_STATUS register',
 'energy_efficiency',1,1,'["workbench","showcase"]'),

('avg_agentic_j','Agentic Mean Energy','Mean package energy per agentic workflow run',
 'energy','silicon',1,'J','kpi',
 'accent.thesis','E_{agentic} = \frac{1}{N_{a}} \sum_{i=1}^{N_a} E_{pkg,i}',
 'thesis_core','lower_is_better',3,
 'MEASURED','RAPL direct — mean across all valid agentic runs',
 'energy_efficiency',1,2,'["workbench","showcase"]'),

('avg_linear_j','Linear Mean Energy','Mean package energy per linear workflow run',
 'energy','silicon',1,'J','kpi',
 'accent.silicon','E_{linear} = \frac{1}{N_l} \sum_{i=1}^{N_l} E_{pkg,i}',
 'thesis_core','lower_is_better',3,
 'MEASURED','RAPL direct — mean across all valid linear runs',
 'energy_efficiency',1,3,'["workbench","showcase"]'),

('dynamic_energy_j','Dynamic Energy','Energy above idle baseline (workload-attributed)',
 'energy','silicon',1,'J','kpi',
 'accent.os','E_{dynamic} = E_{pkg} - E_{idle}',
 'supporting','lower_is_better',3,
 'CALCULATED','PKG energy minus idle baseline (measured pre-run, 30s, 2-sigma)',
 'energy_efficiency',1,4,'["workbench"]'),

-- ── ORCHESTRATION TAX — the thesis metric ────────────────────────────────────
('tax_multiple','Tax Multiple','Ratio of agentic to linear energy — the orchestration tax',
 'orchestration','orchestration',3,'×','kpi',
 'accent.thesis','\tau = \frac{E_{agentic}}{E_{linear}}',
 'thesis_core','lower_is_better',2,
 'CALCULATED','Computed: avg_agentic_j / avg_linear_j from query_registry',
 'energy_efficiency',1,10,'["workbench","showcase","commons"]'),

('avg_tax_j','Mean Tax (J)','Mean energy overhead per agentic run in joules',
 'orchestration','orchestration',3,'J','kpi',
 'accent.thesis','T_j = E_{agentic} - E_{linear}',
 'thesis_core','lower_is_better',3,
 'CALCULATED','Agentic minus paired linear energy from orchestration_tax_summary',
 'orchestration_overhead',1,11,'["workbench","showcase"]'),

('tax_percent','Tax Percentage','Orchestration overhead as percentage of linear energy',
 'orchestration','orchestration',3,'%','bar',
 'accent.thesis','T\% = \frac{E_{agentic} - E_{linear}}{E_{linear}} \times 100',
 'thesis_core','lower_is_better',1,
 'CALCULATED','From orchestration_tax_summary.tax_percent (paired runs only)',
 'orchestration_overhead',1,12,'["workbench","showcase"]'),

-- ── OOI METRICS — Orchestration Overhead Index ────────────────────────────────
('ooi_time','OOI Time','Fraction of wall-clock consumed by orchestration CPU',
 'orchestration','orchestration',3,'ratio','kpi',
 'accent.thesis','OOI_{time} = \frac{t_{orch}}{t_{total}}',
 'thesis_core','lower_is_better',3,
 'CALCULATED','orchestration_cpu_ms / (duration_ns / 1e6) — from research_metrics.sql',
 'orchestration_overhead',1,13,'["workbench","showcase"]'),

('ooi_cpu','OOI CPU','Fraction of active compute consumed by orchestration',
 'orchestration','orchestration',3,'ratio','kpi',
 'accent.thesis','OOI_{cpu} = \frac{t_{orch}}{t_{compute}}',
 'thesis_core','lower_is_better',3,
 'CALCULATED','orchestration_cpu_ms / compute_time_ms from llm_interactions',
 'orchestration_overhead',1,14,'["workbench","showcase"]'),

('ucr','UCR','Useful Compute Ratio — fraction of time on actual LLM inference',
 'orchestration','orchestration',3,'ratio','kpi',
 'accent.silicon','UCR = \frac{t_{LLM}}{t_{total}}',
 'thesis_core','higher_is_better',3,
 'CALCULATED','total_llm_compute_ms / (duration_ns / 1e6)',
 'orchestration_overhead',1,15,'["workbench","showcase"]'),

('network_ratio','Network Wait Ratio','Fraction of time waiting on network (cloud LLM)',
 'orchestration','orchestration',3,'ratio','kpi',
 'accent.warning','NWR = \frac{t_{wait}}{t_{total}}',
 'supporting','lower_is_better',3,
 'CALCULATED','non_local_ms / (duration_ns / 1e6) from llm_interactions',
 'orchestration_overhead',1,16,'["workbench"]'),

-- ── PERFORMANCE METRICS ───────────────────────────────────────────────────────
('avg_ipc','Avg IPC','Instructions per cycle — CPU efficiency indicator',
 'ipc','silicon',1,'','kpi',
 'accent.os','IPC = \frac{N_{instructions}}{N_{cycles}}',
 'supporting','higher_is_better',3,
 'MEASURED','perf_event PERF_COUNT_HW_INSTRUCTIONS / PERF_COUNT_HW_CPU_CYCLES',
 'energy_efficiency',1,20,'["workbench"]'),

('avg_cache_miss_pct','Cache Miss %','L3 cache miss rate — memory pressure indicator',
 'ipc','silicon',1,'%','kpi',
 'accent.warning','\% miss = \frac{N_{LLC\_miss}}{N_{LLC\_access}} \times 100',
 'supporting','lower_is_better',1,
 'MEASURED','perf_event LLC-load-misses / LLC-loads',
 'energy_efficiency',1,21,'["workbench"]'),

-- ── TOKEN METRICS ─────────────────────────────────────────────────────────────
('avg_tokens','Avg Tokens','Mean total tokens (prompt + completion) per run',
 'latency','application',4,'','kpi',
 'accent.orchestration',NULL,
 'supporting','neutral',0,
 'MEASURED','prompt_tokens + completion_tokens from llm_interactions',
 'energy_efficiency',1,30,'["workbench"]'),

('avg_energy_per_token','Energy per Token (J)','Mean joules per token generated',
 'energy','application',4,'J/tok','kpi',
 'accent.application','\epsilon_{token} = \frac{E_{pkg}}{N_{tokens}}',
 'thesis_core','lower_is_better',6,
 'CALCULATED','pkg_energy_uj / total_tokens (from runs table)',
 'energy_efficiency',1,31,'["workbench","showcase","commons"]'),

('energy_per_token_uj','Energy per Token (µJ)','Microjoules per token — more readable unit',
 'energy','application',4,'µJ/tok','kpi',
 'accent.application','\epsilon_{\mu J} = \frac{E_{pkg} \times 10^6}{N_{tokens}}',
 'thesis_core','lower_is_better',3,
 'CALCULATED','Computed by metric_engine: (total_energy_j * 1e6) / (avg_tokens * total_runs)',
 'energy_efficiency',1,32,'["workbench","showcase","commons"]'),

-- ── SUSTAINABILITY METRICS ────────────────────────────────────────────────────
('avg_carbon_mg','Avg CO₂ per Run','Mean CO₂ equivalent per run in milligrams',
 'carbon','application',4,'mg CO₂','kpi',
 'accent.success','C_{run} = E_{pkg} \cdot I_{carbon} \cdot 10^3',
 'thesis_core','lower_is_better',4,
 'CALCULATED','pkg_energy_j × carbon_intensity_uk_2024 (0.233 kg/kWh) / 3.6e6',
 'energy_efficiency',1,40,'["workbench","showcase","commons"]'),

('total_carbon_mg','Total CO₂','Total CO₂ for all runs in dataset',
 'carbon','application',4,'mg CO₂','kpi',
 'accent.success','C_{total} = \sum_{i} E_{pkg,i} \cdot I_{carbon}',
 'supporting','lower_is_better',2,
 'CALCULATED','SUM(carbon_g) * 1000 from runs table',
 'energy_efficiency',1,41,'["workbench"]'),

('avg_water_ml','Avg Water per Run','Mean datacenter water usage per run',
 'carbon','application',4,'mL','kpi',
 'accent.info','W_{run} = E_{pkg} \cdot WUE \cdot 10^3',
 'supporting','lower_is_better',4,
 'CALCULATED','pkg_energy_j × WUE_avg (1.5 L/kWh) / 3600',
 'energy_efficiency',1,42,'["workbench"]'),

-- ── PHASE TIMING METRICS ──────────────────────────────────────────────────────
('avg_planning_ms','Avg Planning Time','Mean agentic planning phase duration',
 'latency','orchestration',3,'ms','kpi',
 'accent.warning',NULL,
 'supporting','lower_is_better',0,
 'MEASURED','planning_time_ms from runs table (agentic only)',
 'orchestration_overhead',1,50,'["workbench"]'),

('avg_execution_ms','Avg Execution Time','Mean agentic execution phase duration',
 'latency','orchestration',3,'ms','kpi',
 'accent.os',NULL,
 'supporting','lower_is_better',0,
 'MEASURED','execution_time_ms from runs table (agentic only)',
 'orchestration_overhead',1,51,'["workbench"]'),

('avg_synthesis_ms','Avg Synthesis Time','Mean agentic synthesis phase duration',
 'latency','orchestration',3,'ms','kpi',
 'accent.silicon',NULL,
 'supporting','lower_is_better',0,
 'MEASURED','synthesis_time_ms from runs table (agentic only)',
 'orchestration_overhead',1,52,'["workbench"]'),

-- ── DATA QUALITY METRICS ──────────────────────────────────────────────────────
('total_runs','Total Runs','Total number of measurement runs in dataset',
 'quality','silicon',1,'','kpi',
 'accent.silicon',NULL,
 'supporting','neutral',0,
 'MEASURED','COUNT(run_id) from runs table',
 NULL,1,60,'["workbench","showcase"]'),

('total_experiments','Total Experiments','Total distinct experiments',
 'quality','silicon',1,'','kpi',
 'accent.silicon',NULL,
 'supporting','neutral',0,
 'MEASURED','COUNT(exp_id) from experiments table',
 NULL,1,61,'["workbench","showcase"]'),

('invalid_runs','Invalid Runs','Runs flagged as invalid (quality threshold failed)',
 'quality','silicon',1,'','kpi',
 'accent.danger',NULL,
 'supporting','lower_is_better',0,
 'MEASURED','experiment_valid=0 in runs table',
 NULL,1,62,'["workbench"]'),

('throttled_runs','Throttled Runs','Runs where thermal throttling was detected',
 'quality','silicon',1,'','kpi',
 'accent.warning',NULL,
 'supporting','lower_is_better',0,
 'MEASURED','thermal_throttle_flag=1 in runs table',
 NULL,1,63,'["workbench"]'),

('noisy_env_runs','Noisy Env Runs','Runs with high background CPU > 10%',
 'quality','silicon',1,'','kpi',
 'accent.warning',NULL,
 'supporting','lower_is_better',0,
 'MEASURED','background_cpu_percent > 10 in runs table',
 NULL,1,64,'["workbench"]'),

('no_baseline_runs','No Baseline Runs','Runs without idle baseline measurement',
 'quality','silicon',1,'','kpi',
 'accent.info',NULL,
 'supporting','lower_is_better',0,
 'MEASURED','baseline_id IS NULL in runs table',
 NULL,1,65,'["workbench"]');

-- =============================================================================
-- VERIFY
-- SELECT id, label, significance, formula_latex IS NOT NULL as has_formula
-- FROM metric_display_registry ORDER BY sort_order;
-- =============================================================================
