#!/usr/bin/env python3
"""
Local FastAPI stub server for web_search and api_query tools.

Returns deterministic responses keyed by query hash so repeated runs
produce identical data — required for energy measurement reproducibility.
Runs on localhost:8765. Started by experiment_runner before tool experiments.

NOT a real web search. Documented as controlled retrieval endpoint in
methodology doc 24. Real HTTP/TCP — real loopback I/O timing.
"""

import hashlib
import logging
import sqlite3
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Path to live experiments DB — stubs serve real experiment metrics
DB_PATH = "data/experiments.db"

app = FastAPI(title="A-LEMS Tool Stub Server", version="1.0.0")

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    """Liveness probe — experiment_runner calls this before tool experiments."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# /search — controlled information retrieval
# ---------------------------------------------------------------------------

@app.get("/search")
def search(q: str = Query(default="")):
    """
    Deterministic search over experiment data.
    Returns real experiment summary rows matching query keyword.
    Response is keyed by query hash for reproducibility.
    """
    results = _query_experiments(q)
    return JSONResponse(content={
        "query": q,
        "query_hash": hashlib.sha256(q.encode()).hexdigest()[:16],
        "results": results,
        "source": "controlled_retrieval_endpoint",  # explicit paper framing
    })


# ---------------------------------------------------------------------------
# /metrics — current run statistics
# ---------------------------------------------------------------------------

@app.get("/metrics")
def metrics():
    """
    Returns aggregate experiment metrics from live DB.
    Used by tg_sequential_3 and tg_deep_chain_4 tool graphs.
    """
    data = _get_metrics()
    return JSONResponse(content=data)


# ---------------------------------------------------------------------------
# /energy_summary — energy attribution summary
# ---------------------------------------------------------------------------

@app.get("/energy_summary")
def energy_summary():
    """
    Returns energy attribution summary for current experiments.
    Used by tg_parallel_2 tool graph — parallel with DB query.
    """
    data = _get_energy_summary()
    return JSONResponse(content=data)


# ---------------------------------------------------------------------------
# DB helper functions — all read-only, no writes
# ---------------------------------------------------------------------------

def _query_experiments(keyword: str) -> list:
    """
    Read experiment rows where name matches keyword.
    Returns at most 10 rows — sufficient for tool response content.
    """
    if not Path(DB_PATH).exists():
        return [{"title": "No DB", "snippet": "experiments.db not found"}]

    try:
        conn = sqlite3.connect(DB_PATH, timeout=3.0)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT exp_id, name, experiment_type, workflow_type "
            "FROM experiments "
            "WHERE name LIKE ? LIMIT 10",
            (f"%{keyword}%",),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows] or [
            {"title": "No results", "snippet": f"No experiments match: {keyword}"}
        ]
    except Exception as exc:
        logger.warning("stub_server _query_experiments error: %s", exc)
        return [{"title": "DB error", "snippet": str(exc)}]


def _get_metrics() -> dict:
    """Returns basic run counts and energy stats from live DB."""
    if not Path(DB_PATH).exists():
        return {"error": "experiments.db not found"}

    try:
        conn = sqlite3.connect(DB_PATH, timeout=3.0)
        row = conn.execute(
            "SELECT COUNT(*) as run_count, "
            "AVG(pkg_energy_uj) as avg_pkg_uj, "
            "MAX(pkg_energy_uj) as max_pkg_uj "
            "FROM runs WHERE pkg_energy_uj > 0"
        ).fetchone()
        conn.close()
        return {
            "run_count": row[0],
            "avg_pkg_energy_uj": round(row[1] or 0, 2),
            "max_pkg_energy_uj": round(row[2] or 0, 2),
            "source": "live_experiments_db",
        }
    except Exception as exc:
        logger.warning("stub_server _get_metrics error: %s", exc)
        return {"error": str(exc)}


def _get_energy_summary() -> dict:
    """Returns energy attribution summary — workflow_type breakdown."""
    if not Path(DB_PATH).exists():
        return {"error": "experiments.db not found"}

    try:
        conn = sqlite3.connect(DB_PATH, timeout=3.0)
        rows = conn.execute(
            "SELECT workflow_type, "
            "COUNT(*) as goals, "
            "AVG(overhead_fraction) as avg_overhead "
            "FROM goal_execution "
            "GROUP BY workflow_type"
        ).fetchall()
        conn.close()
        return {
            "breakdown": [
                {"workflow_type": r[0], "goals": r[1],
                 "avg_overhead_fraction": round(r[2] or 0, 4)}
                for r in rows
            ],
            "source": "goal_execution_table",
        }
    except Exception as exc:
        logger.warning("stub_server _get_energy_summary error: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# In-process launch helper — called by experiment_runner
# ---------------------------------------------------------------------------

_server_thread: threading.Thread = None


def start_stub_server(port: int = 8765) -> bool:
    """
    Start stub server in background daemon thread.
    Returns True if started, False if already running or failed.
    Idempotent — safe to call multiple times.
    Called by experiment_runner before any tool-using experiment.
    """
    global _server_thread

    # Check if already running via health endpoint
    try:
        import requests
        resp = requests.get(f"http://localhost:{port}/health", timeout=1.0)
        if resp.status_code == 200:
            logger.info("Stub server already running on port %d", port)
            return True
    except Exception:
        pass  # not running — proceed to start

    def _run():
        config = uvicorn.Config(
            app, host="127.0.0.1", port=port,
            log_level="warning",  # suppress uvicorn request logs in experiment output
        )
        server = uvicorn.Server(config)
        server.run()

    try:
        _server_thread = threading.Thread(target=_run, daemon=True)
        _server_thread.start()
        # Wait briefly for startup — 1s is sufficient for local loopback
        import time
        time.sleep(1.0)
        logger.info("Stub server started on port %d", port)
        return True
    except Exception as exc:
        logger.warning("Could not start stub server: %s", exc)
        return False
