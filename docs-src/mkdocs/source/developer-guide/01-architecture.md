# A-LEMS Platform Architecture

## Repos
```
a-lems/            ← FROZEN v3.0-stable. Original Streamlit + agent.
alems-platform/    ← Active development. Backend + workbench.
alems-workbench/   ← Next.js frontend only.
```

## Data flow
```
Local SQLite (experiments.db)
    ↓ server.py reads directly
Workbench API :8765
    ↓ HTTP/SSE
Next.js Workbench :3000
```

```
Local agent → POST heartbeat/sync → Oracle VM FastAPI :8000 → PostgreSQL
```

## Services
| Service | Port | Command |
|---------|------|---------|
| Workbench API | 8765 | `uvicorn server:app --port 8765` |
| Next.js UI | 3000 | `npm run dev` |
| Oracle VM API | 8000 | `sudo systemctl restart alems-api` |

## DB modes
| Env var | Mode |
|---------|------|
| `ALEMS_DB_URL` not set | SQLite from `ALEMS_DB_PATH` |
| `ALEMS_DB_URL=postgresql://...` | PostgreSQL |

## 3 Products
| Product | Repo | Port | Audience |
|---------|------|------|----------|
| Workbench | alems-workbench | 3000 | Researcher |
| Showcase | TBD | 3001 | Professor |
| Commons | TBD | 3003 | Public |

## Key config files
| File | Purpose |
|------|---------|
| `config/metric_registry.yaml` | All metrics — provenance, formula, layer |
| `config/query_registry.yaml` | All SQL queries — no SQL in code |
| `config/app_settings.yaml` | App config |
| `config/models.json` | LLM models |
| `config/tasks.yaml` | Experiment tasks |
| `.env.local` | Frontend env vars |
