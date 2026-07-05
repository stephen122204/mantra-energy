-- =============================================================
-- A-LEMS Migration 010 — Config + Methodology Tables
-- Apply to: SQLite (local) + PostgreSQL (central)
--
-- sqlite3 data/experiments.db < migrations/010_config_tables.sql
-- psql $DATABASE_URL < migrations/010_config_tables.sql
--
-- Design rules:
--   formula_latex lives in measurement_method_registry ONLY
--   metric_display_registry.method_id FK points there
--   computed metrics live in query_registry (computed type)
--   UI never computes — only displays
-- =============================================================
 
-- =============================================================
-- 1. MEASUREMENT METHOD REGISTRY
-- METHOD DEFINITIONS — written once by researcher via Directus
-- "How idle baseline works in general"
-- Separate from per-run records (measurement_methodology)
-- =============================================================
CREATE TABLE IF NOT EXISTS measurement_method_registry (
  id                    TEXT        PRIMARY KEY,
  -- e.g. "idle_baseline_cpu_pinning_2sigma"
  --      "energy_per_process_cpu_fraction"
  --      "pkg_energy_rapl_direct"
 
  name                  TEXT        NOT NULL,
  version               TEXT        DEFAULT '1.0',
 
  -- Full prose description (100-500 words)
  -- what it does, why, assumptions, limitations
  description           TEXT        NOT NULL,
 
  -- Formula for display in UI (KaTeX)
  -- SINGLE SOURCE OF TRUTH — metric_display_registry points here
  formula_latex         TEXT,
 
  -- Exact code that implements this method (frozen at design time)
  -- Not a path — the actual text
  code_snapshot         TEXT,
  code_language         TEXT        DEFAULT 'python',
  code_version          TEXT,       -- git commit hash or version tag
 
  -- Exact parameter values this method uses
  parameters            JSONB,
  -- JSON: {"idle_duration_sec":30,"sigma_threshold":2.0,...}
 
  -- What this method produces
  output_metric         TEXT,       -- "idle_baseline_uj"
  output_unit           TEXT,       -- "µJ"
 
  provenance            TEXT        DEFAULT 'MEASURED',
  -- MEASURED | CALCULATED | INFERRED
 
  layer                 TEXT,
  -- silicon | os | orchestration | application
 
  -- Which machines can use this method
  applicable_on         JSONB        DEFAULT '["any"]',
  -- JSON: ["ubuntu_rapl"] or ["any"]
 
  -- If this method fails → use this fallback
  fallback_method_id    TEXT
    REFERENCES measurement_method_registry(id),
 
  -- Validation status
  validated             INTEGER     DEFAULT 0,
  -- 0=internal decision, 1=peer-reviewed methodology
  validated_by          TEXT,
  validated_date        TEXT,
 
  active                INTEGER     DEFAULT 1,
  deprecated_reason     TEXT,
 
  created_at            REAL  DEFAULT EXTRACT(EPOCH FROM NOW()),
  updated_at            REAL  DEFAULT EXTRACT(EPOCH FROM NOW())
);
 
-- =============================================================
-- 2. METHOD REFERENCES
-- Scientific papers, manuals, standards cited by each method
-- Written by researcher when reading and implementing a method
-- =============================================================
CREATE TABLE IF NOT EXISTS method_references (
  id              SERIAL PRIMARY KEY,
  method_id       TEXT        NOT NULL
    REFERENCES measurement_method_registry(id),
 
  ref_type        TEXT        NOT NULL,
  -- paper | manual | standard | datasheet | internal
 
  title           TEXT        NOT NULL,
  authors         TEXT,
  year            INTEGER,
  venue           TEXT,
  doi             TEXT,
  url             TEXT,
 
  -- How this reference applies to the method
  relevance       TEXT,
  -- "RAPL idle measurement — Section 3.2"
 
  -- Key sentence from paper justifying this approach
  -- One sentence only — not a long quote
  cited_text      TEXT,
  page_or_section TEXT,
 
  created_at      REAL  DEFAULT EXTRACT(EPOCH FROM NOW())
);
 
-- =============================================================
-- 3. METRIC DISPLAY REGISTRY
-- HOW to SHOW a metric in the UI
-- formula_latex removed — use method_id FK instead
-- =============================================================
CREATE TABLE IF NOT EXISTS metric_display_registry (
  id                    TEXT        PRIMARY KEY,
  label                 TEXT        NOT NULL,          -- display name in UI
  description           TEXT,                          -- tooltip / docs

  -- Taxonomy — used for filtering and grouping in UI
  category              TEXT,       -- energy|ipc|carbon|latency|quality|orchestration
  layer                 TEXT,       -- silicon|os|orchestration|application
  layer_order           INTEGER,    -- 1=silicon, 2=os, 3=orch, 4=app

  -- Method link — formula_latex lives in measurement_method_registry
  -- NULL = display-only metric with no formal measurement method yet
  method_id             TEXT        REFERENCES measurement_method_registry(id),
  formula_latex         TEXT,       -- KaTeX convenience copy for UI hover
                                    -- full method detail via method_id FK

  -- Display config
  unit_default          TEXT,       -- J | µJ | ms | ratio | %
  unit_options          JSONB,       -- JSON array: ["µJ","mJ","J","Wh"]
  unit_scales           JSONB,       -- JSON: {"µJ":1,"mJ":0.001,"J":0.000001}
  chart_type            TEXT        DEFAULT 'kpi',   -- kpi|bar|line|scatter|heatmap
  color_token           TEXT        DEFAULT 'accent.silicon', -- resolveToken() in UI
  significance          TEXT        DEFAULT 'supporting',
                                    -- thesis_core|supporting|debug

  -- Direction from goals YAML — used for threshold coloring
  direction             TEXT        DEFAULT 'lower_is_better',
                                    -- lower_is_better|higher_is_better|neutral
  display_precision     INTEGER     DEFAULT 2,        -- decimal places in UI

  -- Thresholds from goals/*.yaml — drives warn/severe coloring in UI
  warn_threshold        REAL,       -- yellow above this value
  severe_threshold      REAL,       -- red above this value
  threshold_unit        TEXT,       -- unit for threshold values

  -- Visibility — which products show this metric
  visible_in            JSONB        DEFAULT '["workbench"]', -- JSON array
  default_visible       INTEGER     DEFAULT 1,        -- shown by default?
  leaderboard           INTEGER     DEFAULT 0,        -- show in model leaderboard?

  -- Provenance hint — actual provenance captured per-run in measurement_methodology
  provenance_expected   TEXT        DEFAULT 'MEASURED',
                                    -- MEASURED|CALCULATED|INFERRED

  -- Source tracking — where this metric definition came from
  source_description    TEXT,       -- human readable: "RAPL /sys/class/powercap/..."
  source_yaml           TEXT,       -- which YAML file: "gui/report_engine/goals/energy.yaml"
  goal_id               TEXT,       -- which research goal: "energy_efficiency"

  active                INTEGER     DEFAULT 1,        -- 0 = soft delete
  sort_order            INTEGER     DEFAULT 0,        -- display order in UI
  created_at            DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW()),  -- Unix timestamp seconds
  updated_at            DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW())   -- Unix timestamp seconds
);
 
-- View: metric_display_registry + formula from method registry
-- Use this in PageRenderer instead of querying mdr directly
CREATE OR REPLACE VIEW metric_display_full AS
SELECT
  mdr.*,
  mmr.formula_latex,
  mmr.code_snapshot,
  mmr.parameters        AS method_parameters,
  mmr.provenance        AS method_provenance,
  mmr.validated         AS method_validated,
  mmr.validated_by      AS method_validated_by,
  mmr.fallback_method_id
FROM metric_display_registry mdr
LEFT JOIN measurement_method_registry mmr ON mmr.id = mdr.method_id;
 
-- =============================================================
-- 4. QUERY REGISTRY
-- HOW to FETCH and COMPUTE metrics
-- computed type handles tax_multiple, ooi_time etc
-- =============================================================
CREATE TABLE IF NOT EXISTS query_registry (
  id                    TEXT        PRIMARY KEY,
  name                  TEXT        NOT NULL,
  description           TEXT,
 
  metric_type           TEXT        NOT NULL,
  -- sql_aggregate | sql_rows | timeseries | computed | sql_column
 
  -- SQL (prefer sql_text — lives in DB, editable via Directus)
  -- sql_file is legacy fallback only
  sql_text              TEXT,
  sql_text_pg  TEXT  DEFAULT NULL,
  sql_file              TEXT        DEFAULT NULL,
  dialect_aware         INTEGER     DEFAULT 0,
  returns               TEXT        DEFAULT 'rows',
  -- single_row | rows | timeseries
 
  -- Computed metrics (metric_type = 'computed')
  -- tax_multiple = avg_agentic_j / avg_linear_j
  depends_on            JSONB,       -- JSON array of dependency ids
  formula               TEXT,       -- arithmetic formula string
 
  -- API
  endpoint_path         TEXT,
  group_name            TEXT        DEFAULT 'analytics',
  parameters            TEXT        DEFAULT '{}',
  enrich_metrics        INTEGER     DEFAULT 0,
  -- 1 = run compute_derived() after SQL, merge into response
  cache_ttl_sec         INTEGER     DEFAULT 30,
 
  -- Source tracking
  source_yaml           TEXT,
  source_tab            TEXT,
 
  active                INTEGER     DEFAULT 1,
  version               TEXT        DEFAULT '1.0',
  created_at            REAL  DEFAULT EXTRACT(EPOCH FROM NOW()),
  updated_at            REAL  DEFAULT EXTRACT(EPOCH FROM NOW())
);
 
-- =============================================================
-- 5. STANDARDIZATION REGISTRY
-- Versioned constants: carbon intensity, WUE, TDP
-- =============================================================
CREATE TABLE IF NOT EXISTS standardization_registry (
  id                    SERIAL PRIMARY KEY,
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
  created_at            REAL  DEFAULT EXTRACT(EPOCH FROM NOW())
);
 
-- =============================================================
-- 6. EVALUATION CRITERIA
-- From goals/*.yaml eval_criteria — per goal
-- =============================================================
CREATE TABLE IF NOT EXISTS eval_criteria (
  id                    SERIAL PRIMARY KEY,
  goal_id               TEXT        NOT NULL UNIQUE,
  stat_test             TEXT,
  alpha                 REAL        DEFAULT 0.05,
  effect_size           TEXT,
  min_runs_per_group    INTEGER     DEFAULT 5,
  report_ci             INTEGER     DEFAULT 1,
  ci_level              REAL        DEFAULT 0.95,
  comparison_mode       TEXT        DEFAULT 'relative',
  created_at            REAL  DEFAULT EXTRACT(EPOCH FROM NOW())
);
 
-- =============================================================
-- 7. COMPONENT REGISTRY
-- =============================================================
CREATE TABLE IF NOT EXISTS component_registry (
  name                  TEXT        PRIMARY KEY,
  group_name            TEXT,
  description           TEXT,
  props_schema          JSONB,
  data_shape            TEXT        DEFAULT 'flat_row',
  has_3d_twin           TEXT,
  export_pdf            INTEGER     DEFAULT 0,
  export_png            INTEGER     DEFAULT 0,
  export_csv            INTEGER     DEFAULT 0,
  available_in          TEXT        DEFAULT '["workbench"]',
  active                INTEGER     DEFAULT 1
);
 
-- =============================================================
-- 8. PAGE CONFIGS
-- =============================================================
CREATE TABLE IF NOT EXISTS page_configs (
  id                    TEXT        PRIMARY KEY,
  title                 TEXT        NOT NULL,
  slug                  TEXT,
  icon                  TEXT,
  description           TEXT,
  audience              JSONB        DEFAULT '["workbench"]',
  published             INTEGER     DEFAULT 0,
  sort_order            INTEGER     DEFAULT 0,
  created_at            REAL  DEFAULT EXTRACT(EPOCH FROM NOW()),
  updated_at            REAL  DEFAULT EXTRACT(EPOCH FROM NOW())
);
 
-- =============================================================
-- 9. PAGE SECTIONS
-- =============================================================
CREATE TABLE IF NOT EXISTS page_sections (
  id                    SERIAL PRIMARY KEY,
  page_id               TEXT        NOT NULL
    REFERENCES page_configs(id),
  position              INTEGER     NOT NULL,
  component             TEXT        NOT NULL,
  title                 TEXT,
  cols                  INTEGER     DEFAULT 1,
  query_id              TEXT
    REFERENCES query_registry(id),
  props                 TEXT        DEFAULT '{}',
  visible_in            TEXT        DEFAULT '["workbench"]',
  active                INTEGER     DEFAULT 1
);
 
-- =============================================================
-- 10. PAGE METRIC CONFIGS
-- =============================================================
CREATE TABLE IF NOT EXISTS page_metric_configs (
  id                    SERIAL PRIMARY KEY,
  section_id            INTEGER     NOT NULL
    REFERENCES page_sections(id),
  metric_id             TEXT        NOT NULL
    REFERENCES metric_display_registry(id),
  position              INTEGER     NOT NULL,
  label_override        TEXT,
  color_override        TEXT,
  unit_override         TEXT,
  thesis                INTEGER     DEFAULT 0,
  decimals              INTEGER     DEFAULT 2,
  active                INTEGER     DEFAULT 1
);
 
-- =============================================================
-- 11. MEASUREMENT METHODOLOGY
-- PER-RUN RECORD — written by agent every run
-- "Which method was used for run #1809"
-- =============================================================
CREATE TABLE IF NOT EXISTS measurement_methodology (
  id                    SERIAL PRIMARY KEY,
  run_id                INTEGER     NOT NULL,
  metric_id             TEXT        NOT NULL,
 
  -- FK to method definition (formula, code, references live there)
  method_id             TEXT
    REFERENCES measurement_method_registry(id),
  -- NULL = method not yet registered → audit_log warning
 
  -- Actual parameters used THIS run (may differ from method defaults)
  parameters_used       JSONB,
  -- JSON: {"idle_duration_sec":30,"sigma_threshold":2.0,
  --        "outliers_removed":2,"cpu_fraction_used":0.73}
 
  -- Computed result this run
  value_raw             REAL,
  value_unit            TEXT,
 
  -- Outcome
  provenance            TEXT        NOT NULL,
  hw_available          INTEGER,
  confidence            REAL,
  -- 1.0=direct, 0.7=inferred, 0.3=modelled
 
  -- Fallback tracking
  primary_method_failed INTEGER     DEFAULT 0,
  failure_reason        TEXT,
  -- "RAPL permission denied" | "CPU not supported"
 
  -- Standards used
  standard_ids          JSONB,       -- JSON array
 
  captured_at           REAL  DEFAULT EXTRACT(EPOCH FROM NOW())
);
 
-- =============================================================
-- 12. AUDIT LOG
-- =============================================================
CREATE TABLE IF NOT EXISTS audit_log (
  id                    SERIAL PRIMARY KEY,
  run_id                INTEGER,
  event_type            TEXT,
  event_detail          TEXT,
  metric_id             TEXT,
  value_before          TEXT,
  value_after           TEXT,
  hw_context            TEXT,
  logged_at             REAL  DEFAULT EXTRACT(EPOCH FROM NOW())
);

CREATE TABLE IF NOT EXISTS page_templates (
  id                TEXT        PRIMARY KEY,
  name              TEXT        NOT NULL,
  description       TEXT,
  audience          JSONB       DEFAULT '["workbench"]',
  sections_template JSONB,
  created_at        REAL  DEFAULT EXTRACT(EPOCH FROM NOW())
);
-- =============================================================
-- INDEXES
-- =============================================================
CREATE INDEX IF NOT EXISTS idx_page_sections_page
  ON page_sections(page_id, position);
CREATE INDEX IF NOT EXISTS idx_page_metric_section
  ON page_metric_configs(section_id, position);
CREATE INDEX IF NOT EXISTS idx_methodology_run
  ON measurement_methodology(run_id, metric_id);
CREATE INDEX IF NOT EXISTS idx_methodology_method
  ON measurement_methodology(method_id);
CREATE INDEX IF NOT EXISTS idx_audit_run
  ON audit_log(run_id, logged_at);
CREATE INDEX IF NOT EXISTS idx_query_active
  ON query_registry(active, endpoint_path);
CREATE INDEX IF NOT EXISTS idx_metric_active
  ON metric_display_registry(active, category);
CREATE INDEX IF NOT EXISTS idx_method_refs
  ON method_references(method_id);
