# A-LEMS Platform — Production Spec V2
# Handover Document for Next Agent
# Session: April 2026 | Status: HOURS 1-7 COMPLETE

---

## WHAT IS WORKING RIGHT NOW

```
✓ FastAPI :8765 — serving real data
✓ /analytics/overview — 34 fields, 1817 runs
✓ /analytics/tax_by_task — paired tax data
✓ /analytics/recent_runs — 26 columns per run
✓ /analytics/domains, sessions, research_metrics — all live
✓ /pages/overview — 7 sections from DB (not YAML)
✓ /metrics/registry — 25+ metrics with formulas
✓ Auto-registration — query_registry → endpoints on startup
✓ Next.js :3000 — loads /overview from DB via PageRenderer
✓ 7 themes working — Zustand persisted
✓ TopBar — themes, BG options, glass slider, music toggle
✓ Playground — all viz components preserved, never touched
✓ SQLite: 30 queries, 62 metrics, 46 components, 10 pages
✓ PostgreSQL (Oracle VM): same tables via DBeaver
```

## WHAT IS NOT YET WORKING

```
✗ tax_multiple in /analytics/overview response
  Fix: in auto_router.py line 120:
       from metric_engine import compute_derived as compute_batch

✗ TaxChart shows negative values
  Fix: already in insert_pages.sql — WHERE tax_percent > 0 in SQL

✗ Root page / still old hardcoded page
  Fix: replace src/app/page.tsx with UniversePage.tsx

✗ DrillDownPanel not wired to KPIStrip clicks
  Fix: KPIStrip needs onDrill prop wired (next sprint)

✗ PG sync not automated
  Fix: sync.py needs wiring (Phase 2)

✗ Directus not installed
  Fix: Hour 11-12 per SPEC-05
```

---

## REPO STRUCTURE

```
alems-platform/         ← FastAPI + SQLite + measurement agents
  server.py             ← FastAPI app v3.0 (DO NOT REWRITE — update only)
  auto_router.py        ← reads query_registry → registers endpoints
  server_additions.py   ← /pages, /metrics, /internal/reload endpoints
  metric_engine.py      ← AST-safe formula evaluator
  sync.py               ← metadata sync PG↔SQLite (not yet wired)
  data/experiments.db   ← SQLite: 1817 runs, all config tables
  queries/              ← 39 SQL files (all loaded into query_registry)
  config/               ← YAML files (safety net until Directus live)
  scripts/migrations/   ← 010_config_tables.sql, insert_pages.sql, etc.
  docs-src/mkdocs/      ← MkDocs documentation

alems-workbench/        ← Next.js frontend :3000
  src/
    app/
      page.tsx          ← ROOT → replace with UniversePage.tsx
      [pageId]/page.tsx ← DB-driven dynamic pages (loadPage)
      playground/       ← NEVER TOUCH — append only
      layout.tsx        ← Server component, no "use client"
    components/
      PageRenderer.tsx  ← REGISTRY + render engine
      layout/
        TopBar.tsx       ← themes, BG, glass slider, music
        Sidebar.tsx      ← nav sidebar (existing, untouched)
      overview/          ← HeroBanner, KPIStrip, TaxChart, etc.
      charts/
        EChartsBase.tsx  ← base for all ECharts components
      viz/               ← ALL playground-tested viz components
        UniverseNav.tsx, GalaxyShader.tsx, LensExplorer.tsx,
        AgentFlowGraph.tsx, AttributionExplorer.tsx,
        NormalizationValidation.tsx, SiliconJourney.tsx
      ui/
        DrillDownPanel.tsx ← full metric detail, KaTeX, methodology
        FormulaTooltip.tsx, GlassCard.tsx, ProvenanceBadge.tsx
    store/
      index.ts           ← re-exports all 4 stores
      stores.ts          ← all 4 Zustand stores (theme, metrics, filter, config)
    lib/
      theme.ts           ← 7 themes, LOCKED, never change token names
      ThemeContext.tsx   ← thin Zustand wrapper (backward compat)
      loadPage.ts        ← fetches page config from FastAPI
      api.ts             ← TanStack Query hooks (useOverview, useTax, etc.)
      schemas.ts         ← Zod schemas (partially working — Zod v4 migration needed)
      config.ts          ← all env vars, no hardcoding
```

---

## DATABASE SCHEMA (COMPLETE)

### SQLite: /home/dpani/mydrive/alems-platform/data/experiments.db
### PostgreSQL: alems_central on Oracle VM (129.153.71.47)

**Original tables (measurement data — never touch):**
```
runs (1817r)              — main measurements, 90+ columns
experiments (503r)        — experiment metadata
energy_samples (785k)     — raw RAPL readings
cpu_samples (166k)        — CPU performance counters
orchestration_events      — phase/event timing per run
orchestration_tax_summary — paired linear↔agentic comparisons
llm_interactions          — per-LLM-call metrics
agent_decision_tree       — decision flow (35 dummy records)
hardware_config           — 1 real + 4 dummy hardware profiles
task_categories (17r)     — task→category mapping
idle_baselines            — energy baselines per run
```

**New config tables (migration 010):**
```
measurement_method_registry  — HOW metrics are measured (manual, Directus)
method_references            — scientific citations for methods (manual, Directus)
metric_display_registry      — HOW to display metrics in UI (62 rows)
query_registry               — SQL + computed metrics → auto-endpoints (56 active)
standardization_registry     — versioned constants: carbon intensity, WUE (4 rows)
eval_criteria                — stat tests per research goal
component_registry           — all 46 React components (46 rows)
page_configs                 — 10 pages (10 rows)
page_sections                — ordered sections per page
page_metric_configs          — which metrics in each section
page_templates               — reusable page layouts (empty, populate later)
measurement_methodology      — per-run method record (automatic)
audit_log                    — per-event trace (automatic)
metric_display_full (VIEW)   — joins metric_display_registry + method registry
```

---

## MANUAL vs AUTOMATIC — WHO POPULATES WHAT

```
MANUAL (Researcher via Directus):
  measurement_method_registry  — method definitions, formulas, code
  method_references            — paper/manual citations
  standardization_registry     — carbon intensity, WUE (update annually)
  page_configs                 — page definitions
  page_sections                — sections per page
  page_metric_configs          — metrics per section
  metric_display_registry      — how to display each metric
  component_registry           — when new component is built
  query_registry               — when new SQL endpoint needed

AUTOMATIC (Measurement agent):
  runs                         — after each run
  experiments                  — when experiment created
  measurement_methodology      — per-run, per-metric
  audit_log                    — every event
  orchestration_events         — per orchestration event
  llm_interactions             — per LLM call

SEMI-AUTOMATIC (agent writes, researcher reviews NULLs):
  measurement_methodology.method_id  — agent matches, NULLs reviewed
```

---

## KEY DESIGN DECISIONS (LOCKED)

```
1. formula_latex lives in measurement_method_registry ONLY
   metric_display_registry.method_id FK points there
   UI reads via metric_display_full VIEW

2. tax_multiple computed server-side by metric_engine.py
   query_registry: depends_on + formula fields
   enrich_metrics=1 on overview query → merged into response
   UI never computes — only displays

3. /api/db POST for research instruments (raw rows)
   FastAPI GET /analytics/* for display data (aggregated)
   TanStack Query wraps both identically

4. Playground preserved forever — append only
   src/app/playground/page.tsx never touched by PageRenderer

5. All colors from t.* tokens — zero hardcoding
   theme.ts is LOCKED — never change token names

6. ECharts for all 2D charts — Recharts dropped entirely

7. Zustand for ALL state — no React Context for state
   ThemeContext.tsx is a thin backward-compat wrapper only

8. No Next.js API routes for display data
   /api/db is research instrument only (raw rows, SELECT only)

9. Timestamps: REAL DEFAULT (unixepoch()) SQLite
              DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW()) PG

10. SQL dialect: :named params everywhere
    _adapt_sql() in server.py converts to %(name)s for PG
```

---

## ENVIRONMENT VARIABLES

```bash
# alems-workbench/.env.local
NEXT_PUBLIC_API_URL=http://localhost:8765
NEXT_PUBLIC_DATA_MODE=local
SQLITE_PATH=/home/dpani/mydrive/alems-platform/data/experiments.db
NEXT_PUBLIC_AUDIENCE=workbench

# alems-platform (shell or .env)
ALEMS_DB_PATH=data/experiments.db
ALEMS_DB_URL=                    # empty = SQLite, set for PostgreSQL
CENTRAL_API_URL=                 # set when VM sync needed
```

---

## DEPLOY PATTERN

```bash
# Backend
cd ~/mydrive/alems-platform
uvicorn server:app --host 0.0.0.0 --port 8765 --reload

# Frontend
cd ~/mydrive/alems-workbench
npm run dev  # → :3000

# Copy files
SRC=~/Downloads
DEST=~/mydrive/alems-workbench/src
cp $SRC/file.tsx $DEST/path/

# SSH tunnel to Oracle VM
ssh -i ~/ssh-key-2026-03-26.key -L 5434:localhost:5432 dpani@129.153.71.47 -N

# PG migrations (via tunnel)
psql "host=localhost port=5434 dbname=alems_central user=alems password=Ganesh123" \
  -f scripts/migrations/010_config_tables.pg.sql
```

---

## NEXT PRIORITIES (Hours 8-15 from SPEC-05)

```
Hour 8:  Fix tax_multiple (compute_derived import in auto_router.py)
Hour 9:  Wire root page → UniversePage.tsx
Hour 10: Wire DrillDownPanel to KPIStrip clicks
Hour 11: Install Directus on Oracle VM
Hour 12: Configure Directus webhook → /internal/reload
Hour 13: Run insert_pages.sql + insert_metrics.sql on both DBs
Hour 14: Test all 10 pages render correctly from DB
Hour 15: Verify YAML files can be deleted (DB is source of truth)

Phase 2 (next agent):
  - Zustand + Zod full integration (schemas.ts Zod v4 migration)
  - SubgoalTree component for /goals page
  - HardwareProfile + LiveRunMonitor for /fleet page
  - ExperimentCompare (A vs B diff) component
  - PhaseSwimLane (horizontal timeline) component
  - ModelLeaderboard (ml.energy style, 9 dimensions)
  - ExecutionTimeline3D (3D Gantt)
  - Monaco SQL editor for research page
  - SSE live stream wiring (useMetricsStore)
  - PG sync automation (sync.py wiring)
  - Directus webhook configuration
  - Authentication (NextAuth, Phase 3)
```

---

## DATA FACTS (for realistic testing)

```
1817 runs total: 904 linear + 913 agentic
469 experiments, 17 task types, 4 categories
Mean agentic: 252.5J, mean linear: 62.7J, tax: ~4.0×
avg_ipc: 0.94, avg_cache_miss: 37%, avg_carbon: 15mg
DRAM=NULL (i7-1165G7 RAPL limitation — known)
774 noisy env runs (background_cpu > 10%)
17 runs with no baseline
0 invalid, 0 throttled (data quality is good)
Dummy data: 4 hw configs, 9 runs, 35 decisions (tagged dummy_*)
```

---

## FILES DELIVERED THIS SESSION

```
BACKEND:
  auto_router.py              ← reads query_registry → live endpoints
  server_additions.py         ← /pages, /metrics, /internal/reload
  research_metrics.sql        ← OOI/UCR SQL (queries/drilldown/)

FRONTEND:
  TopBar.tsx                  ← themes, BG, glass slider, music
  UniversePage.tsx            ← root page (galaxy nav)
  PageRenderer.tsx            ← REGISTRY v2, drilldown, EChartsBar
  DrillDownPanel.tsx          ← full metric detail panel
  EChartsBase.tsx             ← base chart wrapper
  HeroBanner.tsx              ← animated hero with live indicator
  KPIStrip.tsx                ← 6 KPI tiles with count-up
  TaxChart.tsx                ← ECharts horizontal bar
  PhaseBreakdown.tsx          ← stacked phase bar
  SustainabilityRow.tsx       ← carbon + water + methane
  DataHealthBar.tsx           ← data quality flags (bare)
  RunsTable.tsx               ← recent runs table
  loadPage.ts                 ← fetches page from FastAPI
  api.ts                      ← TanStack hooks
  ThemeContext.tsx             ← Zustand wrapper
  stores.ts                   ← all 4 Zustand stores

MIGRATIONS:
  010_config_tables.sql       ← all 12 config tables
  010_config_tables.pg.sql    ← PostgreSQL version
  insert_pages.sql            ← 10 pages fully configured
  insert_metrics.sql          ← 25+ metrics with formulas

DOCS:
  15-auto-registration.md     ← auto-router + PageRenderer guide
  16-page-system.md           ← page tables, who populates, SQLite/PG

HANDOVER:
  ALEMS_PRODUCTION_SPEC_V2.md ← this file
```

---

## KNOWN ISSUES (fix before production)

```
1. tax_multiple null in overview
   Fix: auto_router.py line 120 → from metric_engine import compute_derived as compute_batch

2. TaxChart shows negative values  
   Fix: WHERE tax_percent > 0 in tax_by_task SQL (update query_registry)

3. Root page / is old hardcoded page
   Fix: replace src/app/page.tsx with UniversePage.tsx

4. Zod v4 schemas broken (PageConfigSchema.safeParse fails)
   Fix: Zod v4 changed API — schemas.ts needs updating
   Workaround: loadPage.ts skips Zod validation (returns raw JSON)

5. KPIStrip drilldown not wired
   Fix: add onDrill prop call when tile is clicked

6. Universe not theme-aware (hardcoded dark colors)
   Fix: replace "rgba(9,13,19,...)" with glassColor(t, alpha)
        replace "#7090b0" with t.text.secondary

7. ReactFlow nodeTypes warning in AgentFlowGraph
   Fix: define RF_NODE_TYPES = {} outside component
```
