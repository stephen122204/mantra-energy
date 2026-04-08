"""
A-LEMS Workbench API Server — Clean Query Layer v3.0
Run: uvicorn server:app --host 0.0.0.0 --port 8765 --reload
"""
import asyncio, os, re, sqlite3, uuid, yaml
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from metric_engine import compute_metric, compute_batch, load_metric_registry, invalidate_registry_cache
from contextlib import asynccontextmanager
from auto_router import register_all_from_db
from server_additions import add_config_endpoints
import logging
logger = logging.getLogger(__name__)


BASE    = Path(__file__).parent
DB_PATH = Path(os.environ.get("ALEMS_DB_PATH", str(BASE / "data" / "experiments.db")))
DB_URL  = os.environ.get("ALEMS_DB_URL", "")
CFG_DIR = BASE / "config"
SQL_DIR = BASE / "queries"
QR_PATH = CFG_DIR / "query_registry.yaml"
MR_PATH = CFG_DIR / "metric_registry.yaml"

def _is_pg(): return bool(DB_URL)

@contextmanager
def _conn():
    if _is_pg():
        import psycopg2, psycopg2.extras
        con = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        try: yield con
        finally: con.close()
    else:
        con = sqlite3.connect(str(DB_PATH), timeout=15)
        con.row_factory = sqlite3.Row
        try: yield con
        finally: con.close()

def _adapt_sql(sql: str, params: dict):
    if _is_pg():
        adapted = re.sub(r':(\w+)', r'%(\1)s', sql)
        return adapted, params
    return sql, params

def q(sql: str, params: dict = {}) -> List[Dict]:
    adapted, p = _adapt_sql(sql, params)
    with _conn() as con:
        cur = con.cursor()
        cur.execute(adapted, p)
        return [dict(r) for r in cur.fetchall()]

def q1(sql: str, params: dict = {}) -> Optional[Dict]:
    rows = q(sql, params)
    return rows[0] if rows else None

def _load_query_registry() -> dict:
    if not QR_PATH.exists(): return {}
    with open(QR_PATH) as f: data = yaml.safe_load(f) or {}
    return {qd["id"]: qd for qd in data.get("queries", [])}

def _load_sql(query_id: str) -> str:
    dialect = "pg" if _is_pg() else "sqlite"
    specific = SQL_DIR / f"{query_id}.{dialect}.sql"
    if specific.exists(): return specific.read_text()
    shared = SQL_DIR / f"{query_id}.sql"
    if shared.exists(): return shared.read_text()
    raise FileNotFoundError(f"No SQL file for: {query_id}")

def exec_named_query(query_id: str, params: dict = {}) -> Any:
    registry = _load_query_registry()
    qdef = registry.get(query_id)
    if not qdef: raise HTTPException(404, f"Query '{query_id}' not in registry")
    sql = _load_sql(query_id)
    if qdef.get("returns") == "single_row": return q1(sql, params)
    return q(sql, params)

def _metric_reg():
    return load_metric_registry(MR_PATH)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Register dynamic endpoints from query_registry on startup."""
    count = register_all_from_db(app, _conn)
    logger.info(f"✓ {count} endpoints auto-registered from query_registry")
    yield

app = FastAPI(title="A-LEMS API", version="2.0.0", lifespan=lifespan)


app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_subscribers: Dict[str, asyncio.Queue] = {}

@app.get("/events")
async def sse_stream(request: Request):
    q_ = asyncio.Queue(maxsize=100)
    cid = str(uuid.uuid4())
    _subscribers[cid] = q_
    async def gen():
        try:
            while not await request.is_disconnected():
                try:
                    data = await asyncio.wait_for(q_.get(), timeout=30)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {{\"ping\":true}}\n\n"
        finally: _subscribers.pop(cid, None)
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/health")
def health():
    ok = True
    try: q("SELECT 1")
    except: ok = False
    return {"status":"ok","db":"postgresql" if _is_pg() else "sqlite","db_ok":ok,"queries":list(_load_query_registry().keys())}

@app.post("/query/{query_id}")
def run_query_post(query_id: str, body: dict = {}):
    params = body.get("parameters", {}) if isinstance(body, dict) else {}
    result = exec_named_query(query_id, params)
    if isinstance(result, list): return {"query_id":query_id,"rows":result,"count":len(result)}
    return {"query_id":query_id,"row":result}

@app.get("/query/{query_id}")
def run_query_get(query_id: str):
    result = exec_named_query(query_id, {})
    if isinstance(result, list): return {"query_id":query_id,"rows":result,"count":len(result)}
    return {"query_id":query_id,"row":result}

@app.get("/analytics/overview")
def get_overview(): return exec_named_query("overview", {})

@app.get("/analytics/tax")
def get_tax(): return exec_named_query("tax_by_task", {})

@app.get("/analytics/domains")
def get_domains(): return exec_named_query("domains", {})

@app.get("/analytics/sessions")
def get_sessions(): return exec_named_query("sessions", {})

@app.get("/analytics/research-metrics")
def get_research_metrics(): return exec_named_query("research_metrics", {})

@app.get("/runs")
def get_runs(limit: int = 50, exp_id: Optional[int] = None, workflow: Optional[str] = None):
    rows = exec_named_query("recent_runs", {"limit": limit})
    if isinstance(rows, dict): rows = rows.get("rows", [])
    if exp_id:   rows = [r for r in rows if r.get("exp_id") == exp_id]
    if workflow: rows = [r for r in rows if r.get("workflow_type") == workflow]
    return rows

@app.get("/runs/{run_id}/samples/energy")
def get_energy_samples(run_id: int, downsample: int = 1):
    rows = exec_named_query("energy_samples", {"run_id": run_id})
    if isinstance(rows, dict): rows = rows.get("rows", [])
    return rows[::downsample] if downsample > 1 else rows

@app.get("/machines")
def get_machines():
    return q("SELECT hw_id,hostname,cpu_model,cpu_cores,ram_gb,agent_status,last_seen,agent_version FROM hardware_config ORDER BY last_seen DESC")

@app.get("/metrics/registry")
def get_metric_registry():
    return list(_metric_reg().values())

@app.post("/metrics/registry/reload")
def reload_metric_registry():
    invalidate_registry_cache()
    return {"status": "ok", "count": len(_metric_reg())}

class MetricQueryRequest(BaseModel):
    metric_id: str
    parameters: Dict[str, Any] = {}

@app.get("/metrics/batch")
def get_batch_metrics(
    significance: Optional[str] = None,
    layer: Optional[str] = None,
    run_id: Optional[int] = None,
    workflow: Optional[str] = None,
):
    reg = _metric_reg()
    params = {}
    if run_id:   params["run_id"]  = run_id
    if workflow: params["workflow"] = workflow
    results = compute_batch(
        metric_ids=[],
        params=params,
        registry=reg,
        q_fn=q,
        q1_fn=q1,
        filter_significance=significance,
        filter_layer=layer,
    )
    return {"metrics": results, "count": len(results)}
@app.get("/metrics/overview")
def get_overview_metrics():
    reg = _metric_reg()
    thesis_ids = ["tax_multiplier","ooi_time","ucr",
                  "energy_per_token_uj","avg_power_w","carbon_g_per_query"]
    cache = {}
    results = {}
    for mid in thesis_ids:
        try:
            r = compute_metric(mid, {}, reg, q, q1, cache=cache)
            results[mid] = r.get("value")
            if r.get("error"):
                results[f"{mid}_error"] = r["error"]
        except Exception as e:
            results[mid] = None
            results[f"{mid}_error"] = str(e)
    return results
 
@app.post("/metrics/query")
def query_metric(body: MetricQueryRequest):
    reg = _metric_reg()
    try:
        return compute_metric(
            metric_id=body.metric_id,
            params=body.parameters,
            registry=reg,
            q_fn=q,
            q1_fn=q1,
        )
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))

BLOCKED = ["drop","delete","truncate","alter","insert","update","create","replace"]

@app.post("/tools/query")
def run_sql(body: dict):
    sql = body.get("sql","")
    low = sql.strip().lower()
    for kw in BLOCKED:
        if low.startswith(kw): raise HTTPException(400, f"'{kw}' not allowed")
    try: return {"rows": q(sql), "count": len(q(sql))}
    except Exception as e: raise HTTPException(400, str(e))

@app.post("/observe/ask")
def ask_me(body: dict):
    question = body.get("question","")
    api_key  = os.environ.get("GROQ_API_KEY","")
    if not api_key: return {"answer":"GROQ_API_KEY not set","energy_j":0,"carbon_g":0,"water_ml":0,"methane_mg":0}
    try:
        import httpx
        res    = httpx.post("https://api.groq.com/openai/v1/chat/completions",headers={"Authorization":f"Bearer {api_key}"},json={"model":"llama-3.3-70b-versatile","messages":[{"role":"user","content":question}],"max_tokens":500},timeout=30)
        data   = res.json()
        answer = data["choices"][0]["message"]["content"]
        tokens = data["usage"]["total_tokens"]
        ej     = tokens*0.000001
        return {"answer":answer,"tokens":tokens,"energy_j":ej,"carbon_g":ej*0.233,"water_ml":ej*0.5,"methane_mg":ej*0.1}
    except Exception as e: return {"answer":str(e),"energy_j":0,"carbon_g":0,"water_ml":0,"methane_mg":0}

add_config_endpoints(app, q, q1)

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8765, reload=True)
