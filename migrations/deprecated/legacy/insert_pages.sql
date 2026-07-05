-- =============================================================================
-- insert_pages.sql
-- Full page configuration for all 10 A-LEMS pages.
-- Run: sqlite3 data/experiments.db < scripts/migrations/insert_pages.sql
-- PG:  psql $DATABASE_URL < scripts/migrations/insert_pages.sql (with ON CONFLICT)
--
-- Who runs this: developer (once, after 010_config_tables.sql)
-- What it does: populates page_configs + page_sections for all pages
-- Safe to re-run: uses INSERT OR REPLACE / DELETE + re-insert pattern
-- =============================================================================

-- Clean slate for all pages (safe — re-runnable)
DELETE FROM page_metric_configs WHERE section_id IN (SELECT id FROM page_sections);
DELETE FROM page_sections;
DELETE FROM page_configs;

-- =============================================================================
-- PAGE 1: OVERVIEW — main dashboard, real energy data
-- =============================================================================
INSERT INTO page_configs (id,title,slug,icon,description,audience,published,sort_order)
VALUES ('overview','Overview','/overview','◈',
  'Main research dashboard — energy KPIs, orchestration tax, phase breakdown, sustainability',
  '["workbench","showcase"]',1,1);

INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active) VALUES
  -- Hero banner — full width, bare (no card wrapper)
  ('overview',1,'HeroBanner','overview',NULL,'{}',1,1),
  -- KPI strip — 6 tiles with count-up
  ('overview',2,'KPIStrip','overview',NULL,'{"columns":6}',1,1),
  -- Data quality bar — bare
  ('overview',3,'DataHealthBar','overview',NULL,'{}',1,1),
  -- Tax chart — ECharts horizontal bar
  ('overview',4,'TaxChart','tax_by_task','Tax by Task','{"height":320}',1,1),
  -- Phase breakdown — agentic phase timing
  ('overview',5,'PhaseBreakdown','overview','Agentic Phase Distribution','{}',1,1),
  -- Sustainability row — carbon + water + methane
  ('overview',6,'SustainabilityRow','overview','Sustainability Footprint','{}',1,1),
  -- Runs table — last 8 runs
  ('overview',7,'RunsTable','recent_runs','Recent Runs','{"limit":8}',1,1);

-- =============================================================================
-- PAGE 2: ATTRIBUTION — 5-layer energy attribution
-- =============================================================================
INSERT INTO page_configs (id,title,slug,icon,description,audience,published,sort_order)
VALUES ('attribution','Attribution','/attribution','🔀',
  '5-layer energy attribution: silicon, OS, orchestration, application, goal',
  '["workbench"]',1,2);

INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active) VALUES
  ('attribution',1,'HeroBanner','overview',NULL,'{}',1,1),
  ('attribution',2,'AttributionExplorer','attribution','Energy Attribution Layers','{}',1,1),
  ('attribution',3,'SiliconJourney','attribution','Silicon → Application Energy Flow','{}',1,1);

-- =============================================================================
-- PAGE 3: RESEARCH — research insights SQL explorer
-- =============================================================================
INSERT INTO page_configs (id,title,slug,icon,description,audience,published,sort_order)
VALUES ('research','Research','/research','🔬',
  'Interactive research questions — SQL-driven, grouped by analysis tab',
  '["workbench"]',1,3);

INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active) VALUES
  ('research',1,'HeroBanner','overview',NULL,'{}',1,1),
  ('research',2,'LensExplorer','lens','Multi-Dimensional Explorer','{}',1,1);

-- =============================================================================
-- PAGE 4: EXPERIMENTS — full experiment table with drilldown
-- =============================================================================
INSERT INTO page_configs (id,title,slug,icon,description,audience,published,sort_order)
VALUES ('experiments','Experiments','/experiments','⚗',
  'All 468 experiments with per-experiment energy, IPC, validity stats',
  '["workbench"]',1,4);

INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active) VALUES
  ('experiments',1,'HeroBanner','overview',NULL,'{}',1,1),
  ('experiments',2,'EChartsBar','domains','Energy by Task Domain',
   '{"x_key":"task_name","y_key":"avg_energy_j","height":300}',1,1),
  ('experiments',3,'RunsTable','recent_runs','All Recent Runs','{"limit":20}',1,1);

-- =============================================================================
-- PAGE 5: VALIDATE — data quality matrix
-- =============================================================================
INSERT INTO page_configs (id,title,slug,icon,description,audience,published,sort_order)
VALUES ('validate','Data Quality','/validate','✅',
  'Run validity matrix — 6 quality checks per run, filter failed runs',
  '["workbench"]',1,5);

INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active) VALUES
  ('validate',1,'HeroBanner','overview',NULL,'{}',1,1),
  ('validate',2,'DataHealthBar','overview',NULL,'{}',1,1),
  ('validate',3,'ValidationLayer','validate','Run Validity Matrix','{}',1,1);

-- =============================================================================
-- PAGE 6: NORMALIZE — 5 normalization modes
-- =============================================================================
INSERT INTO page_configs (id,title,slug,icon,description,audience,published,sort_order)
VALUES ('normalize','Normalization','/normalize','📊',
  'Energy per token, per instruction, per second, carbon — 5 normalization modes',
  '["workbench"]',1,6);

INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active) VALUES
  ('normalize',1,'HeroBanner','overview',NULL,'{}',1,1),
  ('normalize',2,'NormalizationView','normalize','Normalization Explorer','{}',1,1);

-- =============================================================================
-- PAGE 7: SESSIONS — session timeline grouped by group_id
-- =============================================================================
INSERT INTO page_configs (id,title,slug,icon,description,audience,published,sort_order)
VALUES ('sessions','Sessions','/sessions','📂',
  'Session aggregates — grouped experiment runs with energy totals and tax',
  '["workbench"]',1,7);

INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active) VALUES
  ('sessions',1,'HeroBanner','overview',NULL,'{}',1,1),
  ('sessions',2,'EChartsBar','sessions','Session Energy Overview',
   '{"x_key":"group_id","y_key":"total_energy_j","height":280}',1,1),
  ('sessions',3,'RunsTable','sessions','Session Summary','{"limit":15}',1,1);

-- =============================================================================
-- PAGE 8: GOALS — research hypotheses and eval criteria
-- =============================================================================
INSERT INTO page_configs (id,title,slug,icon,description,audience,published,sort_order)
VALUES ('goals','Research Goals','/goals','🎯',
  '8 research subgoals with hypotheses, eval criteria, and current status',
  '["workbench"]',1,8);

INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active) VALUES
  ('goals',1,'HeroBanner','overview',NULL,'{}',1,1),
  ('goals',2,'GhostPlaceholder',NULL,'Research Goals',
   '{"message":"Goals page — SubgoalTree component coming in next sprint","sub":"See goals/*.yaml for full hypothesis definitions"}',1,1);

-- =============================================================================
-- PAGE 9: FLEET — hardware configuration view
-- =============================================================================
INSERT INTO page_configs (id,title,slug,icon,description,audience,published,sort_order)
VALUES ('fleet','Fleet','/fleet','🖥',
  'Hardware profiles — real + dummy configurations for multi-hw comparison',
  '["workbench"]',1,9);

INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active) VALUES
  ('fleet',1,'HeroBanner','overview',NULL,'{}',1,1),
  ('fleet',2,'GhostPlaceholder',NULL,'Fleet Monitor',
   '{"message":"HardwareProfile + LiveRunMonitor coming next sprint","sub":"Hardware data in hardware_config table — 1 real + 4 dummy configs"}',1,1);

-- =============================================================================
-- PAGE 10: PLAYGROUND — visual design system (preserved forever)
-- =============================================================================
INSERT INTO page_configs (id,title,slug,icon,description,audience,published,sort_order)
VALUES ('playground','Playground','/playground','🎨',
  'Visual design system — all 46 components, 7 themes, all backgrounds. Never removed.',
  '["workbench"]',1,99);

-- Playground has NO page_sections — it is a standalone Next.js page
-- src/app/playground/page.tsx is NEVER touched by PageRenderer

-- =============================================================================
-- VERIFY
-- =============================================================================
-- SELECT id, title, published FROM page_configs ORDER BY sort_order;
-- SELECT page_id, position, component, query_id FROM page_sections ORDER BY page_id, position;
