# 16. Page System — Tables, Configuration, and Data Flow

## Overview

A-LEMS pages are fully data-driven. Every page, section, metric, and chart
is configured in the database and managed via Directus. Zero code changes
are needed to add a new page or modify an existing one.

```
Researcher opens Directus
    ↓ adds row to page_sections
FastAPI /pages/{id} returns updated config
    ↓ Next.js loadPage() fetches it
PageRenderer looks up REGISTRY[section.component]
    ↓ renders with real data
Browser shows new section — zero code change
```

---

## Tables Involved

### page_configs
One row per page per product.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | TEXT PK | URL slug: `overview`, `attribution`, `research` |
| `title` | TEXT | Display name in sidebar |
| `slug` | TEXT | Full URL path: `/overview` |
| `icon` | TEXT | Sidebar icon emoji |
| `description` | TEXT | Tooltip / meta description |
| `audience` | JSONB | `["workbench"]` or `["workbench","showcase"]` |
| `published` | INTEGER | 0=draft, 1=live |
| `sort_order` | INTEGER | Sidebar display order |

**Who populates:** Developer (initial), Researcher (edits via Directus)
**When:** Once per page, then maintained in Directus

### page_sections
Ordered sections within each page. One row = one rendered component.

| Column | Type | Purpose |
|--------|------|---------|
| `page_id` | TEXT FK | Links to page_configs.id |
| `position` | INTEGER | Render order (1=top) |
| `component` | TEXT | Must match REGISTRY key in PageRenderer.tsx |
| `query_id` | TEXT FK | Which query feeds this section's data |
| `title` | TEXT | Optional section header |
| `props` | JSONB | Component-specific config (height, columns, etc) |
| `cols` | INTEGER | Grid columns (future multi-column layout) |
| `active` | INTEGER | 0=hidden, 1=shown |

**Who populates:** Developer (initial via insert_pages.sql), Researcher (edits via Directus)
**When:** When building or modifying pages

**Example — add a tax chart to research page:**
```sql
INSERT INTO page_sections (page_id, position, component, query_id, props, active)
VALUES ('research', 3, 'TaxChart', 'tax_by_task', '{"height":400}', 1);
```

### page_metric_configs
Which metrics appear in each section (for KPI cards).
Allows section-level overrides of global metric display config.

| Column | Type | Purpose |
|--------|------|---------|
| `section_id` | INTEGER FK | Links to page_sections.id |
| `metric_id` | TEXT FK | Links to metric_display_registry.id |
| `position` | INTEGER | Display order within section |
| `label_override` | TEXT | Custom label (NULL = use registry default) |
| `color_override` | TEXT | Custom color token (NULL = use registry) |
| `unit_override` | TEXT | Custom unit (NULL = use registry) |
| `thesis` | INTEGER | 1 = highlight as thesis metric |
| `decimals` | INTEGER | Display precision override |

**Who populates:** Researcher via Directus
**When:** When customising which metrics appear where

### metric_display_registry
Master display configuration for every metric in the system.

| Column | Purpose |
|--------|---------|
| `id` | Unique metric ID: `tax_multiple`, `avg_agentic_j` |
| `label` | Display name |
| `formula_latex` | KaTeX formula shown in DrillDownPanel |
| `method_id` | FK → measurement_method_registry (scientific method) |
| `direction` | `lower_is_better` or `higher_is_better` |
| `warn_threshold` | Yellow threshold value |
| `severe_threshold` | Red threshold value |
| `significance` | `thesis_core` or `supporting` |
| `provenance_expected` | `MEASURED`, `CALCULATED`, or `INFERRED` |
| `goal_id` | Which research goal this metric belongs to |

**Who populates:** Developer (insert_metrics.sql), then Researcher via Directus
**When:** Once per metric, then maintained in Directus

---

## Adding a New Page — Step by Step

### Option A: Via SQL (developer)
```sql
-- 1. Add page config
INSERT INTO page_configs (id, title, slug, icon, audience, published, sort_order)
VALUES ('mypage', 'My Page', '/mypage', '📈', '["workbench"]', 1, 10);

-- 2. Add sections
INSERT INTO page_sections (page_id, position, component, query_id, props, active)
VALUES
  ('mypage', 1, 'HeroBanner', 'overview', '{}', 1),
  ('mypage', 2, 'EChartsBar', 'domains', '{"x_key":"task_name","y_key":"avg_energy_j","height":300}', 1),
  ('mypage', 3, 'RunsTable', 'recent_runs', '{"limit":10}', 1);
```

### Option B: Via Directus (researcher, zero SQL)
1. Open `http://localhost:8055`
2. Go to **page_configs** → Create item → fill in id, title, slug, published=true
3. Go to **page_sections** → Create items → set page_id, position, component, query_id
4. Open `http://localhost:3000/mypage` → page renders immediately

---

## Component Props Reference

Each component accepts props from `page_sections.props` JSON:

| Component | Props | Example |
|-----------|-------|---------|
| `KPIStrip` | `columns: number` | `{"columns": 6}` |
| `EChartsBar` | `x_key, y_key, height, orientation` | `{"x_key":"task_name","y_key":"avg_energy_j","height":300}` |
| `TaxChart` | `height: number` | `{"height": 320}` |
| `RunsTable` | `limit: number` | `{"limit": 10}` |
| `GhostPlaceholder` | `message, sub` | `{"message":"Coming soon"}` |

---

## SQLite vs PostgreSQL Behaviour

| Feature | SQLite | PostgreSQL |
|---------|--------|-----------|
| JSON columns | TEXT (stored as string) | JSONB (native JSON) |
| Timestamps | REAL (unix epoch) | DOUBLE PRECISION (unix epoch) |
| FK enforcement | Not enforced | Enforced — insert method first |
| Conflict handling | `INSERT OR REPLACE` | `INSERT ... ON CONFLICT DO NOTHING` |
| Directus | Not connected | Directus points at this DB |

**Directus always points at PostgreSQL (Oracle VM).**
Local SQLite is synced from PG via sync.py (metadata DOWN direction).

### Sync Flow
```
Researcher edits in Directus (PG)
    ↓ Directus webhook fires
POST /internal/reload on FastAPI
    ↓ sync.py pulls from PG → writes to local SQLite
Local FastAPI serves updated page config
```

**Data (runs, experiments) flows the other way:**
```
Local agent measures energy → SQLite
    ↓ /bulk-sync endpoint
PostgreSQL (central) receives new runs
```

---

## Page Audiences

Three products read from the same database, filtered by `audience`:

| Product | URL | Audience | Pages shown |
|---------|-----|----------|------------|
| Workbench | :3000 | `workbench` | All pages |
| Showcase | :3001 | `showcase` | overview, attribution, experiments |
| Commons | :3003 | `commons` | Public leaderboard (Phase 3) |

Set `NEXT_PUBLIC_AUDIENCE=workbench` in `.env.local`.

PageRenderer filters sections by audience automatically:
```typescript
section.visible_in.includes(audience)
```

---

## Music Per Page

Place audio files in `/public/audio/`:
```
/public/audio/universe.mp3    ← root page (galaxy nav)
/public/audio/overview.mp3    ← /overview
/public/audio/attribution.mp3 ← /attribution
/public/audio/research.mp3    ← /research
```

TopBar loads the file for the current route automatically.
Music is **off by default** — researcher toggles 🔇/🔊.
Missing file = button shows but stays silent (no error).

---

## Playground

`src/app/playground/page.tsx` is **never touched by PageRenderer**.
It is a standalone page preserved as the visual design system.
All new components are tested there first, then registered in REGISTRY.

Rule: **Playground is append-only. Nothing is ever removed.**
