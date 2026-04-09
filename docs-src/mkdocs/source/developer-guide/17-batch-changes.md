# A-LEMS Platform — Batch Changes Guide
## Developer Guide 17: SSE, Sync, Research Endpoints, Universe

---

## What Was Changed

### BATCH 1 — Backend

#### auto_router.py — tax_multiple fix
**Problem:** `compute_batch(base, None)` had wrong signature — needed
`(metric_ids, params, registry, q_fn, q1_fn)` but none of those were available.

**Fix:** New `_compute_derived_from_db(base, get_conn)` reads
`depends_on` + `formula` directly from `query_registry` DB table.
Iterates up to 5 passes for chained dependencies.

**Result:** `tax_multiple`, `energy_per_token_uj`, `ooi_time` all
now appear in `/analytics/overview` response.

```bash
# Verify
curl -s http://localhost:8765/analytics/overview | python3 -m json.tool | grep -E "tax_multiple|energy_per_token|ooi_time"
# Expected: "tax_multiple": 4.09, "energy_per_token_uj": ...
```

#### sync.py — new file
Two-direction sync:
- `sync_metadata_down()` — pulls config tables from Oracle VM on startup
- `push_run_to_central(run_id)` — pushes run data up after each run
- `broadcast_run_complete(run_id, _subscribers)` — SSE notify all clients

Standalone mode: `CENTRAL_API_URL` not set → no network, no errors.

Wire into `server.py` lifespan:
```python
from sync import sync_metadata_down

@asynccontextmanager
async def lifespan(app: FastAPI):
    summary = await sync_metadata_down()
    if summary: logger.info(f"Metadata synced: {summary}")
    count = register_all_from_db(app, _conn)
    logger.info(f"✓ {count} endpoints registered")
    yield
```

Wire after each run completes in measurement agent:
```python
from sync import push_run_to_central, broadcast_run_complete
await push_run_to_central(run_id)
await broadcast_run_complete(run_id, _subscribers)
```

#### 012_research_endpoint_paths.sql — q01-q30 endpoints
Sets `endpoint_path` for all 30 research queries that had NULL paths.
After applying, `/internal/reload` registers them all as GET endpoints.

```bash
sqlite3 ~/mydrive/alems-platform/data/experiments.db \
  < scripts/migrations/012_research_endpoint_paths.sql
curl -X POST http://localhost:8765/internal/reload
# Expected: {"status":"reloaded","new_endpoints":30}
```

---

### BATCH 2 — Frontend

#### api/db/route.ts — MAX_ROWS protection
Added `MAX_ROWS = 2000` limit on array responses.

- Returns random sample + warning when exceeded
- User can bypass with `?full=1`
- Prevents browser hang on 10k+ rows

```typescript
// Response when sampled:
{
  data: [...2000 rows],
  sampled: true,
  sample_n: 2000,
  total_n: 15847,
  warning: "Showing 2000 of 15847 rows. Add ?full=1 to get all."
}
```

#### useSSE.ts — new hook
Connects to `/events` SSE stream.
On `run_complete` event:
1. Updates `useMetricsStore` (last_run_id, last_run_energy_j)
2. Invalidates TanStack Query cache for overview + runs
3. Auto-reconnects with exponential backoff (1s → 30s max)

Wire in layout or root page:
```typescript
import { useSSE } from "@/hooks/useSSE"
export default function RootLayout({ children }) {
  useSSE()   // singleton — call once at root
  return <>{children}</>
}
```

---

### BATCH 3 — New Components

#### ExperimentUniverse page
Path: `src/app/experiment-universe/page.tsx`

- Full-page Three.js canvas
- 469 experiments as 3D stars
- Visual mapping: X=Energy, Y=IPC, Z=TaskCategory
- Color: green=linear, red=agentic
- Glow: orange halo when tax_multiple > 3
- Click star → DetailPanel slides in
- Hover → tooltip with key metrics
- Auto-rotate OrbitControls
- PNG export button (preserveDrawingBuffer=true)
- Paper caption: "Figure 1: A-LEMS Experiment Universe"

#### ParticleBackground component
Path: `src/components/ParticleBackground.tsx`

Presets: `links` | `stars` | `fire` | `none`

Per-page assignments:
```
/overview        → links  opacity 0.08
/research        → stars  opacity 0.06
/fleet           → links  opacity 0.10
/experiment-*    → none   (Three.js is background)
/dispatch        → fire   opacity 0.15
```

#### FigureExport component
Path: `src/components/ui/FigureExport.tsx`

- Appears on hover — never clutters UI
- PNG: html2canvas at scale=3 (≈300 DPI)
- CSV: extracts data array → downloadable file
- Cite: copies formatted academic citation to clipboard
- Optional caption shown in Showcase mode

```typescript
<FigureExport
  number="Figure 1"
  caption="A-LEMS Experiment Universe showing 469 experiments"
  data={universeData}
  filename="figure1_universe"
>
  <MyChart />
</FigureExport>
```

---

## Copy Commands

```bash
SRC=~/Downloads
PLAT=~/mydrive/alems-platform
WORK=~/mydrive/alems-workbench/src

# BACKEND
cp $SRC/auto_router.py    $PLAT/auto_router.py
cp $SRC/sync.py           $PLAT/sync.py
sqlite3 $PLAT/data/experiments.db \
  < $SRC/012_research_endpoint_paths.sql
curl -X POST http://localhost:8765/internal/reload

# FRONTEND — new hook
mkdir -p $WORK/hooks
cp $SRC/useSSE.ts         $WORK/hooks/useSSE.ts

# FRONTEND — api/db route
cp $SRC/route.ts          $WORK/app/api/db/route.ts

# FRONTEND — new components
cp $SRC/ParticleBackground.tsx  $WORK/components/ParticleBackground.tsx
cp $SRC/FigureExport.tsx        $WORK/components/ui/FigureExport.tsx

# FRONTEND — ExperimentUniverse page
mkdir -p $WORK/app/experiment-universe
cp $SRC/ExperimentUniversePage.tsx  $WORK/app/experiment-universe/page.tsx

# DOCS
cp $SRC/17-batch-changes.md \
   $PLAT/docs-src/mkdocs/source/developer-guide/
```

---

## Targeted Fixes (apply manually)

### server.py — wire sync into lifespan
Find:
```python
async def lifespan(app: FastAPI):
    """Register dynamic endpoints from query_registry on startup."""
    count = register_all_from_db(app, _conn)
    logger.info(f"✓ {count} endpoints auto-registered from query_registry")
    yield
```
Replace with:
```python
async def lifespan(app: FastAPI):
    """Startup: sync metadata from central, register endpoints."""
    from sync import sync_metadata_down
    summary = await sync_metadata_down()
    if summary:
        logger.info(f"Metadata synced: {summary}")
    count = register_all_from_db(app, _conn)
    logger.info(f"✓ {count} endpoints auto-registered from query_registry")
    yield
```

### layout.tsx — wire SSE hook once at root
Add to providers or layout (client component only):
```typescript
import { useSSE } from "@/hooks/useSSE"
// Call useSSE() once inside a client component at root level
```

---

## Verify Everything

```bash
# 1. tax_multiple now returns value
curl -s http://localhost:8765/analytics/overview | python3 -m json.tool | grep tax_multiple
# Expected: "tax_multiple": 4.09

# 2. Research endpoints now live
curl -s http://localhost:8765/research/q01_energy_per_query | python3 -m json.tool | head -5

# 3. Universe page loads
# http://localhost:3000/experiment-universe

# 4. MAX_ROWS working
curl -s "http://localhost:3000/api/db?q=lens" | python3 -m json.tool | grep sampled
# Expected: "sampled": true (1817 rows > 2000 threshold... wait 1817 < 2000)
# So lens returns all rows — MAX_ROWS only triggers above 2000
```
