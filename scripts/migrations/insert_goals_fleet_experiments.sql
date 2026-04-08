-- =============================================================================
-- insert_goals_fleet_experiments.sql
-- Sections for goals, fleet, experiments pages.
-- Run: sqlite3 data/experiments.db < scripts/migrations/insert_goals_fleet_experiments.sql
-- =============================================================================

-- ── GOALS PAGE ────────────────────────────────────────────────────────────────
DELETE FROM page_sections WHERE page_id='goals';

INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active)
VALUES
  ('goals',1,'HeroBanner','overview',NULL,'{}',1,1),
  ('goals',2,'SubgoalTree','goals','Research Programme',
   '{"expanded_first":true}',1,1),
  ('goals',3,'SustainabilityRow','overview','Sustainability Metrics','{}',1,1);

-- ── FLEET PAGE ────────────────────────────────────────────────────────────────
DELETE FROM page_sections WHERE page_id='fleet';

INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active)
VALUES
  ('fleet',1,'HeroBanner','overview',NULL,'{}',1,1),
  ('fleet',2,'LiveRunMonitor',NULL,'Live Run Monitor','{"limit":5,"interval":10000}',1,1),
  ('fleet',3,'HardwareProfile','hardware','Hardware Configurations','{}',1,1),
  ('fleet',4,'DataHealthBar','overview',NULL,'{}',1,1);

-- ── EXPERIMENTS PAGE ──────────────────────────────────────────────────────────
DELETE FROM page_sections WHERE page_id='experiments';

INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active)
VALUES
  ('experiments',1,'HeroBanner','overview',NULL,'{}',1,1),
  ('experiments',2,'KPIStrip','overview',NULL,'{"columns":6}',1,1),
  ('experiments',3,'ExperimentCompare','overview',NULL,'{}',2,1),
  ('experiments',4,'TaxMultiplierCard','tax_by_task',NULL,'{}',2,1),
  ('experiments',5,'ModelLeaderboard','model_comparison','Model Energy Leaderboard','{}',1,1),
  ('experiments',6,'RunsTable','recent_runs','All Runs','{"limit":15}',1,1);

-- ── SESSIONS PAGE ─────────────────────────────────────────────────────────────
DELETE FROM page_sections WHERE page_id='sessions';

INSERT INTO page_sections (page_id,position,component,query_id,title,props,cols,active)
VALUES
  ('sessions',1,'HeroBanner','overview',NULL,'{}',1,1),
  ('sessions',2,'KPIStrip','overview',NULL,'{"columns":4}',1,1),
  ('sessions',3,'EChartsBar','sessions','Session Energy Overview',
   '{"x_key":"group_id","y_key":"total_energy_j","height":280}',1,1),
  ('sessions',4,'SessionListCard','sessions','Recent Sessions','{"limit":10}',1,1),
  ('sessions',5,'RunsTable','recent_runs','Recent Runs','{"limit":8}',1,1);

-- ── REGISTER NEW COMPONENTS ───────────────────────────────────────────────────
INSERT OR REPLACE INTO component_registry
  (name, category, description, props_schema, active)
VALUES
  ('SubgoalTree','goals',
   '8 research subgoals with status, formula, progress — click to expand',
   '{"optional":["expanded_first"]}',1),

  ('HardwareProfile','fleet',
   'Hardware config cards — CPU, RAM, RAPL domains, measurement capabilities',
   '{}',1),

  ('LiveRunMonitor','fleet',
   'Real-time run status — polls /analytics/recent_runs every N seconds',
   '{"optional":["limit","interval"]}',1),

  ('ModelLeaderboard','experiments',
   'Model energy leaderboard — 9 dimensions, sortable columns',
   '{}',1),

  ('ExperimentCompare','experiments',
   'Linear vs Agentic energy comparison with split bar and formulas',
   '{}',1),

  ('ExperimentCompare','experiments',
   'A vs B energy diff card',
   '{}',1);

-- ── ADD hardware query to query_registry ─────────────────────────────────────
INSERT OR IGNORE INTO query_registry
  (id, name, metric_type, sql_text, endpoint_path, returns, group_name, active)
VALUES
  ('hardware', 'Hardware Configs', 'sql_rows',
   'SELECT hw_id, name, cpu_model, cpu_cores, ram_gb, os_name,
      rapl_pkg_available AS rapl_pkg,
      rapl_dram_available AS rapl_dram,
      rapl_uncore_available AS rapl_uncore,
      perf_ipc_available AS perf_ipc,
      is_dummy,
      COUNT(r.run_id) AS total_runs,
      AVG(r.total_energy_uj)/1e6 AS avg_energy_j
    FROM hardware_config hc
    LEFT JOIN runs r ON r.hw_id = hc.hw_id
    GROUP BY hc.hw_id
    ORDER BY is_dummy ASC, total_runs DESC',
   '/analytics/hardware', 'rows', 'fleet', 1),

  ('model_comparison', 'Model Comparison', 'sql_rows',
   'SELECT e.model_name, e.provider,
      COUNT(*) AS total_runs,
      AVG(r.total_energy_uj)/1e6 AS avg_energy_j,
      AVG(CASE WHEN r.total_tokens > 0 THEN r.total_energy_uj/r.total_tokens END)/1e6 AS avg_energy_per_token,
      AVG(r.ipc) AS avg_ipc,
      AVG(r.cache_miss_rate)*100 AS avg_cache_miss_pct,
      AVG(r.carbon_g)*1000 AS avg_carbon_mg,
      AVG(r.total_tokens) AS avg_tokens,
      AVG(r.planning_time_ms) AS avg_planning_ms
    FROM runs r
    JOIN experiments e ON r.exp_id = e.exp_id
    WHERE r.experiment_valid = 1
      AND e.model_name IS NOT NULL
    GROUP BY e.model_name, e.provider
    HAVING total_runs >= 3
    ORDER BY avg_energy_per_token ASC NULLS LAST',
   '/analytics/model_comparison', 'rows', 'experiments', 1),

  ('goals', 'Research Goals Status', 'sql_rows',
   'SELECT ec.goal_id AS n, ec.goal_id AS title,
      ec.coverage_pct AS pct,
      ec.status,
      NULL AS formula,
      "CALCULATED" AS prov,
      ec.goal_id AS goal_id,
      ec.coverage_description AS coverage
    FROM eval_criteria ec
    ORDER BY ec.goal_id',
   '/analytics/goals', 'rows', 'goals', 1);

-- =============================================================================
-- VERIFY
-- SELECT page_id, position, component FROM page_sections
--   WHERE page_id IN ('goals','fleet','experiments','sessions')
--   ORDER BY page_id, position;
-- =============================================================================
