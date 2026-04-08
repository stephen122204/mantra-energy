#!/usr/bin/env python3
"""
scripts/migrate_yaml_to_db.py
==============================
Migrates all YAML config files → DB tables.
Safe: uses INSERT OR REPLACE (idempotent, run multiple times).
Never deletes existing data.

Sources:
  config/query_registry.yaml    → query_registry table
  config/tasks.yaml             → task_categories + metric_display_registry
  gui/report_engine/goals/*.yaml → metric_display_registry + eval_criteria
  research_insights.yaml        → query_registry (inline SQL research queries)
  queries/*.sql                 → query_registry.sql_text

Usage:
  python scripts/migrate_yaml_to_db.py [--db data/experiments.db] [--dry-run]
"""

import sqlite3
import yaml
import json
import argparse
import sys
from pathlib import Path

BASE    = Path(__file__).parent.parent
CFG_DIR = BASE / "config"
SQL_DIR = BASE / "queries"
GOALS_DIR = BASE / "gui" / "report_engine" / "goals"

# ── Provenance mapping from goal metric descriptions ──────────────────────────
def _infer_provenance(metric: dict) -> str:
    formula = metric.get("formula", "")
    col     = metric.get("column", "")
    desc    = metric.get("description", "").lower()
    if formula and "/" in formula: return "CALCULATED"
    if "rapl" in desc or "sensor" in desc or "counter" in desc: return "MEASURED"
    if "estimate" in desc or "infer" in desc: return "INFERRED"
    if formula: return "CALCULATED"
    return "MEASURED"

# ── Color token mapping from category ────────────────────────────────────────
def _color_token(category: str, layer: str = "") -> str:
    mapping = {
        "energy":        "accent.silicon",
        "orchestration": "accent.orchestration",
        "ipc":           "accent.os",
        "carbon":        "accent.success",
        "latency":       "accent.warning",
        "quality":       "accent.info",
        "water":         "accent.info",
    }
    return mapping.get(category, "accent.silicon")

# ── Read SQL file for a query id ──────────────────────────────────────────────
def _read_sql(query_id: str) -> str | None:
    """Read SQL from queries/ folder. Returns None if not found."""
    # Try exact match first
    p = SQL_DIR / f"{query_id}.sql"
    if p.exists(): return p.read_text().strip()
    # Try subdirectories
    for sql_file in SQL_DIR.rglob(f"{query_id}.sql"):
        return sql_file.read_text().strip()
    return None

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: Migrate query_registry.yaml → query_registry table
# ─────────────────────────────────────────────────────────────────────────────
def migrate_query_registry(db, dry_run: bool = False) -> int:
    path = CFG_DIR / "query_registry.yaml"
    if not path.exists():
        print(f"  SKIP query_registry.yaml: not found at {path}")
        return 0

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    queries = data.get("queries", [])
    count   = 0

    for q in queries:
        qid      = q["id"]
        sql_file = q.get("query_file", f"{qid}.sql")
        sql_text = _read_sql(qid)
        params   = json.dumps(q.get("parameters", {}))

        # Map returns → endpoint path
        endpoint = f"/analytics/{qid}"

        row = {
            "id":            qid,
            "name":          q.get("name", qid),
            "description":   q.get("description", ""),
            "metric_type":   "sql_rows" if q.get("returns") == "rows" else "sql_aggregate",
            "sql_text":      sql_text,
            "sql_file":      sql_file if not sql_text else None,
            "dialect_aware": int(q.get("dialect_aware", False)),
            "returns":       q.get("returns", "rows"),
            "depends_on":    None,
            "formula":       None,
            "endpoint_path": endpoint,
            "group_name":    "analytics",
            "parameters":    params,
            "enrich_metrics":0,
            "cache_ttl_sec": q.get("cache_ttl_sec", 30),
            "source_yaml":   "config/query_registry.yaml",
            "source_tab":    None,
            "active":        1,
            "version":       "1.0",
        }

        if not dry_run:
            db.execute("""
                INSERT OR REPLACE INTO query_registry
                (id, name, description, metric_type, sql_text, sql_file,
                 dialect_aware, returns, depends_on, formula,
                 endpoint_path, group_name, parameters,
                 enrich_metrics, cache_ttl_sec,
                 source_yaml, source_tab, active, version)
                VALUES
                (:id,:name,:description,:metric_type,:sql_text,:sql_file,
                 :dialect_aware,:returns,:depends_on,:formula,
                 :endpoint_path,:group_name,:parameters,
                 :enrich_metrics,:cache_ttl_sec,
                 :source_yaml,:source_tab,:active,:version)
            """, row)
        count += 1
        sql_status = "✓ sql_text" if sql_text else "⚠ sql_file only"
        print(f"  {'[DRY]' if dry_run else 'INSERT'} query: {qid} ({sql_status})")

    if not dry_run:
        db.commit()
    print(f"  → {count} queries migrated from query_registry.yaml")
    return count

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: Migrate tasks.yaml → metric_display_registry
# ─────────────────────────────────────────────────────────────────────────────
def migrate_tasks(db, dry_run: bool = False) -> int:
    path = CFG_DIR / "tasks.yaml"
    if not path.exists():
        print(f"  SKIP tasks.yaml: not found at {path}")
        return 0

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    tasks = data.get("tasks", [])
    count = 0

    for task in tasks:
        tid = task["id"]
        # task_categories already populated — just ensure metric entry exists
        row = {
            "id":                 f"task_{tid}_energy",
            "label":              f"{task.get('name', tid)} Energy",
            "description":        task.get("description", ""),
            "category":           "energy",
            "layer":              "application",
            "layer_order":        4,
            "unit_default":       "J",
            "chart_type":         "bar",
            "color_token":        "accent.silicon",
            "formula_latex":      None,
            "significance":       "supporting",
            "direction":          "lower_is_better",
            "display_precision":  3,
            "provenance_expected":"MEASURED",
            "source_description": f"Task: {task.get('category','unknown')} level {task.get('level',1)}",
            "source_yaml":        "config/tasks.yaml",
            "goal_id":            None,
            "active":             1,
            "sort_order":         task.get("level", 1) * 10,
            "visible_in":         json.dumps(["workbench"]),
        }

        if not dry_run:
            db.execute("""
                INSERT OR IGNORE INTO metric_display_registry
                (id, label, description, category, layer, layer_order,
                 unit_default, chart_type, color_token, formula_latex,
                 significance, direction, display_precision,
                 provenance_expected, source_description,
                 source_yaml, goal_id, active, sort_order, visible_in)
                VALUES
                (:id,:label,:description,:category,:layer,:layer_order,
                 :unit_default,:chart_type,:color_token,:formula_latex,
                 :significance,:direction,:display_precision,
                 :provenance_expected,:source_description,
                 :source_yaml,:goal_id,:active,:sort_order,:visible_in)
            """, row)
        count += 1

    if not dry_run:
        db.commit()
    print(f"  → {count} task metrics from tasks.yaml")
    return count

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3: Migrate goals/*.yaml → metric_display_registry + eval_criteria
# ─────────────────────────────────────────────────────────────────────────────
def migrate_goals(db, dry_run: bool = False) -> int:
    if not GOALS_DIR.exists():
        print(f"  SKIP goals/: not found at {GOALS_DIR}")
        return 0

    goal_files = list(GOALS_DIR.glob("*.yaml"))
    total = 0

    for gf in goal_files:
        with open(gf) as f:
            data = yaml.safe_load(f) or {}

        goal = data.get("goal", {})
        if not goal:
            print(f"  SKIP {gf.name}: no 'goal' key")
            continue

        goal_id    = goal.get("goal_id", gf.stem)
        category   = goal.get("category", "efficiency")
        metrics    = goal.get("metrics", [])
        thresholds = goal.get("thresholds", {})
        eval_crit  = goal.get("eval_criteria", {})

        print(f"  Processing goal: {goal_id} ({len(metrics)} metrics)")

        # Migrate eval_criteria
        if eval_crit and not dry_run:
            db.execute("""
                INSERT OR REPLACE INTO eval_criteria
                (goal_id, stat_test, alpha, effect_size,
                 min_runs_per_group, report_ci, ci_level, comparison_mode)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                goal_id,
                eval_crit.get("stat_test", "mann_whitney"),
                eval_crit.get("alpha", 0.05),
                eval_crit.get("effect_size", "cohens_d"),
                eval_crit.get("min_runs_per_group", 5),
                int(eval_crit.get("report_ci", True)),
                eval_crit.get("ci_level", 0.95),
                eval_crit.get("comparison_mode", "relative"),
            ))

        # Migrate each metric
        for i, m in enumerate(metrics):
            col_name  = m.get("column", "")
            mid       = f"{goal_id}_{col_name}" if col_name else f"{goal_id}_metric_{i}"
            # Clean metric id
            mid = mid.replace("-", "_").replace(" ", "_").lower()

            unit      = m.get("unit", "")
            formula   = m.get("formula", "")
            threshold = thresholds.get(col_name, {})

            # Convert formula to LaTeX approximation
            latex = None
            if formula:
                # Simple substitutions for common patterns
                latex = formula \
                    .replace("/ 1e6", "/ 10^6") \
                    .replace("orchestration_cpu_ms", "t_{orch}") \
                    .replace("duration_ns", "t_{total}") \
                    .replace("compute_time_ms", "t_{compute}") \
                    .replace("total_energy_uj", "E_{total}") \
                    .replace("idle_baseline_uj", "E_{idle}") \
                    .replace("total_tokens", "N_{tokens}") \
                    .replace("NULLIF", "") \
                    .replace("(, 0)", "")

            row = {
                "id":                 mid,
                "label":              m.get("name", mid),
                "description":        m.get("description", ""),
                "category":           category,
                "layer":              goal.get("category", "efficiency"),
                "layer_order":        i + 1,
                "unit_default":       unit,
                "chart_type":         "kpi",
                "color_token":        _color_token(category),
                "formula_latex":      latex,
                "significance":       "thesis_core" if "ooi" in mid or "tax" in mid else "supporting",
                "direction":          m.get("direction", "lower_is_better"),
                "display_precision":  m.get("display_precision", 2),
                "warn_threshold":     threshold.get("warn"),
                "severe_threshold":   threshold.get("severe"),
                "threshold_unit":     threshold.get("unit"),
                "provenance_expected":_infer_provenance(m),
                "source_description": m.get("description", ""),
                "source_yaml":        f"gui/report_engine/goals/{gf.name}",
                "goal_id":            goal_id,
                "active":             1,
                "sort_order":         i,
                "visible_in":         json.dumps(["workbench"]),
                "default_visible":    1,
                "leaderboard":        1 if "ooi" in mid or "energy" in mid else 0,
            }

            if not dry_run:
                db.execute("""
                    INSERT OR REPLACE INTO metric_display_registry
                    (id, label, description, category, layer, layer_order,
                     unit_default, chart_type, color_token, formula_latex,
                     significance, direction, display_precision,
                     warn_threshold, severe_threshold, threshold_unit,
                     provenance_expected, source_description,
                     source_yaml, goal_id, active, sort_order,
                     visible_in, default_visible, leaderboard)
                    VALUES
                    (:id,:label,:description,:category,:layer,:layer_order,
                     :unit_default,:chart_type,:color_token,:formula_latex,
                     :significance,:direction,:display_precision,
                     :warn_threshold,:severe_threshold,:threshold_unit,
                     :provenance_expected,:source_description,
                     :source_yaml,:goal_id,:active,:sort_order,
                     :visible_in,:default_visible,:leaderboard)
                """, row)
            total += 1

        if not dry_run:
            db.commit()

    print(f"  → {total} goal metrics from {len(goal_files)} goal files")
    return total

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4: Migrate research_insights.yaml → query_registry
# ─────────────────────────────────────────────────────────────────────────────
def migrate_research_insights(db, dry_run: bool = False) -> int:
    path = BASE / "research_insights.yaml"
    if not path.exists():
        print(f"  SKIP research_insights.yaml: not found at {path}")
        return 0

    with open(path) as f:
        tabs = yaml.safe_load(f) or []

    count = 0
    for tab_data in tabs:
        tab_name  = tab_data.get("tab", "unknown")
        questions = tab_data.get("questions", [])

        for i, q in enumerate(questions):
            question = q.get("question", f"q_{i}")
            sql      = q.get("sql", "").strip()
            display  = q.get("display", {})

            # Generate a stable id from tab + question index
            safe_tab = tab_name.lower().replace(" ", "_")
            qid = f"ri_{safe_tab}_{i:02d}"

            row = {
                "id":            qid,
                "name":          question,
                "description":   question,
                "metric_type":   "sql_rows",
                "sql_text":      sql,
                "sql_file":      None,
                "dialect_aware": 0,
                "returns":       "rows",
                "depends_on":    None,
                "formula":       None,
                "endpoint_path": f"/research/{qid}",
                "group_name":    "research",
                "parameters":    json.dumps({}),
                "enrich_metrics":0,
                "cache_ttl_sec": 60,
                "source_yaml":   "research_insights.yaml",
                "source_tab":    tab_name,
                "active":        1,
                "version":       "1.0",
            }

            if not dry_run:
                db.execute("""
                    INSERT OR IGNORE INTO query_registry
                    (id, name, description, metric_type, sql_text, sql_file,
                     dialect_aware, returns, depends_on, formula,
                     endpoint_path, group_name, parameters,
                     enrich_metrics, cache_ttl_sec,
                     source_yaml, source_tab, active, version)
                    VALUES
                    (:id,:name,:description,:metric_type,:sql_text,:sql_file,
                     :dialect_aware,:returns,:depends_on,:formula,
                     :endpoint_path,:group_name,:parameters,
                     :enrich_metrics,:cache_ttl_sec,
                     :source_yaml,:source_tab,:active,:version)
                """, row)
            count += 1

    if not dry_run:
        db.commit()
    print(f"  → {count} research insight queries migrated")
    return count

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5: Seed core computed metrics
# ─────────────────────────────────────────────────────────────────────────────
def seed_computed_metrics(db, dry_run: bool = False) -> int:
    computed = [
        {
            "id":          "tax_multiple",
            "name":        "Orchestration Tax Multiple",
            "description": "Agentic vs linear energy ratio",
            "metric_type": "computed",
            "depends_on":  json.dumps(["avg_agentic_j", "avg_linear_j"]),
            "formula":     "avg_agentic_j / avg_linear_j",
            "endpoint_path": None,
            "group_name":  "analytics",
            "enrich_metrics": 0,
        },
        {
            "id":          "energy_per_token_uj",
            "name":        "Energy per Token (µJ)",
            "description": "Microjoules per token generated",
            "metric_type": "computed",
            "depends_on":  json.dumps(["total_energy_j", "avg_tokens", "total_runs"]),
            "formula":     "(total_energy_j * 1e6) / (avg_tokens * total_runs)",
            "endpoint_path": None,
            "group_name":  "analytics",
            "enrich_metrics": 0,
        },
        {
            "id":          "ooi_time",
            "name":        "OOI Time",
            "description": "Orchestration Overhead Index (time)",
            "metric_type": "computed",
            "depends_on":  json.dumps(["avg_planning_ms", "avg_execution_ms", "avg_synthesis_ms"]),
            "formula":     "avg_planning_ms / (avg_planning_ms + avg_execution_ms + avg_synthesis_ms)",
            "endpoint_path": None,
            "group_name":  "research",
            "enrich_metrics": 0,
        },
    ]

    for c in computed:
        if not dry_run:
            db.execute("""
                INSERT OR IGNORE INTO query_registry
                (id, name, description, metric_type,
                 sql_text, sql_file, dialect_aware, returns,
                 depends_on, formula,
                 endpoint_path, group_name, parameters,
                 enrich_metrics, cache_ttl_sec,
                 source_yaml, source_tab, active, version)
                VALUES (?,?,?,?,NULL,NULL,0,'single_row',?,?,?,?,'{}',0,0,
                        'computed_seed',NULL,1,'1.0')
            """, (
                c["id"], c["name"], c["description"], c["metric_type"],
                c["depends_on"], c["formula"],
                c["endpoint_path"], c["group_name"],
            ))
        print(f"  {'[DRY]' if dry_run else 'INSERT'} computed: {c['id']}")

    if not dry_run:
        db.commit()
    return len(computed)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6: Seed core page configs from known page structure
# ─────────────────────────────────────────────────────────────────────────────
def seed_page_configs(db, dry_run: bool = False) -> int:
    pages = [
        {"id": "overview",    "title": "Overview",           "slug": "/overview",    "icon": "◈", "sort_order": 1,  "audience": '["workbench","showcase"]'},
        {"id": "research",    "title": "Research Workbench", "slug": "/research",    "icon": "🔬", "sort_order": 2,  "audience": '["workbench"]'},
        {"id": "fleet",       "title": "Fleet",              "slug": "/fleet",       "icon": "🖥", "sort_order": 3,  "audience": '["workbench"]'},
        {"id": "sessions",    "title": "Sessions",           "slug": "/sessions",    "icon": "📂", "sort_order": 4,  "audience": '["workbench"]'},
        {"id": "experiments", "title": "Experiments",        "slug": "/experiments", "icon": "⚗", "sort_order": 5,  "audience": '["workbench"]'},
        {"id": "attribution", "title": "Attribution",        "slug": "/attribution", "icon": "🔀", "sort_order": 6,  "audience": '["workbench"]'},
        {"id": "validate",    "title": "Data Quality",       "slug": "/validate",    "icon": "✅", "sort_order": 7,  "audience": '["workbench"]'},
        {"id": "normalize",   "title": "Normalization",      "slug": "/normalize",   "icon": "📊", "sort_order": 8,  "audience": '["workbench"]'},
        {"id": "goals",       "title": "Research Goals",     "slug": "/goals",       "icon": "🎯", "sort_order": 9,  "audience": '["workbench"]'},
        {"id": "playground",  "title": "Playground",         "slug": "/playground",  "icon": "🎨", "sort_order": 99, "audience": '["workbench"]'},
    ]

    for p in pages:
        if not dry_run:
            db.execute("""
                INSERT OR IGNORE INTO page_configs
                (id, title, slug, icon, sort_order, audience, published)
                VALUES (?,?,?,?,?,?,1)
            """, (p["id"], p["title"], p["slug"], p["icon"], p["sort_order"], p["audience"]))
        print(f"  {'[DRY]' if dry_run else 'INSERT'} page: {p['id']}")

    # Seed overview page sections
    if not dry_run:
        db.execute("DELETE FROM page_sections WHERE page_id='overview'")
        sections = [
            (1, "overview", 1, "HeroBanner",      None,          "overview", "{}",                           1),
            (2, "overview", 2, "KPIStrip",         None,          "overview", '{"columns":6}',                1),
            (3, "overview", 3, "DataHealthBar",    None,          "overview", "{}",                           1),
            (4, "overview", 4, "EChartsBar",       "Tax by Task", "tax_by_task", '{"x_key":"task_name","y_key":"tax_percent","height":280}', 1),
            (5, "overview", 5, "PhaseBreakdown",   None,          "overview", "{}",                           1),
            (6, "overview", 6, "SustainabilityRow",None,          "overview", "{}",                           1),
            (7, "overview", 7, "RunsTable",        None,          "recent_runs", '{"limit":8}',               1),
        ]
        for s in sections:
            db.execute("""
                INSERT OR REPLACE INTO page_sections
                (id, page_id, position, component, title, query_id, props, active)
                VALUES (?,?,?,?,?,?,?,?)
            """, s)

    if not dry_run:
        db.commit()
    print(f"  → {len(pages)} pages seeded with overview sections")
    return len(pages)

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Migrate YAML config to DB")
    parser.add_argument("--db",      default="data/experiments.db")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"A-LEMS YAML → DB Migration")
    print(f"DB:      {args.db}")
    print(f"Dry run: {args.dry_run}")
    print(f"{'='*60}\n")

    if not Path(args.db).exists():
        print(f"ERROR: DB not found: {args.db}")
        print(f"Run migrations/010_config_tables.sql first")
        sys.exit(1)

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row

    # Verify tables exist
    tables = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    required = {"query_registry", "metric_display_registry", "page_configs"}
    missing  = required - tables
    if missing:
        print(f"ERROR: Missing tables: {missing}")
        print(f"Run: sqlite3 {args.db} < migrations/010_config_tables.sql")
        sys.exit(1)

    total = 0

    print("STEP 1: Migrating query_registry.yaml...")
    total += migrate_query_registry(db, args.dry_run)

    print("\nSTEP 2: Migrating tasks.yaml...")
    total += migrate_tasks(db, args.dry_run)

    print("\nSTEP 3: Migrating goals/*.yaml...")
    total += migrate_goals(db, args.dry_run)

    print("\nSTEP 4: Migrating research_insights.yaml...")
    total += migrate_research_insights(db, args.dry_run)

    print("\nSTEP 5: Seeding computed metrics...")
    total += seed_computed_metrics(db, args.dry_run)

    print("\nSTEP 6: Seeding page configs...")
    total += seed_page_configs(db, args.dry_run)

    db.close()

    print(f"\n{'='*60}")
    print(f"✓ Migration {'(dry run) ' if args.dry_run else ''}complete: {total} records")
    print(f"\nVerify:")
    print(f"  sqlite3 {args.db} \"SELECT COUNT(*) FROM query_registry;\"")
    print(f"  sqlite3 {args.db} \"SELECT COUNT(*) FROM metric_display_registry;\"")
    print(f"  sqlite3 {args.db} \"SELECT id FROM page_configs;\"")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()