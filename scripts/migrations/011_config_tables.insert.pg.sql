-- =============================================================
-- SEED: standardization_registry
-- =============================================================
INSERT INTO standardization_registry 
  (standard_id, category, value, unit, source, valid_from)
VALUES
  ('carbon_intensity_uk_2024','carbon',0.233,'kg_co2_per_kwh','National Grid ESO 2024','2024-01-01'),
  ('datacenter_wue_avg','water',1.5,'l_per_kwh','Industry average WUE','2024-01-01'),
  ('tdp_oracle_vm_vcpu','hardware',15,'watts','Oracle VM vCPU TDP estimate','2024-01-01'),
  ('tdp_i7_1165g7','hardware',28,'watts','Intel i7-1165G7 TDP','2024-01-01')
ON CONFLICT DO NOTHING;
-- =============================================================
-- SEED: query_registry — computed metrics
-- tax_multiple and ooi_time computed server-side
-- UI receives final value, never computes
-- =============================================================
INSERT INTO query_registry 
  (id, name, metric_type, depends_on, formula,
   endpoint_path, group_name, enrich_metrics, active)
VALUES
  ('tax_multiple','Orchestration Tax Multiple',
   'computed',
   '["avg_agentic_j","avg_linear_j"]',
   'avg_agentic_j / avg_linear_j',
   NULL,'analytics',0,1),
 
  ('energy_per_token_uj','Energy per Token µJ',
   'computed',
   '["total_energy_j","avg_tokens","total_runs"]',
   '(total_energy_j * 1000000) / (avg_tokens * total_runs)',
   NULL,'analytics',0,1),
 
  ('ooi_time','OOI Time',
   'computed',
   '["avg_planning_ms","avg_execution_ms","avg_synthesis_ms"]',
   'avg_planning_ms / (avg_planning_ms + avg_execution_ms + avg_synthesis_ms)',
   NULL,'research',0,1)
 ON CONFLICT DO NOTHING;
-- Set overview to enrich with computed metrics
-- (run after inserting overview row from migration script)
-- UPDATE query_registry SET enrich_metrics=1 WHERE id='overview';
 
-- =============================================================
-- SEED: component_registry
-- =============================================================
INSERT INTO component_registry VALUES
  ('HeroBanner','layout','Animated headline + live indicator','{}','none',NULL,0,0,0,'["workbench","showcase"]',1),
  ('KPIStrip','data','6 KPI tiles with count-up','{"columns":{"type":"number","default":6}}','flat_row',NULL,0,1,1,'["workbench","showcase"]',1),
  ('EChartsBar','chart_2d','ECharts bar chart','{"x_key":{"type":"string"},"y_key":{"type":"string"}}','array',NULL,0,1,1,'["workbench","showcase"]',1),
  ('EChartsScatter','chart_2d','ECharts scatter','{}','array',NULL,0,1,1,'["workbench"]',1),
  ('EChartsDualTrace','chart_2d','ECharts dual-axis','{}','array',NULL,0,1,1,'["workbench"]',1),
  ('PhaseBreakdown','data','Stacked phase bar + list','{}','flat_row',NULL,0,1,0,'["workbench","showcase"]',1),
  ('DataHealthBar','data','Data quality flag strip','{}','flat_row',NULL,0,0,0,'["workbench"]',1),
  ('RunsTable','data','Recent runs table','{"limit":{"type":"number","default":10}}','array',NULL,0,0,1,'["workbench"]',1),
  ('TaxChart','chart_2d','Orchestration tax by task','{}','array',NULL,0,1,1,'["workbench","showcase"]',1),
  ('SustainabilityRow','data','Carbon + water row','{}','flat_row',NULL,0,0,0,'["workbench","showcase"]',1),
  ('AttributionExplorer','chart_2d','5-layer energy attribution','{}','array',NULL,0,1,0,'["workbench"]',1),
  ('LensExplorer','chart_2d','Multi-dim parallel coords','{}','array',NULL,0,0,0,'["workbench"]',1),
  ('AgentFlowGraph','chart_3d','ReactFlow decision tree','{}','array',NULL,0,1,0,'["workbench"]',1),
  ('SiliconJourney','chart_3d','Particle attribution journey','{}','none',NULL,0,0,0,'["workbench","showcase"]',1),
  ('FormulaTooltip','ui','KaTeX formula on hover','{}','none',NULL,0,0,0,'["workbench","showcase","commons"]',1),
  ('ProvenanceBadge','ui','MEASURED/CALCULATED/INFERRED badge','{}','none',NULL,0,0,0,'["workbench","showcase","commons"]',1),
  ('GlassCard','ui','Glass morphism card','{}','none',NULL,0,0,0,'["workbench","showcase","commons"]',1),
  ('GhostPlaceholder','utility','Coming soon placeholder','{}','none',NULL,0,0,0,'["workbench"]',1),
  ('KPIGrid','data','Configurable KPI grid','{}','flat_row',NULL,0,1,1,'["workbench"]',1),
  ('EChartsLine','chart_2d','Line/area chart','{}','array',NULL,0,1,1,'["workbench"]',1),
  ('EChartsHeatmap','chart_2d','Heatmap','{}','array',NULL,0,1,1,'["workbench"]',1),
  ('EChartsRadar','chart_2d','Radar chart','{}','array',NULL,0,1,1,'["workbench"]',1),
  ('EChartsBoxplot','chart_2d','Boxplot','{}','array',NULL,0,1,1,'["workbench"]',1),
  ('EChartsPie','chart_2d','Pie/donut','{}','array',NULL,0,1,1,'["workbench"]',1),
  ('SessionTree','data','Session hierarchy tree','{}','array',NULL,0,0,0,'["workbench"]',1),
  ('GoalsPage','data','Research goals + hypotheses','{}','array',NULL,0,0,0,'["workbench"]',1),
  ('NormalizationView','data','5-mode normalization toggle','{}','array',NULL,0,1,0,'["workbench"]',1),
  ('ValidationLayer','data','Run validity matrix','{}','array',NULL,0,0,1,'["workbench"]',1),
  ('DrillDownModal','ui','Metric drilldown with KaTeX','{}','flat_row',NULL,0,0,0,'["workbench"]',1),
  ('UniverseNav','chart_3d','3D galaxy navigation','{}','none',NULL,0,0,0,'["workbench"]',1),
  ('GalaxyShader','chart_3d','WebGL shader galaxy','{}','none',NULL,0,0,0,'["workbench"]',1),
  ('LiveRunMonitor','data','SSE live run stream','{}','timeseries',NULL,0,0,0,'["workbench"]',1),
  ('ModelLeaderboard','data','Multi-dim model comparison','{}','array',NULL,0,1,1,'["workbench","showcase","commons"]',1),
  ('ExperimentCompare','data','A vs B run diff','{}','array',NULL,0,1,0,'["workbench"]',1),
  ('PhaseSwimLane','chart_2d','Horizontal phase timeline','{}','array',NULL,0,1,0,'["workbench"]',1),
  ('ExecutionTimeline3D','chart_3d','3D Gantt chart','{}','array',NULL,0,1,0,'["workbench"]',1),
  ('SQLConsole','utility','Ad-hoc SQL research tool','{}','none',NULL,0,0,0,'["workbench"]',1),
  ('HardwareProfile','data','Hardware config card','{}','flat_row',NULL,0,0,0,'["workbench"]',1),
  ('ResearchInsights','data','Research question explorer','{}','array',NULL,0,0,0,'["workbench"]',1),
  ('EnergyCompareCard','hybrid','Linear vs agentic split card','{}','flat_row',NULL,0,1,0,'["workbench","showcase"]',1),
  ('TaxMultiplierCard','hybrid','Tax multiplier horizontal bars','{}','array',NULL,0,1,0,'["workbench","showcase"]',1),
  ('PhaseBreakdownCard','hybrid','Phase stacked bar + list','{}','flat_row',NULL,0,1,0,'["workbench","showcase"]',1),
  ('TaxAttributionCard','hybrid','Attribution text + bars','{}','flat_row',NULL,0,1,0,'["workbench","showcase"]',1),
  ('EnergyTimelineCard','hybrid','Phase-colored timeline chart','{}','array',NULL,0,1,0,'["workbench","showcase"]',1),
  ('SessionListCard','hybrid','Session list + status badges','{}','array',NULL,0,0,0,'["workbench"]',1),
  ('HeroStatBanner','hybrid','Animated headline + live dot','{}','flat_row',NULL,0,0,0,'["workbench","showcase"]',1)
  ON CONFLICT (name) DO NOTHING;