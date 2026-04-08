# Developer Setup

## Prerequisites
- Python 3.11+ with venv
- Node.js 18+
- Git

## Local setup (SQLite mode)

```bash
# 1. Backend
cd ~/mydrive/alems-platform
source venv/bin/activate
pip install fastapi uvicorn pyyaml httpx psycopg2-binary
GROQ_API_KEY=your_key uvicorn server:app --port 8765 --reload

# 2. Frontend
cd ~/mydrive/alems-workbench
npm install
npm run dev

# 3. Open
# http://localhost:3000
```

## PostgreSQL mode (Oracle VM data)
```bash
ALEMS_DB_URL=postgresql://alems:Ganesh123@129.153.71.47/alems_central \
uvicorn server:app --port 8765 --reload
```

## Adding a new metric (zero code change)
1. Add entry to `config/metric_registry.yaml`
2. Add query to `config/query_registry.yaml` (if custom SQL needed)
3. Restart server — appears in UI automatically

## Adding a new page
1. Create `src/app/{page}/page.tsx`
2. Add to sidebar in `src/components/layout/Sidebar.tsx`
3. No backend changes needed if using existing endpoints

## Environment variables
| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8765` | Backend URL |
| `NEXT_PUBLIC_DEFAULT_THEME` | `dark` | dark or light |
| `ALEMS_DB_PATH` | `data/experiments.db` | SQLite path |
| `ALEMS_DB_URL` | — | PostgreSQL URL (overrides SQLite) |
| `GROQ_API_KEY` | — | For Ask Me page |
