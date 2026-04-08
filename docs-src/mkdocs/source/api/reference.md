# A-LEMS Workbench API

**File:** `server.py` | **Port:** 8765 | **DB:** SQLite (local) or PostgreSQL (env)

## Start
```bash
uvicorn server:app --host 0.0.0.0 --port 8765 --reload
# With PostgreSQL:
ALEMS_DB_URL=postgresql://alems:pass@localhost/alems_central uvicorn server:app --port 8765
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | DB status + mode |
| GET | `/machines` | All registered hardware |
| GET | `/experiments` | All experiments |
| GET | `/experiments/{id}` | Single experiment |
| GET | `/runs` | Runs (filter: exp_id, workflow) |
| GET | `/runs/{id}` | Single run + experiment join |
| GET | `/runs/{id}/samples/energy` | 100Hz RAPL samples |
| GET | `/runs/{id}/samples/cpu` | 10Hz CPU samples |
| GET | `/runs/{id}/events` | Orchestration events |
| GET | `/runs/{id}/llm` | LLM interactions |
| GET | `/analytics/overview` | Global KPIs |
| GET | `/analytics/tax` | Orchestration tax pairs |
| GET | `/analytics/domains` | Energy by task domain |
| GET | `/analytics/sessions` | Session aggregates |
| GET | `/analytics/hypotheses` | Hypothesis tracker |
| GET | `/analytics/outliers` | Flagged outlier runs |
| GET | `/jobs/queue` | Job queue |
| GET | `/events` | SSE stream |
| GET | `/metrics/registry` | All metrics from metric_registry.yaml |
| POST | `/metrics/query` | Dynamic metric query |
| POST | `/tools/query` | SQL console (SELECT only) |
| POST | `/observe/ask` | Ask Me — LLM + energy meters |

## Dynamic metric query
```json
POST /metrics/query
{"metric_id": "ooi_time", "parameters": {"run_id": 123}}
```
Metric definitions in `config/metric_registry.yaml`. Add metric → appears automatically.

## NFRs met
- Zero hardcoded SQL in routes
- SQLite or PostgreSQL via env var
- All queries parameterized (no injection)
- SQL console blocks DROP/DELETE/ALTER
