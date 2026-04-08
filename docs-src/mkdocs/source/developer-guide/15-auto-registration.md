# 15. Auto-Registration & PageRenderer

## Overview

A-LEMS uses a zero-code page configuration system. New pages, metrics, and
endpoints are added entirely through Directus — no code changes, no restarts.

```
Directus (admin UI)
    ↓ saves to PostgreSQL
FastAPI reads query_registry
    ↓ auto-registers GET /analytics/{id}
Next.js loadPage() fetches /pages/{id}
    ↓ PageRenderer looks up REGISTRY[component]
Browser renders real data
```

---

## Auto-Registration

### How It Works

On startup, `auto_router.py` reads every active row in `query_registry` where
`metric_type IN ('sql_aggregate', 'sql_rows', 'timeseries')` and
`endpoint_path IS NOT NULL`.

For each row it calls `app.add_api_route()` — making the endpoint live
immediately with no restart.

```python
# auto_router.py — simplified
rows = db.execute("SELECT * FROM query_registry WHERE active=1").fetchall()
for row in rows:
    handler = _make_handler(row, get_conn)
    app.add_api_route(path=row["endpoint_path"], endpoint=handler, methods=["GET"])
```

### Adding a New Endpoint — Zero Code Steps

1. Open Directus: `http://localhost:8055`
2. Go to **query_registry** → **Create item**
3. Fill in:

| Field | Value |
|-------|-------|
| `id` | `hallucination_rate` |
| `metric_type` | `sql_aggregate` |
| `sql_text` | `SELECT task_name, AVG(score) as avg FROM hallucination_events GROUP BY task_name` |
| `endpoint_path` | `/analytics/hallucination_rate` |
| `returns` | `rows` |
| `active` | `true` |

4. Click **Save & Publish**
5. Directus webhook fires → `POST /internal/reload`
6. `GET /analytics/hallucination_rate` is **live in ~2 seconds**

**Total time: 3 minutes. Code changed: zero. Files changed: zero. Restart: zero.**

### Validation at Startup

`auto_router.py` validates ALL rows before registering ANY endpoint.
If any active SQL row has `sql_text = NULL` and `sql_file = NULL`, the
server fails loudly with a clear error message pointing to the Directus URL.

This prevents silent failures where an endpoint appears registered but
returns empty data.

```
FileNotFoundError: query_registry[my_query]: sql_text and sql_file both NULL.
Fix: add sql_text in Directus admin.
URL: http://localhost:8055/admin/content/query_registry
```

### SQL Resolution Order

```
1. sql_text populated → use it (preferred, DB-managed)
2. sql_text NULL, sql_file set → read file from queries/ folder
3. Both NULL → ValueError at startup (loud failure)
```

For PostgreSQL-specific SQL, set `sql_text_pg`. Auto-router uses it
automatically when `ALEMS_DB_URL` is set.

---

## Computed Metrics

Some metrics cannot be expressed in SQL (ratios, formulas). These use
`metric_type = 'computed'` in `query_registry`.

```sql
-- Example: tax_multiple = avg_agentic_j / avg_linear_j
INSERT INTO query_registry (id, metric_type, depends_on, formula) VALUES
('tax_multiple', 'computed', '["avg_agentic_j","avg_linear_j"]', 'avg_agentic_j / avg_linear_j');
```

`metric_engine.py` resolves dependencies iteratively and evaluates
the formula using a safe AST-based evaluator (no `eval()`).

To trigger computation, set `enrich_metrics = 1` on the parent SQL query:
```sql
UPDATE query_registry SET enrich_metrics=1 WHERE id='overview';
```

The `/analytics/overview` response then includes `tax_multiple` automatically.

---

## PageRenderer

### Architecture

```
[pageId]/page.tsx (Server Component)
    ↓ loadPage(pageId) → FastAPI /pages/{pageId}
    ↓ fetches all query_ids in parallel
PageRenderer (Client Component)
    ↓ for each section → REGISTRY[section.component]
    ↓ passes { data, props, metrics, t }
Component renders
```

### REGISTRY

The REGISTRY in `PageRenderer.tsx` maps component names to React components:

```typescript
const REGISTRY: Record<string, React.FC<any>> = {
  HeroBanner,
  KPIStrip,
  TaxChart,
  // ... all components
}
```

**To add a new component:**
1. Build the component in `src/components/`
2. Import it in `PageRenderer.tsx`
3. Add to REGISTRY: `MyComponent`
4. Add to `component_registry` table in Directus
5. Add to `page_sections` in Directus for any page

Unknown components render `GhostPlaceholder` — never crashes.

### Component Contract

Every component registered in REGISTRY must accept these props:

```typescript
interface ComponentProps {
  data?:    any        // query result (single row or array)
  metrics?: any[]      // merged metric_display_registry rows
  props?:   any        // section-level props from page_sections.props JSON
  t?:       Theme      // theme object (Zustand)
  alpha?:   number     // glass alpha (default 0.82)
}
```

### Bare Components

Components in `BARE_COMPONENTS` render without a GlassCard wrapper:
```typescript
const BARE_COMPONENTS = new Set(["HeroBanner", "DataHealthBar"])
```

These handle their own container styling.

---

## Page Configuration via Directus

### Adding a Section to a Page

1. Open Directus → `page_sections`
2. Create row:

| Field | Value |
|-------|-------|
| `page_id` | `overview` |
| `position` | `8` |
| `component` | `TaxChart` |
| `query_id` | `tax_by_task` |
| `props` | `{"height": 400}` |

3. Save → page reloads with new section on next browser refresh

### Metric Display Config

Each section can have metrics from `page_metric_configs`:
- `label_override` — custom label (overrides registry default)
- `color_override` — custom color token
- `unit_override` — custom unit
- `thesis` — marks as thesis-critical (highlighted in UI)
- `decimals` — display precision

Registry default is used when override is NULL.

---

## Directus Webhook Setup

```bash
# In Directus admin:
# Settings → Webhooks → Create
# Name: reload-fastapi
# Event: items.create + items.update + items.delete
# Collections: query_registry, page_configs, page_sections, metric_display_registry
# URL: http://localhost:8765/internal/reload
# Method: POST
```

After saving any metadata in Directus, FastAPI auto-reloads in ~2 seconds.

---

## Two-Path Architecture

| Path | Used For | Examples |
|------|----------|---------|
| FastAPI `GET /analytics/*` | Display data (pre-aggregated) | KPIs, charts, phase breakdown |
| Next.js `POST /api/db` | Research instruments (raw rows) | LensExplorer, ParallelCoords, AgentFlow |

Research instruments need raw rows for dynamic filtering (D3 parallel
coordinates cannot work with pre-aggregated data). Display components
use FastAPI for speed and caching.

---

## File Reference

| File | Purpose |
|------|---------|
| `alems-platform/auto_router.py` | Reads query_registry, registers endpoints |
| `alems-platform/metric_engine.py` | Computes derived metrics (AST eval) |
| `alems-platform/server_additions.py` | /pages, /metrics/registry, /internal/reload |
| `alems-workbench/src/components/PageRenderer.tsx` | REGISTRY + render engine |
| `alems-workbench/src/lib/loadPage.ts` | Fetches page config from FastAPI |
| `alems-workbench/src/app/[pageId]/page.tsx` | Server component, parallel data fetch |

---

## Troubleshooting

**Server won't start — `sql_text and sql_file both NULL`**
→ Open Directus → query_registry → find the flagged row → add sql_text

**Page shows "No sections configured"**
→ Check page_configs.published = 1 for the page
→ Check page_sections rows exist for that page_id

**Component shows GhostPlaceholder**
→ Component name in page_sections doesn't match REGISTRY key
→ Check spelling — case-sensitive

**Tax multiple missing from /analytics/overview**
→ `UPDATE query_registry SET enrich_metrics=1 WHERE id='overview';`
→ Restart server

**New Directus save not reflected**
→ Check webhook is configured (Settings → Webhooks)
→ Manually call: `curl -X POST http://localhost:8765/internal/reload`
